"""Project store: a portable folder holding a SQLite database plus data files.

A *project* is a directory the user creates/opens from the app:

    MyProject/
      dredge_data.sqlite      <- all metadata + annotations
      sensor_data/<cruise>/   <- copied-in Star-Oddi files
      winch_data/<cruise>/    <- copied-in winch logs
      usbl_data/<cruise>/     <- copied-in USBL files

Every data file registered with the app is *copied into* the project folder
and recorded with a path relative to the project root, so the folder can be
zipped/moved/shared as a single self-contained unit.

All datetimes are stored as ISO-8601 strings, naive, in UTC.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

DB_FILENAME = "dredge_data.sqlite"

SUBDIRS = {
    "sensor": "sensor_data",
    "winch": "winch_data",
    "usbl": "usbl_data",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cruises (
    cruise_id     INTEGER PRIMARY KEY,
    cruise_name   TEXT NOT NULL UNIQUE,
    vessel_name   TEXT,
    notes         TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dredges (
    dredge_id       INTEGER PRIMARY KEY,
    cruise_id       INTEGER NOT NULL REFERENCES cruises(cruise_id) ON DELETE CASCADE,
    dredge_name     TEXT NOT NULL,
    start_datetime  TEXT NOT NULL,
    end_datetime    TEXT NOT NULL,
    usbl_distance_m REAL,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE (cruise_id, dredge_name)
);

CREATE TABLE IF NOT EXISTS sensor_files (
    sensor_file_id  INTEGER PRIMARY KEY,
    dredge_id       INTEGER NOT NULL REFERENCES dredges(dredge_id) ON DELETE CASCADE,
    file_name       TEXT NOT NULL,
    rel_path        TEXT NOT NULL,
    sensor_location TEXT,
    sensor_type     TEXT,
    remarks         TEXT
);

CREATE TABLE IF NOT EXISTS winch_files (
    winch_file_id   INTEGER PRIMARY KEY,
    cruise_id       INTEGER NOT NULL REFERENCES cruises(cruise_id) ON DELETE CASCADE,
    file_name       TEXT NOT NULL,
    rel_path        TEXT NOT NULL,
    start_time      TEXT,
    end_time        TEXT,
    settings        TEXT NOT NULL,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS usbl_files (
    usbl_file_id     INTEGER PRIMARY KEY,
    cruise_id        INTEGER NOT NULL REFERENCES cruises(cruise_id) ON DELETE CASCADE,
    file_name        TEXT NOT NULL,
    rel_path         TEXT NOT NULL,
    start_time       TEXT,
    end_time         TEXT,
    sampling_device  TEXT,
    transponder_type TEXT,
    remarks          TEXT
);

CREATE TABLE IF NOT EXISTS annotations (
    annotation_id   INTEGER PRIMARY KEY,
    dredge_id       INTEGER NOT NULL REFERENCES dredges(dredge_id) ON DELETE CASCADE,
    annotation_name TEXT NOT NULL,
    start_datetime  TEXT NOT NULL,
    end_datetime    TEXT NOT NULL,
    start_lat       REAL,
    start_lon       REAL,
    end_lat         REAL,
    end_lon         REAL,
    start_easting   REAL,
    start_northing  REAL,
    end_easting     REAL,
    end_northing    REAL,
    utm_zone        TEXT,
    num_usbl_points INTEGER,
    notes           TEXT,
    UNIQUE (dredge_id, annotation_name)
);
"""


def _iso(dt) -> Optional[str]:
    """Convert a datetime-like to a naive-UTC ISO string (None passes through)."""
    if dt is None or (isinstance(dt, float) and pd.isna(dt)):
        return None
    ts = pd.to_datetime(dt)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.isoformat(sep=" ")


