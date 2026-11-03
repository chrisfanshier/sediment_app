"""Parsers for Itrax section folders (document.txt, Results.txt, images, spe, dfl).

Behaviour mirrors documented itraxR / itraxBook conventions for the CD166 example,
implemented cleanly in Python without vendoring R sources.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from PIL import Image

from .elements import PERIODIC_SYMBOLS, element_columns


@dataclass
class SectionPaths:
    """Resolved paths for one scan / section folder."""

    root: Path
    results: Optional[Path] = None
    document: Optional[Path] = None
    optical: Optional[Path] = None
    radiograph: Optional[Path] = None
    rad_document: Optional[Path] = None
    dfl: Optional[Path] = None
    spectra: list[Path] = field(default_factory=list)
    spectra_zip: Optional[Path] = None


def _first_existing(root: Path, names: list[str]) -> Optional[Path]:
    for name in names:
        p = root / name
        if p.exists():
            return p
    # Case-insensitive fallback for Windows-ish trees on Linux
    lower_map = {c.name.lower(): c for c in root.iterdir() if c.is_file()}
    for name in names:
        hit = lower_map.get(name.lower())
        if hit is not None:
            return hit
    return None


def discover_section(path: str | Path) -> SectionPaths:
    """Locate standard Itrax files under a section/scan folder.

    Accepts either a real lab folder (document.txt + Results.txt + …) or the
    flattened itraxR ``inst/extdata`` layout staged as example data.
    """
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Section folder not found: {root}")

    results = _first_existing(
        root,
        ["Results.txt", "result.txt", "CD166_19_S1_Results.txt"],
    )
    document = _first_existing(
        root,
        ["document.txt", "CD166_19_S1_xrf_document.txt"],
    )
    optical = _first_existing(
        root,
        [
            "optical.tif",
            "optical0.tif",
            "CD166_19_S1_optical_lowres.tif",
            "optical.tiff",
        ],
    )
    radiograph = _first_existing(
        root,
        [
            "radiograph.tif",
            "radiograph0.tif",
            "radiograph_adj.tif",
            "CD166_19_S1_radiograph_adj.tif",
            "radiograph.tiff",
        ],
    )
    rad_document = _first_existing(
        root,
        ["rad_document.txt", "CD166_19_S1_rad_document.txt"],
    )
    dfl = None
    for candidate in sorted(root.glob("*.dfl")):
        dfl = candidate
        break
    # Names with a space (Results_ settings.dfl) are common in the book dataset
    if dfl is None:
        for candidate in root.iterdir():
            if candidate.is_file() and candidate.suffix.lower() == ".dfl":
                dfl = candidate
                break

    spectra = sorted(root.glob("*.spe")) + sorted(root.glob("*.SPE"))
    spectra_zip = None
    for zip_name in ["XRF Data.zip", "XRF data.zip", "XRF_Data.zip"]:
        z = root / zip_name
        if z.exists():
            spectra_zip = z
            break

    return SectionPaths(
        root=root,
        results=results,
        document=document,
        optical=optical,
        radiograph=radiograph,
        rad_document=rad_document,
        dfl=dfl,
        spectra=spectra,
        spectra_zip=spectra_zip,
    )


def import_meta(path: str | Path) -> pd.DataFrame:
    """Parse ``document.txt`` into a Parameter / Value / Unit table.

    Tolerant of the CD166 layout used by itraxR examples. Not a byte-for-byte
    clone of ``itrax_meta``'s hard-coded row reshuffling — returns a practical
    key/value view plus a few derived convenience fields.
    """
    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode("latin-1", errors="replace")
    lines = [ln.rstrip("\r\n") for ln in text.splitlines() if ln.strip()]

    rows: list[dict[str, Any]] = []

    def add(param: str, value: Any, unit: str = "") -> None:
        rows.append({"Parameter": param, "Value": value, "Unit": unit})

    # Line 0–1: headers + sample identity
    if len(lines) >= 2:
        hdr = lines[0].split("\t")
        vals = lines[1].split("\t")
        labels = ["Base path", "Sample name", "Section name", "User ID"]
        for i, label in enumerate(labels):
            if i < len(vals):
                add(label, vals[i].strip())

    # Date block
    if len(lines) >= 4 and lines[2].lower().startswith("year"):
        ymd = lines[3].split("\t")
        if len(ymd) >= 3:
            add("Acquisition date", f"{ymd[2].zfill(2)}/{ymd[1].zfill(2)}/{ymd[0]}")
            if len(ymd) >= 4 and ymd[3].strip():
                add("Acquisition time", ymd[3].strip())

    # Remaining key rows — parse common patterns
    for ln in lines[4:]:
        parts = [p.strip() for p in ln.split("\t")]
        if not parts or not parts[0]:
            continue
        key = parts[0]
        if key == "Start coordinate" and len(parts) >= 4:
            add("Start coordinate", parts[1], "mm")
            add("Stop coordinate", parts[3], "mm")
        elif key == "Optical Start" and len(parts) >= 4:
            add("Optical Start", parts[1], "mm")
            add("Optical End", parts[3], "mm")
        elif key == "XRF voltage and current" and len(parts) >= 4:
            add("XRF voltage", parts[1], "kV")
            add("XRF current", parts[3], "mA")
        elif key.lower().startswith("step size"):
            unit = parts[2] if len(parts) > 2 else ""
            # Book / package note: optical step unit in file may say microns but is mm
            add(key, parts[1] if len(parts) > 1 else "", unit)
        elif len(parts) >= 2:
            unit = parts[2] if len(parts) > 2 else ""
            add(key, parts[1], unit)

    return pd.DataFrame(rows)


def _meta_lookup(meta: pd.DataFrame, parameter: str) -> Optional[str]:
    if meta is None or meta.empty:
        return None
    hit = meta.loc[meta["Parameter"] == parameter, "Value"]
    if hit.empty:
        return None
    return str(hit.iloc[0])


def import_xrf(
    path: str | Path,
    *,
    depth_top: float | None = 0.0,
    trim_top: float | None = None,
    trim_bottom: float | None = None,
    parameters: str = "all",
) -> pd.DataFrame:
    """Import Q-Spec ``Results.txt`` / ``result.txt``.

    Mirrors the documented ``itrax_import`` contract:
    - skip 2 header comment lines
    - rename ``position (mm)`` → ``position``
    - ``depth = position - min(position) + depth_top`` when depth_top is numeric
    - invalid rows (``validity`` false) → element zeros become NA
    - ``parameters='some'`` keeps periodic symbols + useful scatter columns
    """
    path = Path(path)
    df = pd.read_csv(path, sep="\t", skiprows=2, encoding="latin-1", engine="python")
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    df.columns = [c.strip() for c in df.columns]

    if "position (mm)" in df.columns:
        df = df.rename(columns={"position (mm)": "position"})

    if "validity" in df.columns:
        # Q-Spec exports 0/1; tolerate boolean strings
        as_num = pd.to_numeric(df["validity"], errors="coerce")
        if as_num.notna().any():
            df["validity"] = as_num.fillna(0).astype(int).astype(bool)
        else:
            df["validity"] = (
                df["validity"]
                .astype(str)
                .str.strip()
                .str.lower()
                .map({"true": True, "false": False, "1": True, "0": False})
                .fillna(False)
            )

    # Depth assignment (coring depth offset supplied by user / lab book)
    if depth_top is not None and "position" in df.columns and len(df):
        pos_min = float(df["position"].min())
        df["depth"] = df["position"] - pos_min + float(depth_top)
    else:
        df["depth"] = np.nan

    # Trim by machine position
    if trim_top is not None and "position" in df.columns:
        df = df.loc[df["position"] >= float(trim_top)]
    if trim_bottom is not None and "position" in df.columns:
        df = df.loc[df["position"] <= float(trim_bottom)]
    df = df.reset_index(drop=True)

    elems = element_columns(df.columns)
    if "validity" in df.columns and elems:
        invalid = ~df["validity"].astype(bool)
        for col in elems:
            zero_mask = invalid & (pd.to_numeric(df[col], errors="coerce") == 0)
            df.loc[zero_mask, col] = np.nan

    if parameters == "some":
        keep = [
            c
            for c in df.columns
            if c
            in {
                "filename",
                "position",
                "depth",
                "sample surface",
                "validity",
                "cps",
                "MSE",
                "Dt",
                "Mo inc",
                "Mo coh",
                "Cr inc",
                "Cr coh",
            }
            or c in PERIODIC_SYMBOLS
        ]
        # Preserve order of appearance
        seen = set()
        ordered = []
        for c in df.columns:
            if c in keep and c not in seen:
                ordered.append(c)
                seen.add(c)
        df = df[ordered]

    return df


def parse_qspec_settings(path: str | Path) -> pd.DataFrame:
    """Parse a Q-Spec ``*.dfl`` settings file into key/value rows."""
    path = Path(path)
    rows = []
    for ln in path.read_text(encoding="latin-1", errors="replace").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("["):
            continue
        if "=" not in ln:
            continue
        key, _, val = ln.partition("=")
        rows.append({"key": key.strip(), "value": val.strip()})
    return pd.DataFrame(rows)


def load_spectrum(
    path: str | Path,
    *,
    datapos: int = 37,
    dfl: str | Path | None = None,
) -> pd.DataFrame:
    """Load one ``*.spe`` MCA spectrum (channel / count [/ energy])."""
    path = Path(path)
    lines = path.read_text(encoding="latin-1", errors="replace").splitlines()
    # Find "channel" header flexibly
    start = datapos
    for i, ln in enumerate(lines):
        if ln.lower().startswith("channel"):
            start = i + 1
            break
    data = []
    for ln in lines[start:]:
        parts = ln.replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            ch = float(parts[0])
            ct = float(parts[1])
        except ValueError:
            continue
        data.append((ch, ct))
    out = pd.DataFrame(data, columns=["channel", "count"])
    if dfl is not None:
        settings = parse_qspec_settings(dfl)
        kev = settings.loc[settings["key"].str.contains("keV/channel", case=False), "value"]
        off = settings.loc[settings["key"].str.contains("energy offset", case=False), "value"]
        if not kev.empty and not off.empty:
            out["energy"] = out["channel"] * float(kev.iloc[0]) + float(off.iloc[0])
    return out


def load_image(path: str | Path) -> np.ndarray:
    """Load optical or radiograph TIFF as a numpy array (PIL + imagecodecs)."""
    path = Path(path)
    with Image.open(path) as im:
        arr = np.array(im)
    return arr


def join_sections(sections: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Stack named section tables (requires ``depth``), like ``itrax_join``."""
    frames = []
    for label, df in sections.items():
        if "depth" not in df.columns:
            raise ValueError(f"Section '{label}' is missing depth; set depth_top on import.")
        part = df.copy()
        part["label"] = label
        frames.append(part)
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values("depth").reset_index(drop=True)
