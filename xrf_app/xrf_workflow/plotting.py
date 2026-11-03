"""Stratigraphic plots with optional optical / radiograph strips."""

from __future__ import annotations

from typing import Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure


def stratigraphic_figure(
    df: pd.DataFrame,
    elements: Sequence[str],
    *,
    depth_col: str = "depth",
    optical: np.ndarray | None = None,
    radiograph: np.ndarray | None = None,
    qc_col: str | None = "qc",
    title: str | None = None,
    figsize: tuple[float, float] | None = None,
) -> Figure:
    """Depth-down stratigraphic panels for selected series.

    Images (if provided) are shown as side strips spanning the XRF depth range.
    Orientation is approximate for the teaching example — not a full itrax_image
    meta-aligned mosaic.
    """
    if depth_col not in df.columns or df[depth_col].isna().all():
        depth_col = "position"
    y = pd.to_numeric(df[depth_col], errors="coerce")
    elems = [e for e in elements if e in df.columns]
    if not elems:
        raise ValueError("No selected columns found in dataframe")

    n_img = int(optical is not None) + int(radiograph is not None)
    n = len(elems) + n_img
    if figsize is None:
        figsize = (max(8, 1.6 * n), 8)

    fig, axes = plt.subplots(
        1,
        n,
        figsize=figsize,
        sharey=True,
        gridspec_kw={"width_ratios": ([0.55] * n_img) + ([1.0] * len(elems))},
    )
    if n == 1:
        axes = [axes]
    axes = list(axes)

    ax_i = 0
    y0, y1 = float(y.min()), float(y.max())

    def _show_strip(ax, img: np.ndarray, label: str) -> None:
        arr = img
        # Optical lowres from extdata is (width, length, 3) or (H, W, 3).
        # Show with depth along vertical axis; extent bottom/top puts shallow at top.
        if arr.ndim == 3:
            if arr.shape[1] > arr.shape[0]:
                arr = np.rot90(arr, k=-1)
            ax.imshow(arr, aspect="auto", extent=[0, 1, y1, y0], origin="upper")
        else:
            if arr.shape[1] > arr.shape[0]:
                arr = np.rot90(arr, k=-1)
            lo, hi = np.percentile(arr, [2, 98])
            vis = np.clip((arr.astype(float) - lo) / max(hi - lo, 1e-9), 0, 1)
            ax.imshow(vis, cmap="gray", aspect="auto", extent=[0, 1, y1, y0], origin="upper")
        ax.set_xticks([])
        ax.set_xlabel(label, fontsize=9)
        ax.set_xlim(0, 1)

    if optical is not None:
        _show_strip(axes[ax_i], optical, "Optical")
        ax_i += 1
    if radiograph is not None:
        _show_strip(axes[ax_i], radiograph, "Radiograph")
        ax_i += 1

    for j, el in enumerate(elems):
        ax = axes[ax_i + j]
        x = pd.to_numeric(df[el], errors="coerce")
        if qc_col and qc_col in df.columns:
            ok = df[qc_col].fillna(False).astype(bool)
            ax.plot(x[~ok], y[~ok], color="#bbbbbb", lw=0.8, label="fail QC")
            ax.plot(x[ok], y[ok], color="#1f4e79", lw=1.2, label="pass QC")
        else:
            ax.plot(x, y, color="#1f4e79", lw=1.2)
        ax.set_xlabel(el, fontsize=9)
        ax.grid(True, axis="x", alpha=0.25)
        ax.tick_params(labelsize=8)

    axes[0].set_ylabel(depth_col + " (mm)", fontsize=10)
    # Depth increases downward (shared y); avoid invert_yaxis after imshow extent.
    for ax in axes:
        ax.set_ylim(y1, y0)
    if title:
        fig.suptitle(title, fontsize=12)
    fig.tight_layout()
    return fig


def qc_overview_figure(df: pd.DataFrame, depth_col: str = "depth") -> Figure:
    """Rug-style overview of QC component flags vs depth."""
    if depth_col not in df.columns or df[depth_col].isna().all():
        depth_col = "position"
    flags = [c for c in ["qc_validity", "qc_cps", "qc_mse", "qc_slope", "qc_ar", "qc"] if c in df.columns]
    y = pd.to_numeric(df[depth_col], errors="coerce")
    fig, axes = plt.subplots(1, len(flags), figsize=(1.4 * len(flags), 6), sharey=True)
    if len(flags) == 1:
        axes = [axes]
    for ax, flag in zip(axes, flags):
        vals = df[flag].fillna(False).astype(bool)
        ax.scatter(np.where(vals, 1, 0), y, c=np.where(vals, "#2a9d8f", "#e76f51"), s=4, marker="|")
        ax.set_xlabel(flag.replace("qc_", ""), fontsize=8)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["fail", "pass"], fontsize=7)
        ax.set_xlim(-0.5, 1.5)
    axes[0].set_ylabel(depth_col + " (mm)")
    y0, y1 = float(y.min()), float(y.max())
    for ax in axes:
        ax.set_ylim(y1, y0)
    fig.suptitle("QC flags", fontsize=11)
    fig.tight_layout()
    return fig
