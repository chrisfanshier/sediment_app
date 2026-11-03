"""Optional CLR-PCA and correlation helpers (small-scale stretch)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

from .transforms import clr_matrix


@dataclass
class PCAResult:
    scores: pd.DataFrame
    loadings: pd.DataFrame
    explained_variance_ratio: np.ndarray
    elements: list[str]


def correlation_matrix(
    df: pd.DataFrame,
    elements: list[str] | None = None,
    *,
    use_clr: bool = True,
    zero_policy: str = "addone",
) -> pd.DataFrame:
    """Pearson correlation on CLR (default) or raw peak areas."""
    if use_clr:
        mat, cols = clr_matrix(df, elements, zero_policy=zero_policy)
    else:
        from .elements import element_columns

        cols = elements or element_columns(df.columns)
        cols = [c for c in cols if c in df.columns]
        mat = df[cols].apply(pd.to_numeric, errors="coerce")
    return mat.corr(method="pearson")


def clr_pca(
    df: pd.DataFrame,
    elements: list[str] | None = None,
    *,
    n_components: int = 3,
    zero_policy: str = "addone",
    depth_col: str = "depth",
) -> PCAResult:
    """PCA on CLR-transformed element matrix (sklearn; sketch of CoDa PCA)."""
    clr, cols = clr_matrix(df, elements, zero_policy=zero_policy)
    # Drop rows with NaN (should be rare after zero policy)
    valid = clr.dropna()
    n_comp = min(n_components, len(cols), max(1, len(valid) - 1))
    pca = PCA(n_components=n_comp)
    scores = pca.fit_transform(valid.to_numpy())
    score_cols = [f"PC{i+1}" for i in range(n_comp)]
    scores_df = pd.DataFrame(scores, columns=score_cols, index=valid.index)
    if depth_col in df.columns:
        scores_df.insert(0, depth_col, df.loc[valid.index, depth_col].to_numpy())
    if "position" in df.columns:
        scores_df.insert(0 if depth_col not in scores_df.columns else 1, "position", df.loc[valid.index, "position"].to_numpy())
    loadings = pd.DataFrame(
        pca.components_.T,
        index=cols,
        columns=score_cols,
    )
    return PCAResult(
        scores=scores_df,
        loadings=loadings,
        explained_variance_ratio=pca.explained_variance_ratio_,
        elements=cols,
    )
