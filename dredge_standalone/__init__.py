"""Dragognosificator — self-contained USBL & time-series viewer.

A PySide6 desktop application for co-plotting dredge sensor / winch time
series with USBL spatial data, annotating time ranges, and exporting the
results.  All metadata lives in a per-project SQLite database and all data
files are copied into the project folder.

Run with:  python -m dredge_standalone
"""

APP_NAME = "Dragognosificator"
__version__ = "1.0.0"