def _num(value) -> Optional[float]:
    """Coerce numpy/pandas numerics to plain float (NaN/None -> None)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _safe_dirname(name: str) -> str:
    """Make a cruise name safe for use as a directory name."""
    return "".join(c if c.isalnum() or c in "-_ ." else "_" for c in name).strip() or "unnamed"


class ProjectStore:
    """Owns the SQLite connection and file layout of one project folder."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        for sub in SUBDIRS.values():
            (self.root / sub).mkdir(exist_ok=True)

        self.db_path = self.root / DB_FILENAME
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self):
        self._conn.close()

    def full_path(self, rel_path: str, file_name: str) -> str:
        return str(self.root / rel_path / file_name)

    # ── cruises ───────────────────────────────────────────────────────

    def add_cruise(self, cruise_name: str, vessel_name: str = None, notes: str = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO cruises (cruise_name, vessel_name, notes) VALUES (?, ?, ?)",
            (cruise_name.strip(), vessel_name or None, notes or None),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_cruise(self, cruise_id: int, cruise_name: str, vessel_name: str = None, notes: str = None):
        self._conn.execute(
            "UPDATE cruises SET cruise_name = ?, vessel_name = ?, notes = ? WHERE cruise_id = ?",
            (cruise_name.strip(), vessel_name or None, notes or None, cruise_id),
        )
        self._conn.commit()

    def delete_cruise(self, cruise_id: int):
        """Delete a cruise, its dredges/files rows, and its copied-in files."""
        for row in self.fetch_winch_files(cruise_id) + self.fetch_usbl_files(cruise_id):
            self._remove_file(row["rel_path"], row["file_name"])
        for dredge in self.fetch_dredges(cruise_id):
            for row in self.fetch_sensor_files(dredge["dredge_id"]):
                self._remove_file(row["rel_path"], row["file_name"])
        self._conn.execute("DELETE FROM cruises WHERE cruise_id = ?", (cruise_id,))
        self._conn.commit()

    def fetch_cruises(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM cruises ORDER BY cruise_name"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── dredges ───────────────────────────────────────────────────────

    def add_dredge(self, cruise_id: int, dredge_name: str, start_datetime, end_datetime,
                   usbl_distance_m: float = None, notes: str = None) -> int:
        cur = self._conn.execute(
            """INSERT INTO dredges
               (cruise_id, dredge_name, start_datetime, end_datetime, usbl_distance_m, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (cruise_id, dredge_name.strip(), _iso(start_datetime), _iso(end_datetime),
             usbl_distance_m, notes or None),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_dredge(self, dredge_id: int, dredge_name: str, start_datetime, end_datetime,
                      usbl_distance_m: float = None, notes: str = None):
        self._conn.execute(
            """UPDATE dredges
               SET dredge_name = ?, start_datetime = ?, end_datetime = ?,
                   usbl_distance_m = ?, notes = ?
               WHERE dredge_id = ?""",
            (dredge_name.strip(), _iso(start_datetime), _iso(end_datetime),
             usbl_distance_m, notes or None, dredge_id),
        )
        self._conn.commit()

    def delete_dredge(self, dredge_id: int):
        for row in self.fetch_sensor_files(dredge_id):
            self._remove_file(row["rel_path"], row["file_name"])
        self._conn.execute("DELETE FROM dredges WHERE dredge_id = ?", (dredge_id,))
        self._conn.commit()

    def fetch_dredges(self, cruise_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM dredges WHERE cruise_id = ? ORDER BY dredge_name",
            (cruise_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_dredge(self, dredge_id: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM dredges WHERE dredge_id = ?", (dredge_id,)
        ).fetchone()
        return dict(row) if row else None

    # ── file copy-in ──────────────────────────────────────────────────

    def _cruise_name(self, cruise_id: int) -> str:
        row = self._conn.execute(
            "SELECT cruise_name FROM cruises WHERE cruise_id = ?", (cruise_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown cruise_id: {cruise_id}")
        return row["cruise_name"]

    def _import_file(self, src_path: str, kind: str, cruise_id: int) -> tuple[str, str]:
        """Copy ``src_path`` into the project and return (file_name, rel_path).

        Files land in ``<kind subdir>/<cruise dirname>/``.  If a file of the
        same name already exists there, a numeric suffix is appended.
        """
        src = Path(src_path)
        if not src.is_file():
            raise FileNotFoundError(f"File not found: {src_path}")

        rel_dir = Path(SUBDIRS[kind]) / _safe_dirname(self._cruise_name(cruise_id))
        dest_dir = self.root / rel_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest = dest_dir / src.name
        stem, suffix = src.stem, src.suffix
        counter = 1
        while dest.exists():
            dest = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        shutil.copy2(src, dest)
        return dest.name, str(rel_dir)

    def _remove_file(self, rel_path: str, file_name: str):
        try:
            target = (self.root / rel_path / file_name).resolve()
            # Never delete anything outside the project folder.
            if self.root.resolve() in target.parents and target.is_file():
                target.unlink()
        except OSError as exc:
            logger.warning("Could not remove file %s/%s: %s", rel_path, file_name, exc)

    # ── sensor files ──────────────────────────────────────────────────

    def add_sensor_file(self, dredge_id: int, src_path: str, sensor_location: str = None,
                        sensor_type: str = None, remarks: str = None) -> int:
        dredge = self.get_dredge(dredge_id)
        if dredge is None:
            raise ValueError(f"Unknown dredge_id: {dredge_id}")
        file_name, rel_path = self._import_file(src_path, "sensor", dredge["cruise_id"])
        cur = self._conn.execute(
            """INSERT INTO sensor_files
               (dredge_id, file_name, rel_path, sensor_location, sensor_type, remarks)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (dredge_id, file_name, rel_path, sensor_location or None,
             sensor_type or None, remarks or None),
        )
        self._conn.commit()
        return cur.lastrowid

    def fetch_sensor_files(self, dredge_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM sensor_files WHERE dredge_id = ? ORDER BY file_name",
            (dredge_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def fetch_sensor_files_for_cruise(self, cruise_id: int) -> list[dict]:
        rows = self._conn.execute(
            """SELECT sf.*, d.dredge_name
               FROM sensor_files sf JOIN dredges d ON sf.dredge_id = d.dredge_id
               WHERE d.cruise_id = ? ORDER BY d.dredge_name, sf.file_name""",
            (cruise_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_sensor_file(self, sensor_file_id: int):
        row = self._conn.execute(
            "SELECT rel_path, file_name FROM sensor_files WHERE sensor_file_id = ?",
            (sensor_file_id,),
        ).fetchone()
        if row:
            self._remove_file(row["rel_path"], row["file_name"])
        self._conn.execute("DELETE FROM sensor_files WHERE sensor_file_id = ?", (sensor_file_id,))
        self._conn.commit()

    # ── winch files ───────────────────────────────────────────────────

    def add_winch_file(self, cruise_id: int, src_path: str, settings: dict,
                       start_time=None, end_time=None, notes: str = None) -> int:
        file_name, rel_path = self._import_file(src_path, "winch", cruise_id)
        cur = self._conn.execute(
            """INSERT INTO winch_files
               (cruise_id, file_name, rel_path, start_time, end_time, settings, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (cruise_id, file_name, rel_path, _iso(start_time), _iso(end_time),
             json.dumps(settings), notes or None),
        )
        self._conn.commit()
        return cur.lastrowid

    def fetch_winch_files(self, cruise_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM winch_files WHERE cruise_id = ? ORDER BY file_name",
            (cruise_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_winch_file(self, winch_file_id: int):
        row = self._conn.execute(
            "SELECT rel_path, file_name FROM winch_files WHERE winch_file_id = ?",
            (winch_file_id,),
        ).fetchone()
        if row:
            self._remove_file(row["rel_path"], row["file_name"])
        self._conn.execute("DELETE FROM winch_files WHERE winch_file_id = ?", (winch_file_id,))
        self._conn.commit()

    # ── USBL files ────────────────────────────────────────────────────

    def add_usbl_file(self, cruise_id: int, src_path: str, start_time=None, end_time=None,
                      sampling_device: str = None, transponder_type: str = None,
                      remarks: str = None) -> int:
        file_name, rel_path = self._import_file(src_path, "usbl", cruise_id)
        cur = self._conn.execute(
            """INSERT INTO usbl_files
               (cruise_id, file_name, rel_path, start_time, end_time,
                sampling_device, transponder_type, remarks)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (cruise_id, file_name, rel_path, _iso(start_time), _iso(end_time),
             sampling_device or None, transponder_type or None, remarks or None),
        )
        self._conn.commit()
        return cur.lastrowid

    def fetch_usbl_files(self, cruise_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM usbl_files WHERE cruise_id = ? ORDER BY file_name",
            (cruise_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_usbl_file(self, usbl_file_id: int):
        row = self._conn.execute(
            "SELECT rel_path, file_name FROM usbl_files WHERE usbl_file_id = ?",
            (usbl_file_id,),
        ).fetchone()
        if row:
            self._remove_file(row["rel_path"], row["file_name"])
        self._conn.execute("DELETE FROM usbl_files WHERE usbl_file_id = ?", (usbl_file_id,))
        self._conn.commit()

    # ── annotations ───────────────────────────────────────────────────

    def fetch_annotations(self, dredge_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM annotations WHERE dredge_id = ? ORDER BY annotation_id",
            (dredge_id,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["start_datetime"] = pd.Timestamp(d["start_datetime"], tz="UTC")
            d["end_datetime"] = pd.Timestamp(d["end_datetime"], tz="UTC")
            result.append(d)
        return result

    def add_annotation(self, dredge_id: int, ann: dict) -> int:
        cur = self._conn.execute(
            """INSERT INTO annotations
               (dredge_id, annotation_name, start_datetime, end_datetime,
                start_lat, start_lon, end_lat, end_lon,
                start_easting, start_northing, end_easting, end_northing,
                utm_zone, num_usbl_points, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (dredge_id, ann["annotation_name"],
             _iso(ann["start_datetime"]), _iso(ann["end_datetime"]),
             _num(ann.get("start_lat")), _num(ann.get("start_lon")),
             _num(ann.get("end_lat")), _num(ann.get("end_lon")),
             _num(ann.get("start_easting")), _num(ann.get("start_northing")),
             _num(ann.get("end_easting")), _num(ann.get("end_northing")),
             ann.get("utm_zone"), int(ann.get("num_usbl_points") or 0), ann.get("notes")),
        )
        self._conn.commit()
        return cur.lastrowid

    def delete_annotation(self, annotation_id: int):
        self._conn.execute("DELETE FROM annotations WHERE annotation_id = ?", (annotation_id,))
        self._conn.commit()

    def clear_annotations(self, dredge_id: int):
        self._conn.execute("DELETE FROM annotations WHERE dredge_id = ?", (dredge_id,))
        self._conn.commit()
