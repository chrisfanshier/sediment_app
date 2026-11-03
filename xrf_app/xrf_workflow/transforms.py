"""Simple XRF transforms: ratios, Mo-inc normalisation, log-ratios, CLR sketch."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .elements import element_columns


def add_ratio(df: pd.DataFrame, num: str, den: str, *, name: str | None = None) -> pd.DataFrame:
    """Element/element ratio; Inf/NaN from /0 → NA."""
    out = df.copy()
    col = name or f"{num}/{den}"
    a = pd.to_numeric(out[num], errors="coerce")
    b = pd.to_numeric(out[den], errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        r = a / b
    r = r.replace([np.inf, -np.inf], np.nan)
    out[col] = r
    return out


def add_log_ratio(df: pd.DataFrame, num: str, den: str, *, name: str | None = None) -> pd.DataFrame:
    """Natural log-ratio; prefers positive values (zeros → NA)."""
    out = df.copy()
    col = name or f"ln({num}/{den})"
    a = pd.to_numeric(out[num], errors="coerce")
    b = pd.to_numeric(out[den], errors="coerce")
    mask = (a > 0) & (b > 0)
    out[col] = np.nan
    out.loc[mask, col] = np.log(a[mask] / b[mask])
    return out


def add_mo_inc_norm(
    df: pd.DataFrame,
    elements: list[str] | None = None,
    *,
    scatter: str = "Mo inc",
) -> pd.DataFrame:
    """Normalise selected elements by Mo incoherent scatter (or Cr inc)."""
    out = df.copy()
    if scatter not in out.columns:
        raise KeyError(f"Scatter column '{scatter}' not in table")
    denom = pd.to_numeric(out[scatter], errors="coerce")
    cols = elements or element_columns(out.columns)
    for el in cols:
        if el not in out.columns:
            continue
        a = pd.to_numeric(out[el], errors="coerce")
        with np.errstate(divide="ignore", invalid="ignore"):
            r = a / denom
        out[f"{el}_/{scatter}"] = r.replace([np.inf, -np.inf], np.nan)
    return out


def clr_matrix(
    df: pd.DataFrame,
    elements: list[str] | None = None,
    *,
    zero_policy: str = "addone",
) -> tuple[pd.DataFrame, list[str]]:
    """Centered log-ratio transform for compositional sketch work.

    zero_policy:
      - ``addone``: add 1 to all values before CLR (itraxR multivariate default)
      - ``limit``: replace zeros with 0.001
    """
    cols = elements or element_columns(df.columns)
    cols = [c for c in cols if c in df.columns]
    mat = df[cols].apply(pd.to_numeric, errors="coerce").astype(float)

    # Drop all-zero columns
    keep = [c for c in cols if not (mat[c].fillna(0) == 0).all()]
    mat = mat[keep]

    if zero_policy == "addone":
        mat = mat.fillna(0) + 1.0
    elif zero_policy == "limit":
        mat = mat.fillna(0.001).replace(0, 0.001)
    else:
        raise ValueError(f"Unknown zero_policy: {zero_policy}")

    # Rows with non-positive after policy should not occur; guard anyway
    logx = np.log(mat.to_numpy())
    gm = logx.mean(axis=1, keepdims=True)
    clr = logx - gm
    clr_df = pd.DataFrame(clr, columns=keep, index=df.index)
    return clr_df, keep
