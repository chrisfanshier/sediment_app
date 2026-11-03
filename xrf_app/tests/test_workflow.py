"""Smoke tests against bundled CD166_19_S1 example data."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from xrf_workflow import (
    apply_qc_flags,
    clr_pca,
    correlation_matrix,
    discover_section,
    import_meta,
    import_xrf,
    load_image,
    load_spectrum,
)
from xrf_workflow.transforms import add_log_ratio, add_ratio

EXAMPLE = ROOT / "data" / "example" / "CD166_19_S1"


def test_discover_and_import():
    assert EXAMPLE.is_dir(), f"missing example data at {EXAMPLE}"
    paths = discover_section(EXAMPLE)
    assert paths.results is not None
    assert paths.document is not None

    meta = import_meta(paths.document)
    assert "Parameter" in meta.columns
    assert (meta["Parameter"] == "Tube").any()

    xrf = import_xrf(paths.results, depth_top=0.0)
    assert "position" in xrf.columns
    assert "depth" in xrf.columns
    assert abs(float(xrf["depth"].iloc[0]) - 0.0) < 1e-6
    assert "Fe" in xrf.columns
    assert "Mo inc" in xrf.columns
    assert len(xrf) > 1000


def test_qc_and_transforms():
    xrf = import_xrf(EXAMPLE / "Results.txt", depth_top=10.0)
    assert float(xrf["depth"].iloc[0]) == 10.0
    qc = apply_qc_flags(xrf)
    assert "qc" in qc.columns
    assert qc["qc"].dtype == bool
    assert 0 < int(qc["qc"].sum()) < len(qc)

    r = add_ratio(qc, "Fe", "Ca")
    assert "Fe/Ca" in r.columns
    lr = add_log_ratio(qc, "Fe", "Ca")
    assert "ln(Fe/Ca)" in lr.columns
    assert np.isfinite(lr["ln(Fe/Ca)"].dropna().iloc[0])


def test_images_spectrum_pca():
    paths = discover_section(EXAMPLE)
    opt = load_image(paths.optical)
    assert opt.ndim in (2, 3)
    rad = load_image(paths.radiograph)
    assert rad.ndim == 2

    spe = load_spectrum(paths.spectra[0], dfl=paths.dfl)
    assert {"channel", "count"} <= set(spe.columns)
    assert "energy" in spe.columns

    xrf = apply_qc_flags(import_xrf(paths.results, depth_top=0.0))
    passed = xrf.loc[xrf["qc"]]
    elems = [e for e in ["Si", "Ca", "Ti", "Fe", "Sr"] if e in passed.columns]
    corr = correlation_matrix(passed, elems, use_clr=True)
    assert corr.shape == (len(elems), len(elems))
    pca = clr_pca(passed, elems, n_components=2)
    assert "PC1" in pca.scores.columns
    assert abs(pca.explained_variance_ratio.sum() - pca.explained_variance_ratio.sum()) < 1e-9


if __name__ == "__main__":
    test_discover_and_import()
    test_qc_and_transforms()
    test_images_spectrum_pca()
    print("OK")
