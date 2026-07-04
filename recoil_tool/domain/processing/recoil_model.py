"""
Elastic rebound physics model for piston corer deployments.

Forward-integrates the post-trip equation of motion (RK4) given
user-supplied deployment parameters.  No optimisation performed here.

All functions are pure Python/numpy — no Qt, no DB.
"""
from __future__ import annotations

import math
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


def _gamma_pulse_curve(t: np.ndarray, A: float, tau: float) -> np.ndarray:
    """x(t) = A * (t/tau) * exp(1 - t/tau)  — peaks at t=tau with amplitude A."""
    return A * (t / tau) * np.exp(1.0 - t / tau)


def _damped_sine_curve(t: np.ndarray, A: float, tau: float, omega: float) -> np.ndarray:
    """x(t) = A * exp(-t/tau) * sin(omega * t)  — oscillatory decay."""
    return A * np.exp(-t / tau) * np.sin(omega * t)

def _single_lobe_damped_curve(
    t: np.ndarray,
    H: float,
    t_p: float,
    alpha: float = 0.25,
) -> np.ndarray:
    """
    Single asymmetric lobe:
      x(t) = H * (t/t_p)^alpha * (1 - t/t_p)   for 0 <= t <= t_p
      x(t) = 0                                  otherwise
    """
    t_p = max(float(t_p), 1e-6)
    alpha = max(float(alpha), 0.0)

    u = t / t_p
    x = np.zeros_like(t, dtype=float)
    mask = (u >= 0.0) & (u <= 1.0)
    if np.any(mask):
        um = u[mask]
        x[mask] = H * np.power(um, alpha) * (1.0 - um)
    return x



_CURVE_FN_MAP = {
    'exponential':        (_exp_curve,             2),
    'critically_damped':  (_crit_damped_curve,     2),
    'gamma_pulse':        (_gamma_pulse_curve,     2),
    'damped_sine':        (_damped_sine_curve,     3),
    'single_lobe_damped': (_single_lobe_damped_curve, 2),
}


def compute_model_peak(
    curve_type: str,
    *,
    t_rel: 'np.ndarray | None' = None,
    x_model: 'np.ndarray | None' = None,
    A_m: 'float | None' = None,
    tau_s: 'float | None' = None,
    omega_rads: 'float | None' = None,
    H_m: 'float | None' = None,
    t_p_s: 'float | None' = None,
    alpha: 'float | None' = None,
) -> tuple['float | None', 'float | None']:
    """Return model peak displacement/time for the selected curve type.

    Returns (None, None) for asymptotic curve types where no finite peak exists.
    """
    if curve_type == 'physics':
        if x_model is None or t_rel is None or len(x_model) == 0 or len(t_rel) == 0:
            return None, None
        idx = int(np.argmax(x_model))
        return float(x_model[idx]), float(t_rel[idx])

    if curve_type == 'single_lobe_damped':
        if H_m is None or t_p_s is None:
            return None, None
        a = float(alpha if alpha is not None else 0.25)
        t_p = float(t_p_s)
        H = float(H_m)
        if t_p <= 0:
            return None, None
        u_peak = a / (1.0 + a) if a >= 0 else 0.0
        t_peak = t_p * u_peak
        x_peak = H * (u_peak ** a) * (1.0 / (1.0 + a)) if a >= 0 else None
        if x_peak is None:
            return None, None
        return float(x_peak), float(t_peak)

    if curve_type == 'gamma_pulse':
        if A_m is None or tau_s is None:
            return None, None
        return float(A_m), float(tau_s)

    if curve_type == 'damped_sine':
        if A_m is None or tau_s is None or omega_rads is None:
            return None, None
        tau = float(tau_s)
        omega = float(omega_rads)
        A = float(A_m)
        if tau <= 0 or omega == 0:
            return None, None
        t_peak = math.atan(omega * tau) / omega
        x_peak = A * math.exp(-t_peak / tau) * math.sin(omega * t_peak)
        return float(x_peak), float(t_peak)

    if curve_type in ('exponential', 'critically_damped'):
        return None, None

    return None, None



