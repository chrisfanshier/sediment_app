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
