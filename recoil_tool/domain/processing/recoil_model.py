"""
Elastic rebound physics model for piston corer deployments.

Forward-integrates the post-trip equation of motion (RK4) given
user-supplied deployment parameters.  No optimisation performed here.

All functions are pure Python/numpy — no Qt, no DB.
"""
from __future__ import annotations

import warnings

import numpy as np
from scipy.signal import savgol_filter

from ..models.recoil_params import DeploymentParams

# ---------------------------------------------------------------------------
# Rope material defaults
# ---------------------------------------------------------------------------

ROPE_PROPS: dict[str, dict] = {
    'hmpe': dict(
        E_gpa_init=45.0,
        rho=970.0,
        buoyancy=1 - 1025 / 970,
        Cf=0.010,
    ),
    'steel': dict(
        E_gpa_init=200.0,
        rho=7850.0,
        buoyancy=1 - 1025 / 7850,
        Cf=0.008,
    ),
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _spring_constant(E_gpa: float, dia_mm: float, depth_m: float) -> float:
    """k = E * A / L  (N/m)."""
    A = np.pi * ((dia_mm / 1000) / 2) ** 2
    return (E_gpa * 1e9 * A) / depth_m


def _effective_mass(params: DeploymentParams) -> float:
    """m_eff = m_instrument + 0.5*m_rope + m_added_water  (kg)."""
    rho_w = 1025.0
    dia_m = params.rope_dia_mm / 1000
    A = np.pi * (dia_m / 2) ** 2
    props = ROPE_PROPS[params.rope_type]
    m_rope = A * props['rho'] * params.depth_m
    m_inst = params.instrument_lbs * 0.4536
    m_added = 1.0 * rho_w * A * params.depth_m
    return m_inst + 0.5 * m_rope + m_added


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def forward_model(
    t_rel: np.ndarray,
    params: DeploymentParams,
    E_gpa: float,
    C_drag: float,
    v0_ms: float = 0.0,
) -> np.ndarray:
    """
    Integrate the rebound equation of motion via RK4 (dt=0.01 s).

    Parameters
    ----------
    t_rel : array
        Time array relative to trip (s), starting at 0.
    params : DeploymentParams
    E_gpa : float
        Effective elastic modulus (GPa).
    C_drag : float
        Hydrodynamic drag coefficient.
    v0_ms : float
        Initial velocity at trip (m/s, positive = downward).

    Returns
    -------
    np.ndarray
        Upward displacement (m) sampled at t_rel.
        Positive = shallower than trip depth.
    """
    rho_w = 1025.0
    dia_m = params.rope_dia_mm / 1000
    A_wetted = np.pi * dia_m * params.depth_m

    k = _spring_constant(E_gpa, params.rope_dia_mm, params.depth_m)
    m_eff = _effective_mass(params)

    m_corer = params.corer_lbs * 0.4536
    # Corer weight in water — upward driving force released at trip
    F_drive = m_corer * 9.81 * (1 - rho_w / 7850)

    dt = 0.01
    t_sim = np.arange(0, t_rel[-1] + dt, dt)
    x = 0.0
    v = -v0_ms  # internally: positive = upward

    x_out = np.zeros(len(t_sim))

    def accel(xi: float, vi: float) -> float:
        fd = 0.5 * rho_w * C_drag * A_wetted * vi * abs(vi)
        return (F_drive - k * xi - fd) / m_eff

    for i in range(len(t_sim)):
        x_out[i] = x
        a1 = accel(x, v)
        a2 = accel(x + 0.5 * dt * v, v + 0.5 * dt * a1)
        a3 = accel(x + 0.5 * dt * (v + 0.5 * dt * a1), v + 0.5 * dt * a2)
        a4 = accel(x + dt * (v + dt * a2), v + dt * a3)
        v += dt * (a1 + 2 * a2 + 2 * a3 + a4) / 6
        x += dt * v

    return np.interp(t_rel, t_sim, x_out)


def estimate_v0(
    time: np.ndarray,
    depth: np.ndarray,
    trip_idx: int,
    window_s: float = 10.0,
    polyorder: int = 3,
) -> float:
    """
    Estimate lowering velocity at the trip instant using a backward-looking
    Savitzky-Golay derivative on the pre-trip depth window.

    Parameters
    ----------
    time : array
        Absolute time in seconds.
    depth : array
        Depth in metres (positive downward).
    trip_idx : int
        Index of trip in time/depth arrays.
    window_s : float
        Window duration (s) to use for SG filter.
    polyorder : int
        Polynomial order for SG filter.

    Returns
    -------
    float
        Velocity in m/s, positive = downward.
        Returns 0.0 if there is insufficient pre-trip data.
    """
    if trip_idx < polyorder + 2:
        warnings.warn("Insufficient pre-trip data for v0 estimation; using 0.0 m/s")
        return 0.0

    dt = float(np.median(np.diff(time)))
    if dt <= 0:
        return 0.0

    win = int(window_s / dt)
    win = max(win, polyorder + 2)
    win = win if win % 2 == 1 else win + 1

    start = max(0, trip_idx - win)
    seg = depth[start: trip_idx + 1]
    win = min(win, len(seg))
    win = win if win % 2 == 1 else win - 1

    if win < polyorder + 2:
        return 0.0

    try:
        return float(savgol_filter(seg, win, polyorder, deriv=1, delta=dt)[-1])
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Empirical rebound curves
# ---------------------------------------------------------------------------

def _exp_curve(t: np.ndarray, A: float, tau: float) -> np.ndarray:
    """x(t) = A * (1 - exp(-t/tau))  — upward displacement (m)."""
    return A * (1.0 - np.exp(-t / tau))


def _crit_damped_curve(t: np.ndarray, A: float, tau: float) -> np.ndarray:
    """x(t) = A * (1 - (1 + t/tau) * exp(-t/tau))  — upward displacement (m)."""
    return A * (1.0 - (1.0 + t / tau) * np.exp(-t / tau))


def fit_empirical_curve(
    time_s: np.ndarray,
    depth_m: np.ndarray,
    trip_idx: int,
    curve_type: str,
) -> tuple[float, float, np.ndarray]:
    """
    Fit an empirical rebound curve to the observed upswing.

    Parameters
    ----------
    time_s : array
        Absolute time in seconds.
    depth_m : array
        Depth in metres (positive downward).
    trip_idx : int
        Index of trip in the arrays.
    curve_type : str
        'exponential' or 'critically_damped'.

    Returns
    -------
    (A, tau, depth_model)
        A           : fitted asymptotic magnitude (m)
        tau         : fitted time constant (s)
        depth_model : absolute depth array over the full post-trip window
    """
    from scipy.optimize import curve_fit as _curve_fit

    curve_fn = _exp_curve if curve_type == 'exponential' else _crit_damped_curve

    # Sample interval from the time array
    dt = float(np.median(np.diff(time_s)))
    if dt <= 0:
        dt = 1.0

    # Peak = shallowest point after trip (minimum depth = maximum rebound)
    post_depth = depth_m[trip_idx:]
    peak_rel = int(np.argmin(post_depth))
    peak_idx = trip_idx + peak_rel

    # Upswing window: trip to peak (inclusive)
    n_fit = peak_rel + 1
    t_fit = np.arange(n_fit) * dt
    trip_depth = float(depth_m[trip_idx])
    x_fit = trip_depth - depth_m[trip_idx: peak_idx + 1]  # upward displacement

    obs_A = float(np.max(x_fit)) if len(x_fit) > 0 else 2.0
    est_tau = (t_fit[-1] / 3.0) if len(t_fit) > 1 else 1.0
    p0 = [max(obs_A, 0.01), max(est_tau, 0.1)]

    try:
        popt, _ = _curve_fit(
            curve_fn, t_fit, x_fit,
            p0=p0,
            bounds=([0.0, 0.01], [50.0, 60.0]),
            maxfev=5000,
        )
        A_fit, tau_fit = float(popt[0]), float(popt[1])
    except Exception:
        # Fitting failed — fall back to initial guess
        A_fit, tau_fit = float(p0[0]), float(p0[1])

    # Evaluate over the full post-trip window
    t_post = np.arange(len(post_depth)) * dt
    x_model = curve_fn(t_post, A_fit, tau_fit)
    depth_model = trip_depth - x_model

    return A_fit, tau_fit, depth_model


def evaluate_empirical_curve(
    time_s: np.ndarray,
    depth_m: np.ndarray,
    trip_idx: int,
    curve_type: str,
    A: float,
    tau: float,
) -> np.ndarray:
    """
    Evaluate an empirical rebound curve with user-supplied A and tau.

    Returns
    -------
    np.ndarray
        Absolute depth array over the full post-trip window.
    """
    curve_fn = _exp_curve if curve_type == 'exponential' else _crit_damped_curve

    dt = float(np.median(np.diff(time_s)))
    if dt <= 0:
        dt = 1.0

    post_depth = depth_m[trip_idx:]
    t_post = np.arange(len(post_depth)) * dt
    x_model = curve_fn(t_post, A, tau)
    trip_depth = float(depth_m[trip_idx])
    return trip_depth - x_model
