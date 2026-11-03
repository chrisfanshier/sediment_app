"""QC flag recipes inspired by itraxBook (thresholds are lab/matrix-specific)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def default_qc_params() -> dict[str, Any]:
    """Book-inspired defaults — editable in the GUI."""
    return {
        "require_validity": True,
        "cps_mode": "band",  # "band" | "sd" | "off"
        "cps_min": 30000.0,
        "cps_max": 60000.0,
        "cps_sd": 3.0,
        "mse_max": 2.0,
        "use_mse": True,
        "slope_max_abs": 0.1,  # mm per step (sample surface lag)
        "use_slope": True,
        "ar_mode": "mean_plus_sd",  # "mean_plus_sd" | "off"
        "ar_sd": 2.0,
    }


def apply_qc_flags(df: pd.DataFrame, params: dict[str, Any] | None = None) -> pd.DataFrame:
    """Add boolean QC columns and a combined ``qc`` flag.

    Does not drop rows — filter with ``df[df['qc']]`` for analysis, as the book
    recommends keeping provenance of rejected intervals.
    """
    p = default_qc_params()
    if params:
        p.update(params)

    out = df.copy()
    n = len(out)
    true = pd.Series(True, index=out.index)

    # Validity
    if p["require_validity"] and "validity" in out.columns:
        out["qc_validity"] = out["validity"].astype(bool)
    else:
        out["qc_validity"] = true

    # cps
    if p["cps_mode"] != "off" and "cps" in out.columns:
        cps = pd.to_numeric(out["cps"], errors="coerce")
        if p["cps_mode"] == "band":
            out["qc_cps"] = (cps >= float(p["cps_min"])) & (cps <= float(p["cps_max"]))
        else:
            mu, sd = cps.mean(), cps.std()
            k = float(p["cps_sd"])
            out["qc_cps"] = (cps >= mu - k * sd) & (cps <= mu + k * sd)
    else:
        out["qc_cps"] = true

    # MSE
    if p["use_mse"] and "MSE" in out.columns:
        mse = pd.to_numeric(out["MSE"], errors="coerce")
        out["qc_mse"] = mse <= float(p["mse_max"])
    else:
        out["qc_mse"] = true

    # Surface slope from lag(sample surface)
    if p["use_slope"] and "sample surface" in out.columns:
        surf = pd.to_numeric(out["sample surface"], errors="coerce")
        slope = surf.diff()
        # First row has no lag — treat as pass
        ok = slope.abs() <= float(p["slope_max_abs"])
        ok.iloc[0] = True
        out["qc_slope"] = ok.fillna(False)
        out["surface_slope"] = slope
    else:
        out["qc_slope"] = true

    # Argon (air path / voids)
    if p["ar_mode"] != "off" and "Ar" in out.columns:
        ar = pd.to_numeric(out["Ar"], errors="coerce")
        thr = ar.mean() + float(p["ar_sd"]) * ar.std()
        out["qc_ar"] = ar <= thr
        out["ar_threshold"] = thr
    else:
        out["qc_ar"] = true

    out["qc"] = (
        out["qc_validity"] & out["qc_cps"] & out["qc_mse"] & out["qc_slope"] & out["qc_ar"]
    )
    out["qc"] = out["qc"].fillna(False)
    return out


def qc_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Small summary table of pass rates for sidebar display."""
    cols = [c for c in ["qc_validity", "qc_cps", "qc_mse", "qc_slope", "qc_ar", "qc"] if c in df.columns]
    rows = []
    n = len(df)
    for c in cols:
        passed = int(df[c].fillna(False).sum())
        rows.append(
            {
                "flag": c,
                "pass": passed,
                "fail": n - passed,
                "pass_pct": round(100.0 * passed / n, 1) if n else 0.0,
            }
        )
    return pd.DataFrame(rows)
