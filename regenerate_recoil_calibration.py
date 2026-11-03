"""
Regenerate the recoil-prediction population regression from the live database.

Institutionalized replacement for the hand-baked ``CALIBRATION`` dict in
``core_prediction_playground.py``.  Run whenever new cruises have added rows to
``recoil_analysis_results`` and the population regression should reflect them.

Usage::

    python regenerate_recoil_calibration.py
    python regenerate_recoil_calibration.py --dry-run
    python regenerate_recoil_calibration.py --output recoil_calibration.json

Reproduces the methodology in ``recoil_regression_12_dual_model.ipynb`` (see also
``recoil_regression_12`` sections 0-3 for load/degenerate filtering):

- degenerate-fit flagging (damped_sine tau_s > 90, single_lobe_damped h_m > 40)
- hand-maintained low-quality-core exclusion (``LOW_QUALITY_CORE_IDS``)
- physics E_gpa ~ depth_m (linear for all rope types)
- single_lobe_damped: h_m ~ WL, t_p_s ~ depth_m, alpha as per-rope mean
- empirical curves via three-tier fallback (rope linear, rope median, all-rope median)

Only reads ``recoil_analysis_results``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import text
from sqlalchemy.engine import Engine

import db_util

ROPE_TYPES = ["steel", "hmpe"]
EMPIRICAL_CURVE_TYPES = ["exponential", "critically_damped", "gamma_pulse", "damped_sine"]
ALL_CURVE_TYPES = ["physics", "single_lobe_damped"] + EMPIRICAL_CURVE_TYPES

LOW_QUALITY_CORE_IDS = {228}

DEGENERATE_DAMPED_SINE_TAU_S = 90.0
DEGENERATE_SLD_H_M = 40.0

PHYSICS_USE_LOG = {"steel": False, "hmpe": False}

C_DRAG = {"steel": 0.01, "hmpe": 0.003}

MIN_ROWS_FOR_LINEAR_FIT = 3
MIN_DISTINCT_PREDICTOR_VALUES = 2


@dataclass
class FitAudit:
    curve_type: str
    rope_type: str
    parameter: str
    mode: str
    value_summary: str
    source: str


AUDIT: list[FitAudit] = []


def load_recoil_analysis_results(engine: Engine) -> pd.DataFrame:
    with engine.connect() as conn:
        df_raw = pd.read_sql(text("SELECT * FROM recoil_analysis_results"), conn)

    if df_raw.empty:
        raise RuntimeError("recoil_analysis_results is empty -- nothing to regress.")

    dp = pd.json_normalize(df_raw["deployment_params"])
    dp.index = df_raw.index
    dp = dp.drop(columns=[c for c in dp.columns if c in df_raw.columns])
    df = pd.concat([df_raw, dp], axis=1)
    assert df.columns.is_unique, "Duplicate columns after flattening deployment_params"

    df["WL"] = df["corer_lbs"] * df["depth_m"]
    df["low_quality"] = df["core_id"].isin(LOW_QUALITY_CORE_IDS)
    return df


def flag_degenerate(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["is_degenerate"] = (
        ((df["curve_type"] == "damped_sine") & (df["tau_s"] > DEGENERATE_DAMPED_SINE_TAU_S))
        | ((df["curve_type"] == "single_lobe_damped") & (df["h_m"] > DEGENERATE_SLD_H_M))
    )
    return df


def _linear_rule(
    rows: pd.DataFrame,
    value_col: str,
    predictor_col: str,
    predictor_label: str,
) -> Optional[dict]:
    sub = rows.dropna(subset=[value_col, predictor_col])
    if len(sub) < MIN_ROWS_FOR_LINEAR_FIT:
        return None
    if predictor_label == "log_depth_m":
        x = np.log(sub[predictor_col])
    else:
        x = sub[predictor_col]
    fit = stats.linregress(x, sub[value_col])
    return {
        "mode": "linear",
        "slope": float(fit.slope),
        "intercept": float(fit.intercept),
        "predictor": predictor_label,
        "r2": float(fit.rvalue ** 2),
        "n": int(len(sub)),
    }


def _three_tier_rule(
    dfw: pd.DataFrame,
    curve_type: str,
    rope_type: str,
    value_col: str,
    predictor_col: str,
) -> dict:
    base = dfw[(dfw["curve_type"] == curve_type) & (~dfw["low_quality"])].dropna(subset=[value_col])
    rope_rows = base[base["rope_type"] == rope_type]

    if (
        predictor_col in rope_rows.columns
        and len(rope_rows.dropna(subset=[predictor_col, value_col])) >= MIN_ROWS_FOR_LINEAR_FIT
        and rope_rows[predictor_col].nunique() >= MIN_DISTINCT_PREDICTOR_VALUES
    ):
        fit_rows = rope_rows.dropna(subset=[predictor_col, value_col])
        fit = stats.linregress(fit_rows[predictor_col], fit_rows[value_col])
        rule = {
            "mode": "linear",
            "slope": float(fit.slope),
            "intercept": float(fit.intercept),
            "predictor": predictor_col,
            "r2": float(fit.rvalue ** 2),
            "n": int(len(fit_rows)),
        }
        source = f"{value_col}~{predictor_col}, {rope_type}, n={len(fit_rows)}, R2={fit.rvalue**2:.2f}"
        AUDIT.append(
            FitAudit(curve_type, rope_type, value_col, "linear", f"slope={fit.slope:.4g}", source)
        )
        return rule

    if len(rope_rows):
        value = float(rope_rows[value_col].median())
        source = f"{rope_type} median, n={len(rope_rows)}"
        AUDIT.append(
            FitAudit(curve_type, rope_type, value_col, "median", f"value={value:.4g}", source)
        )
        return {"mode": "median", "value": value, "n": int(len(rope_rows)), "source": source}

    if len(base):
        value = float(base[value_col].median())
        source = f"all-rope median, n={len(base)}"
        AUDIT.append(
            FitAudit(curve_type, rope_type, value_col, "median", f"value={value:.4g}", source)
        )
        return {"mode": "median", "value": value, "n": int(len(base)), "source": source}

    raise ValueError(f"No saved {curve_type} values for {value_col} ({rope_type}).")


def build_physics(dfw: pd.DataFrame) -> dict:
    out = {}
    phys_data = dfw[(dfw["curve_type"] == "physics") & (~dfw["low_quality"])].dropna(subset=["e_gpa"])
    for rope in ROPE_TYPES:
        use_log = PHYSICS_USE_LOG[rope]
        s = phys_data[phys_data["rope_type"] == rope]
        predictor_label = "log_depth_m" if use_log else "depth_m"
        rule = _linear_rule(s, "e_gpa", "depth_m", predictor_label)
        if rule is None:
            print(
                f"WARNING: insufficient physics E_gpa data for rope_type={rope} (n={len(s)}).",
                file=sys.stderr,
            )
            continue
        out[rope] = {
            "slope": rule["slope"],
            "intercept": rule["intercept"],
            "r2": rule["r2"],
            "n": rule["n"],
            "use_log": use_log,
            "predictor": predictor_label,
        }
        AUDIT.append(
            FitAudit(
                "physics", rope, "E_gpa", "linear", f"slope={rule['slope']:.4g}",
                f"E_gpa~{predictor_label}, {rope}, n={rule['n']}, R2={rule['r2']:.2f}",
            )
        )
    return out


def build_sld(dfw: pd.DataFrame) -> dict:
    out = {}
    sld_all = dfw[(dfw["curve_type"] == "single_lobe_damped") & (~dfw["low_quality"])]
    alpha_means = sld_all.dropna(subset=["alpha"]).groupby("rope_type")["alpha"].mean()

    for rope in ROPE_TYPES:
        s = sld_all[sld_all["rope_type"] == rope]
        h_rule = _linear_rule(s, "h_m", "WL", "WL")
        tp_rule = _linear_rule(s, "t_p_s", "depth_m", "depth_m")
        if h_rule is None or tp_rule is None:
            print(
                f"WARNING: insufficient single_lobe_damped data for rope_type={rope} (n={len(s)}).",
                file=sys.stderr,
            )
            continue
        alpha_mean = float(alpha_means.get(rope, 0.25))
        out[rope] = {
            "n": int(len(s)),
            "alpha_mean": alpha_mean,
            "h_m": h_rule,
            "t_p_s": tp_rule,
        }
        alpha_n = len(sld_all[sld_all["rope_type"] == rope].dropna(subset=["alpha"]))
        AUDIT.append(
            FitAudit(
                "single_lobe_damped", rope, "alpha", "mean", f"value={alpha_mean:.4g}",
                f"flat mean over n={alpha_n}",
            )
        )
    return out


def build_empirical(dfw: pd.DataFrame) -> dict:
    out = {}
    for curve_type in EMPIRICAL_CURVE_TYPES:
        out[curve_type] = {}
        for rope in ROPE_TYPES:
            params = {
                "A_m": _three_tier_rule(dfw, curve_type, rope, "a_m", "WL"),
                "tau_s": _three_tier_rule(dfw, curve_type, rope, "tau_s", "depth_m"),
            }
            if curve_type == "damped_sine":
                params["omega_rads"] = _three_tier_rule(
                    dfw, curve_type, rope, "omega_rads", "depth_m"
                )
            out[curve_type][rope] = params
    return out


def build_training_ranges(dfw: pd.DataFrame) -> dict:
    clean = dfw[~dfw["low_quality"]]
    out = {}
    for rope in ROPE_TYPES:
        s = clean[clean["rope_type"] == rope].dropna(subset=["depth_m", "corer_lbs"])
        if s.empty:
            continue
        out[rope] = {
            "n_rows": int(len(s)),
            "depth_min_m": float(s["depth_m"].min()),
            "depth_max_m": float(s["depth_m"].max()),
            "corer_lbs_min": float(s["corer_lbs"].min()),
            "corer_lbs_max": float(s["corer_lbs"].max()),
            "wl_min": float(s["WL"].min()),
            "wl_max": float(s["WL"].max()),
        }
    return out


def build_cores_by_curve_type(dfw: pd.DataFrame) -> dict:
    clean = dfw[~dfw["low_quality"]]
    out = {}
    for curve_type in ALL_CURVE_TYPES:
        sub = clean[clean["curve_type"] == curve_type]
        entry = {"total": int(sub["core_id"].nunique())}
        for rope in ROPE_TYPES:
            rope_sub = sub[sub["rope_type"] == rope]
            entry[rope] = int(rope_sub["core_id"].nunique())
        out[curve_type] = entry
    return out


def build_calibration(df: pd.DataFrame) -> dict:
    df = flag_degenerate(df)
    dfw = df[~df["is_degenerate"]].copy()

    AUDIT.clear()

    calibration = {
        "row_count_raw": int(len(df)),
        "row_count_working": int(len(dfw)),
        "low_quality_cores": sorted(LOW_QUALITY_CORE_IDS),
        "c_drag": dict(C_DRAG),
        "training_ranges": build_training_ranges(dfw),
        "sld": build_sld(dfw),
        "physics": build_physics(dfw),
        "empirical": build_empirical(dfw),
    }

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "regenerate_recoil_calibration.py",
        "source_table": "recoil_analysis_results",
        "source_row_count_raw": int(len(df)),
        "source_row_count_working": int(len(dfw)),
        "degenerate_row_count": int(df["is_degenerate"].sum()),
        "degenerate_thresholds": {
            "damped_sine_tau_s_gt": DEGENERATE_DAMPED_SINE_TAU_S,
            "single_lobe_damped_h_m_gt": DEGENERATE_SLD_H_M,
        },
        "low_quality_core_ids": sorted(LOW_QUALITY_CORE_IDS),
        "physics_use_log": dict(PHYSICS_USE_LOG),
        "cores_by_curve_type": build_cores_by_curve_type(dfw),
    }

    return {"calibration": calibration, "metadata": metadata}


def print_audit_summary(result: dict) -> None:
    meta = result["metadata"]
    print("\n" + "=" * 70)
    print("CALIBRATION REGENERATION SUMMARY")
    print("=" * 70)
    print(f"Generated at:        {meta['generated_at']}")
    print(f"Raw rows:            {meta['source_row_count_raw']}")
    print(f"Degenerate removed:  {meta['degenerate_row_count']}")
    print(f"Working rows:        {meta['source_row_count_working']}")
    print(f"Low-quality cores:   {meta['low_quality_core_ids']}")
    print()
    print("Cores by curve type (unique core_id):")
    for curve_type, counts in meta.get("cores_by_curve_type", {}).items():
        print(f"  {curve_type:<22} total={counts.get('total', 0):>3}  "
              f"steel={counts.get('steel', 0):>3}  hmpe={counts.get('hmpe', 0):>3}")
    print()
    print(f"{'curve_type':<20}{'rope':<8}{'param':<10}{'mode':<8}{'value':<16}{'source'}")
    print("-" * 100)
    for row in AUDIT:
        print(
            f"{row.curve_type:<20}{row.rope_type:<8}{row.parameter:<10}{row.mode:<8}"
            f"{row.value_summary:<16}{row.source}"
        )
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path(__file__).parent / "recoil_calibration.json",
        help="Where to write the calibration JSON (default: ./recoil_calibration.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the audit summary but do not write the output file.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the per-parameter audit summary printed to stdout.",
    )
    args = parser.parse_args()

    df = load_recoil_analysis_results(db_util.engine)
    result = build_calibration(df)

    if not args.quiet:
        print_audit_summary(result)

    if args.dry_run:
        print("\nDry run — no file written.")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"\nWrote calibration artifact to {args.output}")


if __name__ == "__main__":
    main()
