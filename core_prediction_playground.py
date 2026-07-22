"""
Simple core-prediction playground.

Run from this folder with:

    python -m streamlit run core_prediction_playground.py

This is intentionally a first-pass GUI: it bakes in the current recoil
regression results from ``recoil_regression_12_dual_model.ipynb`` so the
model can be explored without rebuilding regressions or touching the DB.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st


FT_TO_M = 1.0 / 3.28
WEIGHT_STAND_LENGTH_M = 1.5
PISTON_OFFSET_M = 1.25

CURVE_TYPES = [
    "physics",
    "exponential",
    "critically_damped",
    "gamma_pulse",
    "damped_sine",
    "single_lobe_damped",
]

CURVE_LABELS = {
    "physics": "Physics recoil (regressed E)",
    "exponential": "Exponential recoil",
    "critically_damped": "Critically damped recoil",
    "gamma_pulse": "Gamma-pulse recoil",
    "damped_sine": "Damped-sine recoil",
    "single_lobe_damped": "Single-lobe recoil",
}


# Baked from the current recoil_analysis_results snapshot used by
# recoil_regression_12_dual_model.ipynb on 2026-07-07.
CALIBRATION = {
    "row_count_raw": 114,
    "row_count_working": 106,
    "low_quality_cores": [228],
    "c_drag": {"steel": 0.01, "hmpe": 0.003},
    "training_ranges": {
        "steel": {
            "n_rows": 73,
            "depth_min_m": 38.1,
            "depth_max_m": 3646.8,
            "corer_lbs_min": 4200.0,
            "corer_lbs_max": 7000.0,
            "wl_min": 160020.0,
            "wl_max": 17069000.0,
        },
        "hmpe": {
            "n_rows": 31,
            "depth_min_m": 470.0,
            "depth_max_m": 2566.1,
            "corer_lbs_min": 6600.0,
            "corer_lbs_max": 6600.0,
            "wl_min": 3102000.0,
            "wl_max": 16936260.0,
        },
    },
    "sld": {
        "steel": {
            "n": 22,
            "alpha_mean": 1.0324555981543517,
            "h_m": {
                "mode": "linear",
                "slope": 7.733949600023103e-07,
                "intercept": 3.209601870713811,
                "predictor": "WL",
                "r2": 0.8511246967238426,
                "n": 22,
            },
            "t_p_s": {
                "mode": "linear",
                "slope": 0.0004709839609167194,
                "intercept": 1.4199339526218233,
                "predictor": "depth_m",
                "r2": 0.6653680162294867,
                "n": 22,
            },
        },
        "hmpe": {
            "n": 6,
            "alpha_mean": 0.6358345036134644,
            "h_m": {
                "mode": "linear",
                "slope": 1.5405400253075836e-06,
                "intercept": 1.634585431889775,
                "predictor": "WL",
                "r2": 0.5900503261209528,
                "n": 6,
            },
            "t_p_s": {
                "mode": "linear",
                "slope": 0.0013217565451143951,
                "intercept": 1.2325187650111027,
                "predictor": "depth_m",
                "r2": 0.3664703451937395,
                "n": 6,
            },
        },
    },
    "physics": {
        "steel": {
            "slope": 0.058094056245240444,
            "intercept": 22.372265416366737,
            "r2": 0.8806456974616738,
            "n": 22,
            "use_log": False,
            "predictor": "depth_m",
        },
        "hmpe": {
            "slope": 15.015433600352358,
            "intercept": -57.82403276840371,
            "r2": 0.6950414314593719,
            "n": 6,
            "use_log": True,
            "predictor": "log_depth_m",
        },
    },
    "empirical": {
        "exponential": {
            "steel": {
                "A_m": {
                    "mode": "linear",
                    "slope": 2.254818482137023e-07,
                    "intercept": 0.9279846809249638,
                    "r2": 0.3920636696469712,
                    "n": 7,
                    "predictor": "WL",
                },
                "tau_s": {
                    "mode": "linear",
                    "slope": -0.00021946989043184937,
                    "intercept": 0.31473542605907723,
                    "r2": 0.05403097959176627,
                    "n": 7,
                    "predictor": "depth_m",
                },
            },
            "hmpe": {
                "A_m": {
                    "mode": "linear",
                    "slope": 3.851927423433202e-07,
                    "intercept": 1.9674588640992194,
                    "r2": 0.7398514792155917,
                    "n": 6,
                    "predictor": "WL",
                },
                "tau_s": {
                    "mode": "linear",
                    "slope": 0.00015812506886104947,
                    "intercept": 0.09160297364915088,
                    "r2": 0.4117306934952785,
                    "n": 6,
                    "predictor": "depth_m",
                },
            },
        },
        "critically_damped": {
            "steel": {
                "A_m": {
                    "mode": "linear",
                    "slope": 2.3542730016524976e-07,
                    "intercept": 0.8680250906437642,
                    "r2": 0.49800048307351963,
                    "n": 7,
                    "predictor": "WL",
                },
                "tau_s": {
                    "mode": "linear",
                    "slope": -3.492384608745299e-05,
                    "intercept": 0.12227801616743861,
                    "r2": 0.016797242171710136,
                    "n": 7,
                    "predictor": "depth_m",
                },
            },
            "hmpe": {
                "A_m": {
                    "mode": "linear",
                    "slope": 3.7614922554226275e-07,
                    "intercept": 1.8473297921407976,
                    "r2": 0.8398530846493285,
                    "n": 6,
                    "predictor": "WL",
                },
                "tau_s": {
                    "mode": "linear",
                    "slope": 5.722828539217034e-05,
                    "intercept": 0.052631953733197887,
                    "r2": 0.4166004547255224,
                    "n": 6,
                    "predictor": "depth_m",
                },
            },
        },
        "gamma_pulse": {
            "steel": {
                "A_m": {
                    "mode": "median",
                    "value": 2.6977117239696855,
                    "n": 1,
                    "source": "all-rope median",
                },
                "tau_s": {
                    "mode": "median",
                    "value": 0.536793982682471,
                    "n": 1,
                    "source": "all-rope median",
                },
            },
            "hmpe": {
                "A_m": {
                    "mode": "median",
                    "value": 2.6977117239696855,
                    "n": 1,
                    "source": "hmpe median",
                },
                "tau_s": {
                    "mode": "median",
                    "value": 0.536793982682471,
                    "n": 1,
                    "source": "hmpe median",
                },
            },
        },
        "damped_sine": {
            "steel": {
                "A_m": {
                    "mode": "linear",
                    "slope": 3.3449785199787355e-07,
                    "intercept": 1.325151731714785,
                    "r2": 0.7072981204368521,
                    "n": 15,
                    "predictor": "WL",
                },
                "tau_s": {
                    "mode": "linear",
                    "slope": 0.0020009314652582443,
                    "intercept": 2.160138929415135,
                    "r2": 0.1642867406801432,
                    "n": 15,
                    "predictor": "depth_m",
                },
                "omega_rads": {
                    "mode": "linear",
                    "slope": -0.0007485890154230566,
                    "intercept": 2.2698198177489166,
                    "r2": 0.5354150691999154,
                    "n": 15,
                    "predictor": "depth_m",
                },
            },
            "hmpe": {
                "A_m": {
                    "mode": "linear",
                    "slope": -1.328289799828189e-06,
                    "intercept": 55.10201043733735,
                    "r2": 0.14354557200216367,
                    "n": 6,
                    "predictor": "WL",
                },
                "tau_s": {
                    "mode": "linear",
                    "slope": 0.0013167422595395377,
                    "intercept": -0.6036932796967505,
                    "r2": 0.46841100136145325,
                    "n": 6,
                    "predictor": "depth_m",
                },
                "omega_rads": {
                    "mode": "linear",
                    "slope": 0.00012365797274493096,
                    "intercept": 0.22785746249721395,
                    "r2": 0.1240037867821682,
                    "n": 6,
                    "predictor": "depth_m",
                },
            },
        },
    },
}


@dataclass
class Inputs:
    depth_m: float
    corer_lbs: float
    rope_type: str
    rope_diameter_mm: float
    instrument_lbs: float
    v0_mean_ms: float
    v0_std_ms: float
    v0_min_ms: float
    v0_max_ms: float
    v0_scenarios: int
    random_seed: int
    time_before_s: float
    time_after_s: float
    dt_s: float
    release_above_corer_m: float
    displaced_volume_m3: float
    added_mass_coefficient: float
    barrel_length_m: float
    barrel_diameter_in: float
    lead_flow_diameter_in: float
    lead_drag_coefficient: float
    scope_ft: float
    main_core_length_ft: float
    trigger_line_length_ft: float
    trigger_core_length_ft: float
    trigger_core_penetration_ft: float


def _rule_value(rule: dict, *, depth_m: float, corer_lbs: float) -> tuple[float, str]:
    if rule["mode"] == "linear":
        predictor = rule["predictor"]
        if predictor == "WL":
            x = corer_lbs * depth_m
        elif predictor == "depth_m":
            x = depth_m
        elif predictor == "log_depth_m":
            x = math.log(depth_m)
        else:
            raise ValueError(f"Unknown predictor: {predictor}")
        value = rule["slope"] * x + rule["intercept"]
        source = f"{predictor}, n={rule.get('n')}, R²={rule.get('r2', float('nan')):.2f}"
        return float(value), source
    return float(rule["value"]), f"{rule.get('source', rule['mode'])}, n={rule.get('n')}"


def _safe_positive(value: float, floor: float = 0.01) -> float:
    if not np.isfinite(value):
        return floor
    return max(float(value), floor)


def predict_recoil_parameters(inputs: Inputs) -> tuple[dict, pd.DataFrame]:
    depth_m = inputs.depth_m
    corer_lbs = inputs.corer_lbs
    rope = inputs.rope_type

    params: dict[str, dict] = {}
    audit_rows = []

    phys = CALIBRATION["physics"][rope]
    x = math.log(depth_m) if phys["use_log"] else depth_m
    e_gpa = _safe_positive(phys["slope"] * x + phys["intercept"], 1.0)
    c_drag = float(CALIBRATION["c_drag"][rope])
    params["physics"] = {"E_gpa": e_gpa, "C_drag": c_drag}
    audit_rows.extend(
        [
            {
                "curve_type": "physics",
                "parameter": "E_gpa",
                "value": e_gpa,
                "source": f"{phys['predictor']}, n={phys['n']}, R²={phys['r2']:.2f}",
            },
            {
                "curve_type": "physics",
                "parameter": "C_drag",
                "value": c_drag,
                "source": "baked rope default",
            },
        ]
    )

    sld = CALIBRATION["sld"][rope]
    h_m, h_src = _rule_value(sld["h_m"], depth_m=depth_m, corer_lbs=corer_lbs)
    t_p_s, tp_src = _rule_value(sld["t_p_s"], depth_m=depth_m, corer_lbs=corer_lbs)
    alpha = _safe_positive(sld["alpha_mean"], 0.01)
    params["single_lobe_damped"] = {
        "H_m": _safe_positive(h_m),
        "t_p_s": _safe_positive(t_p_s),
        "alpha": alpha,
    }
    audit_rows.extend(
        [
            {"curve_type": "single_lobe_damped", "parameter": "H_m", "value": params["single_lobe_damped"]["H_m"], "source": h_src},
            {"curve_type": "single_lobe_damped", "parameter": "t_p_s", "value": params["single_lobe_damped"]["t_p_s"], "source": tp_src},
            {"curve_type": "single_lobe_damped", "parameter": "alpha", "value": alpha, "source": f"mean alpha, n={sld['n']}"},
        ]
    )

    for curve in ["exponential", "critically_damped", "gamma_pulse", "damped_sine"]:
        curve_rules = CALIBRATION["empirical"][curve][rope]
        a_m, a_src = _rule_value(curve_rules["A_m"], depth_m=depth_m, corer_lbs=corer_lbs)
        tau_s, tau_src = _rule_value(curve_rules["tau_s"], depth_m=depth_m, corer_lbs=corer_lbs)
        params[curve] = {"A_m": _safe_positive(a_m), "tau_s": _safe_positive(tau_s)}
        audit_rows.extend(
            [
                {"curve_type": curve, "parameter": "A_m", "value": params[curve]["A_m"], "source": a_src},
                {"curve_type": curve, "parameter": "tau_s", "value": params[curve]["tau_s"], "source": tau_src},
            ]
        )
        if curve == "damped_sine":
            omega, omega_src = _rule_value(curve_rules["omega_rads"], depth_m=depth_m, corer_lbs=corer_lbs)
            params[curve]["omega_rads"] = _safe_positive(omega)
            audit_rows.append(
                {"curve_type": curve, "parameter": "omega_rads", "value": params[curve]["omega_rads"], "source": omega_src}
            )

    return params, pd.DataFrame(audit_rows)


def make_v0_scenarios(inputs: Inputs) -> np.ndarray:
    rng = np.random.default_rng(int(inputs.random_seed))
    values = np.clip(
        rng.normal(inputs.v0_mean_ms, inputs.v0_std_ms, int(inputs.v0_scenarios)),
        inputs.v0_min_ms,
        inputs.v0_max_ms,
    )
    if len(values):
        values[0] = inputs.v0_mean_ms
    return values


def corer_acceleration_factory(inputs: Inputs):
    rho_w = 1025.0
    g = 9.81
    mu = 1.065e-3
    mass_kg = inputs.corer_lbs * 0.453592
    barrel_dia_m = inputs.barrel_diameter_in * 0.0254
    lead_dia_m = inputs.lead_flow_diameter_in * 0.0254
    lead_area = math.pi * ((lead_dia_m / 2.0) ** 2 - (barrel_dia_m / 2.0) ** 2)
    barrel_wet_area = math.pi * barrel_dia_m * inputs.barrel_length_m
    added_mass = inputs.added_mass_coefficient * rho_w * inputs.displaced_volume_m3
    effective_mass = mass_kg + added_mass
    drive_force = mass_kg * g - rho_w * inputs.displaced_volume_m3 * g

    def barrel_cd(speed: float) -> float:
        speed = abs(float(speed))
        if speed < 0.001:
            return 0.003
        reynolds = rho_w * speed * inputs.barrel_length_m / mu
        return 0.455 / (math.log10(reynolds) ** 2.58) if reynolds > 1e5 else 0.003

    def accel(v: float) -> float:
        speed = abs(float(v))
        lead_drag = 0.5 * rho_w * inputs.lead_drag_coefficient * lead_area * v * speed
        skin_drag = 0.5 * rho_w * barrel_cd(speed) * barrel_wet_area * v * speed
        return (drive_force - lead_drag - skin_drag) / effective_mass

    return accel


def integrate_freefall(inputs: Inputs, post_time: np.ndarray, v0: float) -> np.ndarray:
    accel = corer_acceleration_factory(inputs)
    dt = min(0.002, max(inputs.dt_s / 5.0, 0.0005))
    sim_t = np.arange(0.0, inputs.time_after_s + dt, dt)
    z = np.zeros_like(sim_t)
    v = np.zeros_like(sim_t)
    v[0] = v0
    for i in range(1, len(sim_t)):
        z0, v0i = z[i - 1], v[i - 1]

        def deriv(vi: float) -> tuple[float, float]:
            return vi, accel(vi)

        k1z, k1v = deriv(v0i)
        k2z, k2v = deriv(v0i + 0.5 * dt * k1v)
        k3z, k3v = deriv(v0i + 0.5 * dt * k2v)
        k4z, k4v = deriv(v0i + dt * k3v)
        z[i] = z0 + dt * (k1z + 2 * k2z + 2 * k3z + k4z) / 6.0
        v[i] = v0i + dt * (k1v + 2 * k2v + 2 * k3v + k4v) / 6.0
    return np.interp(post_time, sim_t, z)


def physics_recoil(inputs: Inputs, params: dict, post_time: np.ndarray, v0: float) -> np.ndarray:
    p = params["physics"]
    rho_w = 1025.0
    dia_m = inputs.rope_diameter_mm / 1000.0
    a_cs = math.pi * (dia_m / 2.0) ** 2
    a_wet = math.pi * dia_m * inputs.depth_m
    k = (p["E_gpa"] * 1e9 * a_cs) / inputs.depth_m
    rho_rope = 970.0 if inputs.rope_type == "hmpe" else 7850.0
    m_eff = 0.5 * a_cs * rho_rope * inputs.depth_m + rho_w * a_cs * inputs.depth_m
    f_drive = inputs.corer_lbs * 0.4536 * 9.81 * (1 - rho_w / 7850.0)
    dt = inputs.dt_s
    sim_t = np.arange(0.0, inputs.time_after_s + dt, dt)
    x = 0.0
    v = -float(v0)
    out = np.zeros_like(sim_t)

    def accel(xi: float, vi: float) -> float:
        return (f_drive - k * xi - 0.5 * rho_w * p["C_drag"] * a_wet * vi * abs(vi)) / m_eff

    for i in range(len(sim_t)):
        out[i] = x
        a1 = accel(x, v)
        a2 = accel(x + 0.5 * dt * v, v + 0.5 * dt * a1)
        a3 = accel(x + 0.5 * dt * (v + 0.5 * dt * a1), v + 0.5 * dt * a2)
        a4 = accel(x + dt * (v + dt * a2), v + dt * a3)
        v += dt * (a1 + 2 * a2 + 2 * a3 + a4) / 6.0
        x += dt * v
    return np.interp(post_time, sim_t, out)


def empirical_recoil(curve: str, params: dict, post_time: np.ndarray) -> np.ndarray:
    t = post_time
    p = params[curve]
    if curve == "single_lobe_damped":
        u = t / p["t_p_s"]
        return np.where(
            (u >= 0.0) & (u <= 1.0),
            p["H_m"] * np.power(np.clip(u, 1e-10, None), p["alpha"]) * (1.0 - u),
            0.0,
        )
    a = p["A_m"]
    tau = p["tau_s"]
    if curve == "exponential":
        return a * (1.0 - np.exp(-t / tau))
    if curve == "critically_damped":
        return a * (1.0 - (1.0 + t / tau) * np.exp(-t / tau))
    if curve == "gamma_pulse":
        return a * (t / tau) * np.exp(1.0 - t / tau)
    if curve == "damped_sine":
        return a * np.exp(-t / tau) * np.sin(p["omega_rads"] * t)
    raise ValueError(curve)


def compute_piston_position(weight_stand_m, release_m, scope_ft, core_length_ft, start_core_idx):
    scope_m = scope_ft * FT_TO_M
    barrel_m = core_length_ft * FT_TO_M
    ws = np.asarray(weight_stand_m, dtype=float)
    rel = np.asarray(release_m, dtype=float)
    piston = np.empty_like(ws)
    piston[:start_core_idx] = ws[:start_core_idx] + PISTON_OFFSET_M + barrel_m
    piston[start_core_idx:] = rel[start_core_idx:] + scope_m + barrel_m + PISTON_OFFSET_M
    return piston


def detect_start_core(weight_stand_m, release_m, scope_ft, trip_idx):
    ws = np.asarray(weight_stand_m, dtype=float)
    rel = np.asarray(release_m, dtype=float)
    threshold = scope_ft * FT_TO_M
    diff = np.abs(rel[trip_idx:] - ws[trip_idx:])
    crossings = np.flatnonzero(diff > threshold)
    if len(crossings):
        return int(trip_idx + crossings[0])
    return len(ws) - 1


def bands(matrix: np.ndarray) -> dict[int, np.ndarray]:
    return {q: np.percentile(matrix, q, axis=0) for q in (10, 50, 90)}


@st.cache_data(show_spinner=False)
def run_prediction(inputs_dict: dict):
    inputs = Inputs(**inputs_dict)
    params, parameter_table = predict_recoil_parameters(inputs)

    time = np.arange(-inputs.time_before_s, inputs.time_after_s + inputs.dt_s / 2.0, inputs.dt_s)
    pre_mask = time < 0.0
    post_mask = ~pre_mask
    post_time = time[post_mask]
    trip_idx = int(np.argmin(np.abs(time)))
    v0_values = make_v0_scenarios(inputs)

    corer_paths = []
    release_paths = {curve: [] for curve in CURVE_TYPES}
    empirical_post = {
        curve: empirical_recoil(curve, params, post_time)
        for curve in CURVE_TYPES
        if curve != "physics"
    }

    for v0 in v0_values:
        corer = np.empty_like(time)
        corer[pre_mask] = v0 * time[pre_mask]
        corer[post_mask] = integrate_freefall(inputs, post_time, v0)
        corer_paths.append(corer)

        for curve in CURVE_TYPES:
            release = np.empty_like(time)
            release[pre_mask] = v0 * time[pre_mask] - inputs.release_above_corer_m
            recoil = physics_recoil(inputs, params, post_time, v0) if curve == "physics" else empirical_post[curve]
            release[post_mask] = -inputs.release_above_corer_m - recoil
            release_paths[curve].append(release)

    corer_paths = np.vstack(corer_paths)
    release_paths = {curve: np.vstack(paths) for curve, paths in release_paths.items()}

    release_depth_at_trip = inputs.depth_m
    release_rel_at_trip = -inputs.release_above_corer_m
    corer_depth_at_trip = release_depth_at_trip - release_rel_at_trip
    seafloor_m = (
        release_depth_at_trip
        + inputs.trigger_line_length_ft * FT_TO_M
        + inputs.trigger_core_length_ft * FT_TO_M
        - inputs.trigger_core_penetration_ft * FT_TO_M
    )
    seafloor_relative_m = seafloor_m - corer_depth_at_trip
    main_core_length_m = inputs.main_core_length_ft * FT_TO_M

    piston_paths = {}
    event_rows = []
    for curve in CURVE_TYPES:
        piston_rows = []
        for i in range(len(v0_values)):
            release_rel = release_paths[curve][i]
            corer_rel = corer_paths[i]
            release_abs = release_depth_at_trip + (release_rel - release_rel_at_trip)
            corer_abs = release_depth_at_trip + (corer_rel - release_rel_at_trip)
            start_core_idx = detect_start_core(corer_abs, release_abs, inputs.scope_ft, trip_idx)
            sep_m = abs(float(release_abs[start_core_idx] - corer_abs[start_core_idx]))
            start_core_detected = start_core_idx >= trip_idx and sep_m > inputs.scope_ft * FT_TO_M

            piston_abs = compute_piston_position(
                corer_abs,
                release_abs,
                inputs.scope_ft,
                inputs.main_core_length_ft,
                start_core_idx,
            )
            piston_rows.append(piston_abs - corer_depth_at_trip)

            core_tip_abs = corer_abs + WEIGHT_STAND_LENGTH_M + main_core_length_m
            pen_candidates = np.flatnonzero(core_tip_abs[trip_idx:] >= seafloor_m)
            start_pen_idx = int(trip_idx + pen_candidates[0]) if len(pen_candidates) else None
            start_pen_detected = start_pen_idx is not None

            event_rows.append(
                {
                    "curve_type": curve,
                    "start_core_detected": start_core_detected,
                    "start_core_time_s": float(time[start_core_idx]) if start_core_detected else np.nan,
                    "piston_alt_start_core_m": seafloor_m - float(piston_abs[start_core_idx]) if start_core_detected else np.nan,
                    "start_pen_detected": start_pen_detected,
                    "start_pen_time_s": float(time[start_pen_idx]) if start_pen_detected else np.nan,
                    "piston_alt_start_pen_m": seafloor_m - float(piston_abs[start_pen_idx]) if start_pen_detected else np.nan,
                    "start_pen_before_start_core": bool(start_pen_idx < start_core_idx) if start_pen_detected and start_core_detected else False,
                }
            )
        piston_paths[curve] = np.vstack(piston_rows)

    event_detail = pd.DataFrame(event_rows)
    summary_rows = []
    for curve, detail in event_detail.groupby("curve_type"):
        summary_rows.append(
            {
                "curve_type": curve,
                "start_core_detected_n": int(detail["start_core_detected"].sum()),
                "start_pen_detected_n": int(detail["start_pen_detected"].sum()),
                "start_pen_before_start_core_n": int(detail["start_pen_before_start_core"].sum()),
                "start_core_time_median_s": float(np.nanmedian(detail["start_core_time_s"])),
                "piston_alt_start_core_median_m": float(np.nanmedian(detail["piston_alt_start_core_m"])),
                "start_pen_time_median_s": float(np.nanmedian(detail["start_pen_time_s"])),
                "piston_alt_start_pen_median_m": float(np.nanmedian(detail["piston_alt_start_pen_m"])),
            }
        )

    return {
        "inputs": inputs,
        "time": time,
        "corer_paths": corer_paths,
        "release_paths": release_paths,
        "piston_paths": piston_paths,
        "corer_bands": bands(corer_paths),
        "release_bands": {curve: bands(paths) for curve, paths in release_paths.items()},
        "piston_bands": {curve: bands(paths) for curve, paths in piston_paths.items()},
        "parameter_table": parameter_table,
        "event_summary": pd.DataFrame(summary_rows),
        "seafloor_relative_m": seafloor_relative_m,
        "seafloor_m": seafloor_m,
        "corer_depth_at_trip_m": corer_depth_at_trip,
        "release_depth_at_trip_m": release_depth_at_trip,
        "v0_values": v0_values,
    }


def draw_curve(result: dict, selected_curves: list[str], show_piston: bool):
    time = result["time"]
    corer = result["corer_bands"]
    event_summary = result["event_summary"].set_index("curve_type")
    seafloor_rel = result["seafloor_relative_m"]

    n = len(selected_curves)
    cols = 2 if n > 1 else 1
    rows = int(math.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(10 * cols, 5.8 * rows), sharex=True, squeeze=False)

    y_values = [corer[10].min(), corer[90].max(), seafloor_rel]
    for curve in selected_curves:
        rel = result["release_bands"][curve]
        y_values.extend([rel[10].min(), rel[90].max()])
        if show_piston:
            pist = result["piston_bands"][curve]
            y_values.extend([pist[10].min(), pist[90].max()])
    y_min = float(np.nanmin(y_values)) - 0.5
    y_max = float(np.nanmax(y_values)) + 0.75

    for ax, curve in zip(axes.flat, selected_curves):
        release = result["release_bands"][curve]
        ax.fill_between(time, corer[10], corer[90], color="#e6550d", alpha=0.16, label="Corer 10-90%")
        ax.plot(time, corer[50], color="#e6550d", lw=2.6, label="Corer median")
        ax.fill_between(time, release[10], release[90], color="#3182bd", alpha=0.18, label="Release 10-90%")
        ax.plot(time, release[50], color="#3182bd", lw=2.4, label="Release median")

        if show_piston:
            piston = result["piston_bands"][curve]
            ax.fill_between(time, piston[10], piston[90], color="#756bb1", alpha=0.14, label="Piston 10-90%")
            ax.plot(time, piston[50], color="#756bb1", lw=2.2, label="Piston median")

        ax.axvline(0.0, color="black", ls="--", lw=1.0, label="Trip")
        ax.axhline(seafloor_rel, color="#444444", ls=":", lw=1.5, label="Estimated seafloor")

        if curve in event_summary.index:
            row = event_summary.loc[curve]
            sc_t = row["start_core_time_median_s"]
            sp_t = row["start_pen_time_median_s"]
            if np.isfinite(sc_t):
                ax.axvline(sc_t, color="#2ca02c", ls="-.", lw=1.7, label="Start core")
            if np.isfinite(sp_t):
                ax.axvline(sp_t, color="#984ea3", ls="--", lw=1.7, label="Start pen")

        ax.set_title(CURVE_LABELS[curve])
        ax.set_xlabel("Time relative to trip (s)")
        ax.set_ylabel("Relative depth (m; downward positive)")
        ax.set_ylim(y_max, y_min)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="best")

    for ax in axes.flat[n:]:
        ax.axis("off")

    fig.tight_layout()
    return fig


def training_warnings(inputs: Inputs) -> list[str]:
    warnings = []
    ranges = CALIBRATION["training_ranges"][inputs.rope_type]
    wl = inputs.depth_m * inputs.corer_lbs
    if not ranges["depth_min_m"] <= inputs.depth_m <= ranges["depth_max_m"]:
        warnings.append(
            f"Depth {inputs.depth_m:.0f} m is outside the {inputs.rope_type.upper()} recoil training range "
            f"({ranges['depth_min_m']:.0f}-{ranges['depth_max_m']:.0f} m)."
        )
    if not ranges["wl_min"] <= wl <= ranges["wl_max"]:
        warnings.append(
            f"Weight x depth {wl:,.0f} lb*m is outside the {inputs.rope_type.upper()} training range "
            f"({ranges['wl_min']:,.0f}-{ranges['wl_max']:,.0f} lb*m)."
        )
    return warnings


st.set_page_config(page_title="Core Prediction Playground", layout="wide")
st.title("Core prediction playground")
st.caption(
    "A deliberately simple GUI using the current baked recoil regressions, corer freefall physics, "
    "and piston/seafloor geometry."
)

with st.sidebar:
    st.header("Deployment")
    rope_type = st.selectbox("Rope type", ["hmpe", "steel"], index=0).lower()
    depth_m = st.number_input("Release-device depth at trip (m)", min_value=1.0, max_value=6000.0, value=1500.0, step=50.0)
    corer_lbs = st.number_input("Corer weight (lb)", min_value=100.0, max_value=20000.0, value=6000.0, step=100.0)
    rope_diameter_mm = st.number_input("Rope diameter (mm)", min_value=1.0, max_value=100.0, value=14.3, step=0.1)
    instrument_lbs = st.number_input("Instrument weight (lb, currently informational)", min_value=0.0, max_value=2000.0, value=100.0, step=10.0)

    st.header("Initial velocity")
    v0_mean_ms = st.slider("Mean v0 (m/s, + downward)", -1.5, 2.0, -0.10, 0.01)
    v0_std_ms = st.slider("v0 standard deviation (m/s)", 0.0, 1.5, 0.45, 0.01)
    v0_min_ms = st.number_input("v0 min (m/s)", value=-0.75, step=0.05)
    v0_max_ms = st.number_input("v0 max (m/s)", value=1.50, step=0.05)
    v0_scenarios = st.slider("Uncertainty scenarios", 51, 501, 301, 10)
    random_seed = st.number_input("Random seed", value=20260706, step=1)

    st.header("Geometry")
    release_above_corer_m = st.number_input("Release above corer at trip (m)", min_value=0.0, max_value=10.0, value=0.50, step=0.05)
    scope_ft = st.number_input("Scope (ft)", min_value=0.1, max_value=500.0, value=25.0, step=0.5)
    main_core_length_ft = st.number_input("Main core length (ft)", min_value=1.0, max_value=100.0, value=32.8, step=0.5)
    trigger_line_length_ft = st.number_input("Trigger line length (ft)", min_value=0.1, max_value=500.0, value=30.0, step=0.5)
    trigger_core_length_ft = st.number_input("Trigger core length (ft)", min_value=0.1, max_value=100.0, value=10.0, step=0.5)
    trigger_core_penetration_ft = st.number_input("Trigger core penetration (ft)", min_value=0.0, max_value=100.0, value=0.0, step=0.25)

    with st.expander("Freefall physics details"):
        displaced_volume_m3 = st.number_input("Displaced volume (m³)", min_value=0.001, max_value=10.0, value=0.347, step=0.01)
        added_mass_coefficient = st.number_input("Added mass coefficient", min_value=0.0, max_value=5.0, value=0.0, step=0.05)
        barrel_length_m = st.number_input("Barrel length (m)", min_value=0.1, max_value=50.0, value=10.0, step=0.1)
        barrel_diameter_in = st.number_input("Barrel diameter (in)", min_value=0.1, max_value=50.0, value=5.0, step=0.1)
        lead_flow_diameter_in = st.number_input("Lead flow diameter (in)", min_value=0.1, max_value=100.0, value=24.0, step=0.5)
        lead_drag_coefficient = st.number_input("Lead drag coefficient", min_value=0.0, max_value=5.0, value=1.10, step=0.05)

    st.header("Plot")
    time_before_s = st.number_input("Seconds before trip", min_value=0.0, max_value=10.0, value=1.0, step=0.25)
    time_after_s = st.number_input("Seconds after trip", min_value=0.5, max_value=20.0, value=3.0, step=0.25)
    dt_s = st.select_slider("Output time step (s)", options=[0.005, 0.01, 0.02, 0.05], value=0.01)

inputs = Inputs(
    depth_m=float(depth_m),
    corer_lbs=float(corer_lbs),
    rope_type=rope_type,
    rope_diameter_mm=float(rope_diameter_mm),
    instrument_lbs=float(instrument_lbs),
    v0_mean_ms=float(v0_mean_ms),
    v0_std_ms=float(v0_std_ms),
    v0_min_ms=float(v0_min_ms),
    v0_max_ms=float(v0_max_ms),
    v0_scenarios=int(v0_scenarios),
    random_seed=int(random_seed),
    time_before_s=float(time_before_s),
    time_after_s=float(time_after_s),
    dt_s=float(dt_s),
    release_above_corer_m=float(release_above_corer_m),
    displaced_volume_m3=float(displaced_volume_m3),
    added_mass_coefficient=float(added_mass_coefficient),
    barrel_length_m=float(barrel_length_m),
    barrel_diameter_in=float(barrel_diameter_in),
    lead_flow_diameter_in=float(lead_flow_diameter_in),
    lead_drag_coefficient=float(lead_drag_coefficient),
    scope_ft=float(scope_ft),
    main_core_length_ft=float(main_core_length_ft),
    trigger_line_length_ft=float(trigger_line_length_ft),
    trigger_core_length_ft=float(trigger_core_length_ft),
    trigger_core_penetration_ft=float(trigger_core_penetration_ft),
)

if inputs.v0_min_ms > inputs.v0_max_ms:
    st.error("v0 min must be <= v0 max.")
    st.stop()

for warning in training_warnings(inputs):
    st.warning(warning)

result = run_prediction(inputs.__dict__)

metrics = st.columns(4)
metrics[0].metric("Estimated seafloor", f"{result['seafloor_m']:.2f} m")
metrics[1].metric("Seafloor rel. to corer trip", f"{result['seafloor_relative_m']:+.2f} m")
metrics[2].metric("Release depth at trip", f"{result['release_depth_at_trip_m']:.2f} m")
metrics[3].metric("Corer depth at trip", f"{result['corer_depth_at_trip_m']:.2f} m")

tab_plot, tab_events, tab_params, tab_notes = st.tabs(["Plot", "Events", "Parameters", "Notes"])

with tab_plot:
    left, right = st.columns([1, 2])
    with left:
        plot_mode = st.radio("Curve display", ["Single curve", "All curves"], index=0)
        if plot_mode == "Single curve":
            selected = [
                st.selectbox(
                    "Recoil curve",
                    CURVE_TYPES,
                    format_func=lambda c: CURVE_LABELS[c],
                    index=0,
                )
            ]
        else:
            selected = CURVE_TYPES
        show_piston = st.checkbox("Show piston trajectory", value=True)
    with right:
        st.pyplot(draw_curve(result, selected, show_piston), clear_figure=True)

with tab_events:
    display_cols = [
        "curve_type",
        "start_core_time_median_s",
        "piston_alt_start_core_median_m",
        "start_pen_time_median_s",
        "piston_alt_start_pen_median_m",
        "start_pen_before_start_core_n",
        "start_core_detected_n",
        "start_pen_detected_n",
    ]
    st.dataframe(
        result["event_summary"][display_cols].sort_values("curve_type"),
        use_container_width=True,
        hide_index=True,
    )
    st.caption("Piston altitude is seafloor minus piston depth. Positive means the piston is above seafloor.")

with tab_params:
    st.subheader("Predicted recoil parameters")
    st.dataframe(
        result["parameter_table"].sort_values(["curve_type", "parameter"]),
        use_container_width=True,
        hide_index=True,
    )
    st.subheader("Initial-velocity scenarios")
    st.write(
        pd.Series(result["v0_values"]).describe(percentiles=[0.1, 0.5, 0.9]).to_frame("v0_ms").T
    )

with tab_notes:
    st.markdown(
        f"""
        This playground is intentionally baked and temporary.

        - Calibration source: `recoil_regression_12_dual_model.ipynb`
        - Raw recoil rows at bake time: `{CALIBRATION['row_count_raw']}`
        - Working recoil rows after filtering: `{CALIBRATION['row_count_working']}`
        - Low-quality core excluded from regressions: `{CALIBRATION['low_quality_cores']}`
        - No database is read by this GUI.
        - No observational trip-time offset is applied; `t = 0` is the hypothetical true trip.

        The next, more durable version should load a saved calibration artifact instead of using constants
        inside this file.
        """
    )

