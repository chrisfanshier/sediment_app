"""
Domain models for the recoil overlay tool.

DeploymentParams: Physical inputs describing one corer deployment (includes
                  user-supplied E_gpa and C_drag).
ModelResult:      Output of running the forward rebound model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DeploymentParams:
    """Physical parameters describing a single corer deployment."""

    depth_m: float
    """Wire/rope length at trip = seafloor depth of release device (m)."""

    corer_lbs: float
    """Corer weight in air (lbs)."""

    instrument_lbs: float = 0.0
    """Release device weight in air (lbs)."""

    rope_type: str = 'hmpe'
    """Rope/wire material: 'hmpe' or 'steel'."""

    rope_dia_mm: float = 14.3
    """Rope/wire outer diameter (mm)."""

    E_gpa: float = 45.0
    """Effective elastic modulus (GPa) — user-supplied tuning knob."""

    C_drag: float = 0.01
    """Hydrodynamic drag coefficient (dimensionless)."""

    deployment_id: Optional[str] = None
    """Optional label (e.g. core name) for display/export."""

    # Empirical curve-fitting options (ignored by physics model path)
    curve_type: str = 'physics'
    """One of 'physics', 'exponential', 'critically_damped'."""

    A_m: float = 2.0
    """Asymptotic rebound magnitude (m) for empirical curves."""

    tau_s: float = 1.0
    """Time constant (s) for empirical curves."""

    auto_fit: bool = True
    """When True, run curve_fit automatically; otherwise use A_m/tau_s directly."""


@dataclass
class ModelResult:
    """Output of running the forward rebound model with user-supplied parameters."""

    v0_ms: float
    """Estimated velocity at trip instant (m/s, positive = downward)."""

    peak_displacement_m: float
    """Peak upward displacement from trip depth (m)."""

    peak_time_s: float
    """Time from trip to peak displacement (s)."""

    k_nm: float
    """Rope spring constant at the supplied E_gpa (N/m)."""

    deployment: DeploymentParams
    """The deployment parameters used to produce this result."""
