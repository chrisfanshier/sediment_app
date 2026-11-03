#!/usr/bin/env python3
"""Download CD166_19_S1 example files into data/example/.

Default source: itraxR ``inst/extdata`` (small, enough for step 1).
Optional ``--book``: also pull the fuller itraxBook S1 scan folder
(Results + document + optical + radiograph; skips huge XRF Data.zip unless
``--with-spectra-zip`` is set).
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "example" / "CD166_19_S1"

ITRAXR_BASE = "https://raw.githubusercontent.com/tombishop1/itraxR/master/inst/extdata"
ITRAXR_FILES = {
    "CD166_19_S1_Results.txt": "Results.txt",
    "CD166_19_S1_xrf_document.txt": "document.txt",
    "CD166_19_S1_optical_lowres.tif": "optical.tif",
    "CD166_19_S1_radiograph_adj.tif": "radiograph.tif",
    "CD166_19_S1_rad_document.txt": "rad_document.txt",
    "L000676.spe": "L000676.spe",
    "Results_settings.dfl": "Results_settings.dfl",
}

BOOK_BASE = (
    "https://raw.githubusercontent.com/tombishop1/itraxBook/master/"
    "CD166_19_(2020)/CD166_19_S1/CD166_19_S1"
)
BOOK_RAD = (
    "https://raw.githubusercontent.com/tombishop1/itraxBook/master/"
    "CD166_19_(2020)/CD166_19_S1/CD166_19_S1_RAD"
)
BOOK_OUT = ROOT / "data" / "example" / "CD166_19_S1_book"


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"GET {url}")
    print(f" -> {dest}")
    urllib.request.urlretrieve(url, dest)


def fetch_itraxr(force: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for remote, local in ITRAXR_FILES.items():
        dest = OUT / local
        if dest.exists() and not force:
            print(f"skip (exists): {dest.name}")
            continue
        download(f"{ITRAXR_BASE}/{remote}", dest)
    print(f"\nExample section ready: {OUT}")


def fetch_book(force: bool = False, with_spectra_zip: bool = False) -> None:
    scan = BOOK_OUT / "CD166_19_S1"
    rad = BOOK_OUT / "CD166_19_S1_RAD"
    files = [
        (f"{BOOK_BASE}/Results.txt", scan / "Results.txt"),
        (f"{BOOK_BASE}/document.txt", scan / "document.txt"),
        (f"{BOOK_BASE}/optical.tif", scan / "optical.tif"),
        (f"{BOOK_BASE}/sumspectra.spe", scan / "sumspectra.spe"),
        (f"{BOOK_RAD}/document.txt", rad / "document.txt"),
        (f"{BOOK_RAD}/radiograph.tif", rad / "radiograph.tif"),
    ]
    if with_spectra_zip:
        files.append((f"{BOOK_BASE}/XRF%20Data.zip", scan / "XRF Data.zip"))
    for url, dest in files:
        if dest.exists() and not force:
            print(f"skip (exists): {dest}")
            continue
        try:
            download(url, dest)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN failed {url}: {exc}", file=sys.stderr)
    print(f"\nBook-style tree ready under: {BOOK_OUT}")
    print("Point the GUI at the CD166_19_S1 scan subfolder.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="Re-download even if present")
    ap.add_argument(
        "--book",
        action="store_true",
        help="Also fetch fuller itraxBook S1 scan (+ RAD) files",
    )
    ap.add_argument(
        "--with-spectra-zip",
        action="store_true",
        help="With --book, also download XRF Data.zip (large)",
    )
    args = ap.parse_args()
    fetch_itraxr(force=args.force)
    if args.book:
        fetch_book(force=args.force, with_spectra_zip=args.with_spectra_zip)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
