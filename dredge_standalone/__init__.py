"""Standalone Dredge App — self-contained USBL & time-series viewer.

A PySide6 desktop application for co-plotting dredge sensor / winch time
series with USBL spatial data, annotating time ranges, and exporting the
results.  All metadata lives in a per-project SQLite database and all data
files are copied into the project folder, so a project is a single portable
directory with no external database or server required.

Run with:  python -m dredge_standalone
"""

__version__ = "1.0.0"
