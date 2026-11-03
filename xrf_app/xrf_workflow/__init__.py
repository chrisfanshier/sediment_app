"""Minimal Python reimplementation of the Itrax / itraxR teaching workflow.

Inspired by itraxR (GPL-3) and itraxBook by Tom Bishop et al.
This is a clean-room port of documented behaviour for the CD166 example path —
not a vendored copy of the R sources.
"""

from .io import (
    discover_section,
    import_meta,
    import_xrf,
    load_image,
    load_spectrum,
    parse_qspec_settings,
)
from .qc import apply_qc_flags, default_qc_params
from .transforms import add_log_ratio, add_mo_inc_norm, add_ratio, clr_matrix
from .multivariate import correlation_matrix, clr_pca
from .plotting import stratigraphic_figure

__all__ = [
    "discover_section",
    "import_meta",
    "import_xrf",
    "load_image",
    "load_spectrum",
    "parse_qspec_settings",
    "apply_qc_flags",
    "default_qc_params",
    "add_log_ratio",
    "add_mo_inc_norm",
    "add_ratio",
    "clr_matrix",
    "correlation_matrix",
    "clr_pca",
    "stratigraphic_figure",
]

__version__ = "0.1.0"
