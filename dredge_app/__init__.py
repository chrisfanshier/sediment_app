"""
Dredge App — USBL location + time-series viewer with database integration.

This is the "full" dredge visualization app (interactive USBL map linked to
time-series brush selection, zone annotation, and CSV / GeoPackage export),
adapted so that data is pulled directly from the sediment_app PostgreSQL
database instead of pre-built CSV files.

Run with:
    python -m dredge_app
"""

__all__ = ["main"]


def main():
    from .__main__ import main as _main
    _main()
