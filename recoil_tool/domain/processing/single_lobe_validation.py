"""
Standalone validation helpers for the single_lobe_damped empirical curve.

This module can be run directly to visualize shape and parameter sensitivity,
or imported from notebooks/scripts for quick checks against real data.
"""
from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt


def evaluate_single_lobe_damped(
    t_s: np.ndarray,
    H_m: float,
    t_p_s: float,
    alpha: float,
) -> np.ndarray:
    """
    Evaluate:
      x(t) = H * (t/t_p)^alpha * (1 - t/t_p)   for 0 <= t <= t_p
      x(t) = 0                                 otherwise

    Returns upward displacement x(t) in meters.
    """
    t = np.asarray(t_s, dtype=float)
    t_p = max(float(t_p_s), 1e-6)
    a = max(float(alpha), 0.0)

    u = t / t_p
    x = np.zeros_like(t)
    mask = (u >= 0.0) & (u <= 1.0)
    if np.any(mask):
        um = u[mask]
        x[mask] = float(H_m) * np.power(um, a) * (1.0 - um)
    return x


def plot_single_lobe_against_data(
    time_s: np.ndarray,
    depth_m: np.ndarray,
    trip_idx: int,
    H_m: float,
    t_p_s: float,
    alpha: float = 0.25,
):
    """Plot observed post-trip rebound and the single_lobe_damped model."""
    if trip_idx < 0 or trip_idx >= len(time_s):
        raise ValueError("trip_idx is out of bounds")

    t_post = np.asarray(time_s[trip_idx:], dtype=float)
    d_post = np.asarray(depth_m[trip_idx:], dtype=float)
    t_rel = t_post - t_post[0]
    trip_depth = float(depth_m[trip_idx])

    x_obs = trip_depth - d_post
    x_model = evaluate_single_lobe_damped(t_rel, H_m=H_m, t_p_s=t_p_s, alpha=alpha)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))

    axes[0].plot(t_rel, x_obs, label="Observed", color="#333333", linewidth=1.8)
    axes[0].plot(t_rel, x_model, label="Model", color="#1f77b4", linewidth=2.2)
    axes[0].set_xlabel("Time since trip (s)")
    axes[0].set_ylabel("Upward displacement (m)")
    axes[0].set_title("Single Lobe Fit vs Observed")
    axes[0].grid(True, alpha=0.25)
    axes[0].legend()

    depth_model = trip_depth - x_model
    axes[1].plot(t_post, d_post, label="Observed depth", color="#333333", linewidth=1.8)
    axes[1].plot(t_post, depth_model, label="Model depth", color="#1f77b4", linewidth=2.2)
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Absolute time (s)")
    axes[1].set_ylabel("Depth (m)")
    axes[1].set_title("Depth Overlay")
    axes[1].grid(True, alpha=0.25)
    axes[1].legend()

    fig.tight_layout()
    return fig, axes


def plot_parameter_sensitivity(
    t_max_s: float = 25.0,
    dt_s: float = 0.05,
    H_values: tuple[float, ...] = (1.0, 2.0, 3.0),
    t_p_values: tuple[float, ...] = (3.0, 6.0, 10.0),
    alpha_values: tuple[float, ...] = (0.1, 0.25, 0.6),
):
    """Plot separate sweeps for H, t_p, and alpha to validate sensitivity."""
    t = np.arange(0.0, float(t_max_s) + float(dt_s), float(dt_s))

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.2), sharey=True)

    for H in H_values:
        x = evaluate_single_lobe_damped(t, H_m=H, t_p_s=6.0, alpha=0.25)
        axes[0].plot(t, x, linewidth=2.0, label=f"H={H:g}")
    axes[0].set_title("Sensitivity: H")
    axes[0].set_xlabel("t (s)")
    axes[0].set_ylabel("x(t) (m)")
    axes[0].grid(True, alpha=0.25)
    axes[0].legend()

    for t_p in t_p_values:
        x = evaluate_single_lobe_damped(t, H_m=2.0, t_p_s=t_p, alpha=0.25)
        axes[1].plot(t, x, linewidth=2.0, label=f"t_p={t_p:g}")
    axes[1].set_title("Sensitivity: t_p")
    axes[1].set_xlabel("t (s)")
    axes[1].grid(True, alpha=0.25)
    axes[1].legend()

    for a in alpha_values:
        x = evaluate_single_lobe_damped(t, H_m=2.0, t_p_s=6.0, alpha=a)
        axes[2].plot(t, x, linewidth=2.0, label=f"alpha={a:g}")
    axes[2].set_title("Sensitivity: alpha")
    axes[2].set_xlabel("t (s)")
    axes[2].grid(True, alpha=0.25)
    axes[2].legend()

    fig.tight_layout()
    return fig, axes


if __name__ == "__main__":
    # Quick visual sanity check without DB dependencies.
    demo_t = np.linspace(0.0, 20.0, 401)
    demo_depth = 1000.0 - evaluate_single_lobe_damped(demo_t, H_m=2.5, t_p_s=8.0, alpha=0.25)
    plot_single_lobe_against_data(
        time_s=demo_t,
        depth_m=demo_depth,
        trip_idx=0,
        H_m=2.5,
        t_p_s=8.0,
        alpha=0.25,
    )
    plot_parameter_sensitivity()
    plt.show()