def fit_empirical_curve(
    time_s: np.ndarray,
    depth_m: np.ndarray,
    trip_idx: int,
    curve_type: str,
    fit_end_idx: 'int | None' = None,
) -> tuple[float, float, 'float | None', np.ndarray]:
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
        One of 'exponential', 'critically_damped', 'gamma_pulse', 'damped_sine'.
    fit_end_idx : int or None
        Explicit end index for the fit window (exclusive).  When provided the
        segment depth_m[trip_idx:fit_end_idx] is used directly.  When None the
        fit window is determined by auto-detecting the rebound peak within the
        first ~30 s after trip.

    Returns
    -------
    (A, tau, omega_or_alpha, depth_model)
        A               : fitted amplitude / asymptote (m), or H for single_lobe_damped
        tau             : fitted time constant (s), or t_p for single_lobe_damped
        omega_or_alpha  : fitted omega (damped_sine), fitted alpha (single_lobe_damped), or None
        depth_model : absolute depth array over the full post-trip window
    """
    from scipy.optimize import curve_fit as _curve_fit

    if curve_type not in _CURVE_FN_MAP:
        raise ValueError(f"Unknown curve_type: {curve_type!r}")

    curve_fn, n_params = _CURVE_FN_MAP[curve_type]

    # Sample interval from the time array
    dt = float(np.median(np.diff(time_s)))
    if dt <= 0:
        dt = 1.0

    post_depth = depth_m[trip_idx:]
    trip_depth = float(depth_m[trip_idx])

    if fit_end_idx is not None:
        # Use explicitly specified window
        end = max(trip_idx + 1, min(int(fit_end_idx), len(depth_m)))
        peak_rel = end - trip_idx
        peak_idx = end
    else:
        # Auto-detect: shallowest point within the first ~30 s
        search_window = min(int(30.0 / dt) + 1, len(post_depth))
        peak_rel = int(np.argmin(post_depth[:search_window]))
        peak_idx = trip_idx + peak_rel

    # Upswing window: trip to peak (inclusive)
    n_fit = peak_rel + 1
    t_fit = np.arange(n_fit) * dt
    x_fit = trip_depth - depth_m[trip_idx: peak_idx + 1]  # upward displacement (m)

    obs_A = float(np.max(x_fit)) if len(x_fit) > 0 else 2.0

    if curve_type == 'single_lobe_damped':
        # Fit (H, t_p, alpha) explicitly.
        t_end = float(t_fit[-1]) if len(t_fit) > 1 else 1.0
        p0_H = max(obs_A * 1.8, 0.01)
        p0_t_p = max(t_end, 0.1)
        p0_alpha = 0.25

        try:
            popt, _ = _curve_fit(
                _single_lobe_damped_curve,
                t_fit,
                x_fit,
                p0=[p0_H, p0_t_p, p0_alpha],
                bounds=([0.0, 0.01, 0.01], [50.0, 120.0, 5.0]),
                maxfev=8000,
            )
            A_fit, tau_fit, omega_fit = float(popt[0]), float(popt[1]), float(popt[2])
        except Exception:
            A_fit, tau_fit, omega_fit = float(p0_H), float(p0_t_p), float(p0_alpha)

        t_post = np.arange(len(post_depth)) * dt
        x_model = _single_lobe_damped_curve(t_post, A_fit, tau_fit, omega_fit)

    elif n_params == 2:
        if curve_type == 'gamma_pulse':
            # For gamma pulse, tau is the time of peak, so seed with observed peak time
            t_peak = float(t_fit[int(np.argmax(x_fit))]) if len(t_fit) > 1 else 1.0
            p0 = [max(obs_A, 0.01), max(t_peak, 0.1)]
        else:
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
            A_fit, tau_fit = float(p0[0]), float(p0[1])

        omega_fit: 'float | None' = None
        t_post = np.arange(len(post_depth)) * dt
        x_model = curve_fn(t_post, A_fit, tau_fit)


    else:  # damped_sine (n_params == 3)
        # Seed omega from peak time: first peak of sin at omega*t_peak = pi/2
        t_peak = float(t_fit[-1]) if len(t_fit) > 1 else 1.0
        omega_est = np.pi / (2.0 * max(t_peak, 0.1))
        p0 = [max(obs_A, 0.01), max(t_peak * 2.0, 0.1), omega_est]

        try:
            popt, _ = _curve_fit(
                curve_fn, t_fit, x_fit,
                p0=p0,
                bounds=([0.0, 0.1, 0.1], [50.0, 100.0, 20.0]),
                maxfev=5000,
            )
            A_fit, tau_fit, omega_fit = float(popt[0]), float(popt[1]), float(popt[2])
        except Exception:
            A_fit, tau_fit, omega_fit = float(p0[0]), float(p0[1]), float(p0[2])

        t_post = np.arange(len(post_depth)) * dt
        x_model = curve_fn(t_post, A_fit, tau_fit, omega_fit)

    depth_model = trip_depth - x_model
    return A_fit, tau_fit, omega_fit, depth_model


def evaluate_empirical_curve(
    time_s: np.ndarray,
    depth_m: np.ndarray,
    trip_idx: int,
    curve_type: str,
    A: float,
    tau: float,
    omega: float = 1.0,
    alpha: float = 0.25,
) -> np.ndarray:
    """
    Evaluate an empirical rebound curve with user-supplied parameters.

    Parameters
    ----------
    omega : float
        Angular frequency (rad/s) — only used when curve_type == 'damped_sine'.

    Returns
    -------
    np.ndarray
        Absolute depth array over the full post-trip window.
    """
    curve_fn, n_params = _CURVE_FN_MAP.get(curve_type, (_exp_curve, 2))

    dt = float(np.median(np.diff(time_s)))
    if dt <= 0:
        dt = 1.0

    post_depth = depth_m[trip_idx:]
    t_post = np.arange(len(post_depth)) * dt
    if curve_type == 'single_lobe_damped':
        x_model = _single_lobe_damped_curve(t_post, A, tau, alpha)
    else:
        x_model = curve_fn(t_post, A, tau, omega) if n_params == 3 else curve_fn(t_post, A, tau)
    trip_depth = float(depth_m[trip_idx])
    return trip_depth - x_model
