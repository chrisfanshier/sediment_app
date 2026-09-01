"""Minimal pure-Python GeoPackage writer for point layers.

Replaces the geopandas / shapely / fiona stack for the app's only spatial
export (annotated USBL fixes as a point layer).  A GeoPackage is a SQLite
database with a small set of metadata tables defined by the OGC GeoPackage
specification, and point geometries are trivial WKB blobs — so the standard
library ``sqlite3`` module plus ``pyproj`` (for the CRS definition, already a
core dependency) is all that's needed.

Motivation: GDAL-based libraries are the classic blocker for bundling this
app into a single executable (missing shared libraries / data files under
PyInstaller).  With this writer the app has no GDAL dependency at all.

Spec reference: OGC 12-128r19 (GeoPackage 1.3), requirements 1-32
(core + features).  Only what is needed for a 2D point feature layer is
implemented.
"""
from __future__ import annotations

import sqlite3
import struct
from datetime import datetime, timezone

import pandas as pd
from pyproj import CRS

_GPKG_APPLICATION_ID = 0x47504B47  # "GPKG"
_GPKG_USER_VERSION = 10301         # GeoPackage 1.3.1


def _gpkg_point_blob(x: float, y: float, srs_id: int) -> bytes:
    """Encode one XY point as a GeoPackage geometry blob.

    Header: magic "GP", version 0, flags 0x01 (little-endian, no envelope),
    srs_id int32 — followed by standard WKB for a 2D point.
    """
    header = b"GP" + bytes([0, 0x01]) + struct.pack("<i", srs_id)
    wkb = struct.pack("<BIdd", 1, 1, x, y)  # little-endian, type 1 = Point
    return header + wkb


def _column_type(series: pd.Series) -> str:
    """Map a pandas dtype to a GeoPackage/SQLite column type."""
    if pd.api.types.is_bool_dtype(series):
        return "BOOLEAN"
    if pd.api.types.is_integer_dtype(series):
        return "INTEGER"
    if pd.api.types.is_float_dtype(series):
        return "REAL"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "DATETIME"
    return "TEXT"


def _to_sqlite_value(value, col_type: str):
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NaT:
        return None
    if col_type == "BOOLEAN":
        return int(bool(value))
    if col_type == "INTEGER":
        return int(value)
    if col_type == "REAL":
        return float(value)
    if col_type == "DATETIME":
        ts = pd.Timestamp(value)
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        # GeoPackage requires ISO-8601 'YYYY-MM-DDTHH:MM:SS.SSSZ'
        return ts.isoformat(sep="T", timespec="milliseconds") + "Z"
    return str(value)


def write_gpkg_points(
    df: pd.DataFrame,
    path: str,
    layer: str = "points",
    epsg: int = 4326,
    x_col: str = "easting",
    y_col: str = "northing",
) -> int:
    """Write ``df`` to ``path`` as a GeoPackage with one point layer.

    Point geometry comes from ``x_col``/``y_col`` (in the CRS given by
    ``epsg``); all other columns become feature attributes.  Returns the
    number of features written.  An existing file at ``path`` is replaced.
    """
    if x_col not in df.columns or y_col not in df.columns:
        raise ValueError(f"DataFrame must contain '{x_col}' and '{y_col}' columns")

    crs = CRS.from_epsg(epsg)
    srs_wkt = crs.to_wkt()
    srs_name = crs.name

    attr_cols = [c for c in df.columns if c not in (x_col, y_col)]
    col_types = {c: _column_type(df[c]) for c in attr_cols}

    import os
    if os.path.exists(path):
        os.remove(path)

    conn = sqlite3.connect(path)
    try:
        conn.execute(f"PRAGMA application_id = {_GPKG_APPLICATION_ID}")
        conn.execute(f"PRAGMA user_version = {_GPKG_USER_VERSION}")

        conn.execute("""
            CREATE TABLE gpkg_spatial_ref_sys (
                srs_name TEXT NOT NULL,
                srs_id INTEGER NOT NULL PRIMARY KEY,
                organization TEXT NOT NULL,
                organization_coordsys_id INTEGER NOT NULL,
                definition TEXT NOT NULL,
                description TEXT
            )""")
        conn.executemany(
            "INSERT INTO gpkg_spatial_ref_sys VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("Undefined Cartesian SRS", -1, "NONE", -1, "undefined",
                 "undefined cartesian coordinate reference system"),
                ("Undefined Geographic SRS", 0, "NONE", 0, "undefined",
                 "undefined geographic coordinate reference system"),
                (srs_name, epsg, "EPSG", epsg, srs_wkt, None),
            ],
        )

        conn.execute("""
            CREATE TABLE gpkg_contents (
                table_name TEXT NOT NULL PRIMARY KEY,
                data_type TEXT NOT NULL,
                identifier TEXT UNIQUE,
                description TEXT DEFAULT '',
                last_change DATETIME NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE,
                srs_id INTEGER,
                CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id)
                    REFERENCES gpkg_spatial_ref_sys(srs_id)
            )""")

        conn.execute("""
            CREATE TABLE gpkg_geometry_columns (
                table_name TEXT NOT NULL,
                column_name TEXT NOT NULL,
                geometry_type_name TEXT NOT NULL,
                srs_id INTEGER NOT NULL,
                z TINYINT NOT NULL,
                m TINYINT NOT NULL,
                CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
                CONSTRAINT fk_gc_tn FOREIGN KEY (table_name)
                    REFERENCES gpkg_contents(table_name),
                CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id)
                    REFERENCES gpkg_spatial_ref_sys(srs_id)
            )""")

        col_defs = ", ".join(f'"{c}" {col_types[c]}' for c in attr_cols)
        conn.execute(
            f'CREATE TABLE "{layer}" ('
            f"fid INTEGER PRIMARY KEY AUTOINCREMENT, "
            f"geom POINT"
            + (f", {col_defs}" if col_defs else "")
            + ")"
        )

        xs = df[x_col].astype(float)
        ys = df[y_col].astype(float)

        placeholders = ", ".join(["?"] * (1 + len(attr_cols)))
        quoted_attrs = ", ".join(f'"{c}"' for c in attr_cols)
        insert_sql = (
            f'INSERT INTO "{layer}" (geom'
            + (f", {quoted_attrs}" if attr_cols else "")
            + f") VALUES ({placeholders})"
        )

        rows = []
        for i in range(len(df)):
            row = df.iloc[i]
            values = [_gpkg_point_blob(xs.iloc[i], ys.iloc[i], epsg)]
            for c in attr_cols:
                values.append(_to_sqlite_value(row[c], col_types[c]))
            rows.append(values)
        conn.executemany(insert_sql, rows)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        conn.execute(
            "INSERT INTO gpkg_contents "
            "(table_name, data_type, identifier, description, last_change, "
            " min_x, min_y, max_x, max_y, srs_id) "
            "VALUES (?, 'features', ?, ?, ?, ?, ?, ?, ?, ?)",
            (layer, layer, "Exported by Dragognosificator", now,
             float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()),
             epsg),
        )
        conn.execute(
            "INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', 'POINT', ?, 0, 0)",
            (layer, epsg),
        )

        conn.commit()
        return len(df)
    finally:
        conn.close()
