"""
Database loader — loads sensor data directly from the sediment_app
PostgreSQL database, replacing the CSV-export intermediate step.

Uses the same queries and RSK processing as batch_sensor_export.py
to produce SensorData objects identical to those from CSVLoader.

Now that sensor_tool lives inside the sediment_app repository,
database connections and file-path helpers are imported from
db_util and config rather than being duplicated here.
"""
from __future__ import annotations

import io as _io
import os
from typing import Optional

import pandas as pd
import numpy as np
from sqlalchemy import text

from ..domain.models.sensor_data import SensorData

# sediment_app helpers (available because sensor_tool now lives
# in the sediment_app repo alongside these modules)
from db_util import get_connection as _get_connection   # DB connections
from config import get_full_path as _full_path           # file-storage paths


# ---------------------------------------------------------------------------
# RSK / Star-Oddi file processing (mirrors sediment_app/utils.py)
# ---------------------------------------------------------------------------

def _process_rsk(relative_path: str) -> Optional[pd.DataFrame]:
    """Read an RSK file and return a DataFrame with datetime + Depth columns."""
    try:
        from pyrsktools import RSK  # type: ignore
    except ImportError:
        raise ImportError(
            "pyRSKtools is required to load RSK sensor files. "
            "Install it with: pip install pyRSKtools"
        )

    full = _full_path(relative_path)
    if not os.path.exists(full):
        print(f"  ⚠ RSK file not found: {full}")
        return None

    try:
        with RSK(full) as rsk:
            rsk.open()
            rsk.readdata()
            rsk.deriveseapressure()
            rsk.derivedepth(latitude=45.0)
            return pd.DataFrame({
                "datetime": rsk.data["timestamp"],
                "Pressure (dbar)": rsk.data["pressure"],
                "Sea Pressure (dbar)": rsk.data["sea_pressure"],
                "Depth (m)": rsk.data["depth"],
            })
    except Exception as exc:
        print(f"  ⚠ Error processing RSK file {full}: {exc}")
        return None


def _process_star_oddi(relative_path: str) -> Optional[pd.DataFrame]:
    """Read a Star-Oddi .dat or .acc file."""
    full = _full_path(relative_path)
    if not os.path.exists(full):
        print(f"  ⚠ Star-Oddi file not found: {full}")
        return None

    try:
        with open(full, "rb") as fh:
            lines = fh.read().decode("latin1").splitlines()
        data_start = next(i for i, ln in enumerate(lines) if ln and ln[0].isdigit())

        if full.lower().endswith(".acc"):
            colnames = ["rownum", "datetime", "g", "x_acc", "y_acc", "z_acc"]
        else:
            colnames = [
                "index", "datetime", "temp", "press",
                "tilt_x", "tilt_y", "tilt_z", "EAL", "roll",
            ]

        df = pd.read_csv(
            _io.StringIO("\n".join(lines[data_start:])),
            sep="\t", names=colnames, header=None,
            na_values="____", decimal=",",
        )
        df["datetime"] = (
            df["datetime"].astype(str).str.replace(",", ".", regex=False)
        )
        df["datetime"] = pd.to_datetime(
            df["datetime"], format="%d.%m.%Y %H:%M:%S.%f", errors="coerce"
        )

        # Numeric cleanup
        for col in [c for c in df.columns if c not in ("datetime", "index", "rownum")]:
            df[col] = df[col].astype(str).str.replace(",", ".", regex=False)
            df[col] = pd.to_numeric(df[col], errors="coerce")

        if full.lower().endswith(".acc"):
            return pd.DataFrame({
                "datetime": df["datetime"],
                "X_Acceleration": df["x_acc"],
                "Y_Acceleration": df["y_acc"],
                "Z_Acceleration": df["z_acc"],
                "Total_G": df["g"],
            })
        else:
            # Star-Oddi .dat: press column is used directly for depth
            # (same convention as sediment_app/utils.py — Star-Oddi units
            # are already in depth-equivalent values)
            return pd.DataFrame({
                "datetime": df["datetime"],
                "Pressure (dbar)": df["press"],
                "Sea Pressure (dbar)": df["press"],
                "Depth (m)": df["press"],
                "Tilt X": df["tilt_x"],
                "Tilt Y": df["tilt_y"],
                "Tilt Z": df["tilt_z"],
            })
    except Exception as exc:
        print(f"  ⚠ Error processing Star-Oddi file {full}: {exc}")
        return None


def _load_sensor_file(file_id: int) -> tuple[Optional[pd.DataFrame], Optional[object]]:
    """Load a single sensor file by ID — returns (df, sensor_info_row)."""
    with _get_connection() as conn:
        row = conn.execute(
            text("""
                SELECT sf.*, c.core_name
                FROM sensor_files sf
                JOIN cores c ON sf.core_id = c.core_id
                WHERE sf.file_id = :fid
            """),
            {"fid": file_id},
        ).fetchone()

    if row is None:
        return None, None

    relative_path = os.path.join(row.file_path, row.file_name)
    ext = os.path.splitext(row.file_name)[1].lower()
    stype = (row.sensor_type or "").lower()

    if ext == ".rsk" or "rbr" in stype:
        df = _process_rsk(relative_path)
    elif ext in (".dat", ".acc") or "star" in stype:
        df = _process_star_oddi(relative_path)
    else:
        return None, None

    if df is not None and "datetime" not in df.columns:
        if "Timestamp" in df.columns:
            df["datetime"] = df["Timestamp"]

    return df, row


# ---------------------------------------------------------------------------
# Column-filtering helper (mirrors batch_sensor_export.should_include_column)
# ---------------------------------------------------------------------------

# Keywords to match when filtering sensor columns for export
# 'g' matches gravitational acceleration (e.g. "Total_G") from Star-Oddi
_INCLUDE_KEYWORDS = {"depth", "pressure", "acceleration", "g", "tilt"}


def _should_include(col: str) -> bool:
    low = col.lower()
    return any(kw in low for kw in _INCLUDE_KEYWORDS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class DatabaseLoader:
    """Query the sediment_app database and produce SensorData objects."""

    # ── dropdown data ─────────────────────────────────────────────────

    @staticmethod
    def fetch_cruises() -> list[dict]:
        """Return [{cruise_id, cruise_name, vessel_name}, …] for the combo."""
        with _get_connection() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT cr.cruise_id, cr.cruise_name, v.vessel_name
                FROM cruises cr
                LEFT JOIN vessels v ON cr.vessel_id = v.vessel_id
                ORDER BY cr.cruise_name
            """)).fetchall()
        return [
            {"cruise_id": r.cruise_id,
             "cruise_name": r.cruise_name,
             "vessel_name": r.vessel_name or ""}
            for r in rows
        ]

    @staticmethod
    def fetch_cores_for_cruise(cruise_id: int) -> list[dict]:
        """
        Return cores that have sensor files for the given cruise.

        Matches batch_sensor_export logic: core_type_id = 1 (Jumbo Piston)
        with at least one sensor_file.
        """
        with _get_connection() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT
                    c.core_id, c.core_name, ct.core_type_name,
                    c.core_length, c.trigger_core_length,
                    c.trigger_line_length, c.scope,
                    c.pig_weights, w.wire_type
                FROM cores c
                LEFT JOIN core_types ct ON c.core_type_id = ct.core_type_id
                LEFT JOIN sensor_files sf ON c.core_id = sf.core_id
                LEFT JOIN wire w ON c.wire_type_id = w.wire_type_id
                WHERE c.cruise_id = :cid
                  AND c.core_type_id = 1
                  AND sf.file_id IS NOT NULL
                ORDER BY c.core_name
            """), {"cid": cruise_id}).fetchall()

        return [
            {
                "core_id": r.core_id,
                "core_name": r.core_name,
                "core_type_name": r.core_type_name,
                "core_length": r.core_length,
                "trigger_core_length": r.trigger_core_length,
                "trigger_line_length": r.trigger_line_length,
                "scope": r.scope,
                "pig_weights": r.pig_weights,
                "wire_type": r.wire_type,
            }
            for r in rows
        ]

    @staticmethod
    def fetch_cores_for_cruise_all_types(cruise_id: int) -> list[dict]:
        """
        Return all cores with sensor files for the given cruise, regardless
        of core type. Used for calibration cast selection.
        """
        with _get_connection() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT
                    c.core_id, c.core_name, ct.core_type_name,
                    c.core_length, c.trigger_core_length,
                    c.trigger_line_length, c.scope,
                    c.pig_weights, w.wire_type
                FROM cores c
                LEFT JOIN core_types ct ON c.core_type_id = ct.core_type_id
                LEFT JOIN sensor_files sf ON c.core_id = sf.core_id
                LEFT JOIN wire w ON c.wire_type_id = w.wire_type_id
                WHERE c.cruise_id = :cid
                  AND sf.file_id IS NOT NULL
                ORDER BY c.core_name
            """), {"cid": cruise_id}).fetchall()

        return [
            {
                "core_id": r.core_id,
                "core_name": r.core_name,
                "core_type_name": r.core_type_name,
                "core_length": r.core_length,
                "trigger_core_length": r.trigger_core_length,
                "trigger_line_length": r.trigger_line_length,
                "scope": r.scope,
                "pig_weights": r.pig_weights,
                "wire_type": r.wire_type,
            }
            for r in rows
        ]

    # ── full data load ────────────────────────────────────────────────

    @staticmethod
    def load_core_sensor_data(core_id: int, core_info: dict) -> SensorData:
        """
        Load all sensor files for *core_id*, merge on datetime, and
        return a SensorData object with metadata populated from *core_info*.

        Mirrors the logic in batch_sensor_export.create_export_dataframe().
        """
        # 1. Get sensor files for this core
        with _get_connection() as conn:
            sensor_files = conn.execute(text("""
                SELECT file_id, file_name, sensor_type, sensor_location
                FROM sensor_files
                WHERE core_id = :cid
                ORDER BY file_name
            """), {"cid": core_id}).fetchall()

        if not sensor_files:
            raise ValueError(
                f"No sensor files found for core {core_info.get('core_name', core_id)}"
            )

        # 2. Load each file and collect export columns
        export_frames: list[pd.DataFrame] = []

        for sf in sensor_files:
            df, info = _load_sensor_file(sf.file_id)
            if df is None:
                continue

            cols = [c for c in df.columns if c != "datetime" and _should_include(c)]
            if not cols:
                continue

            # Build a column-name prefix like batch_sensor_export does
            loc = sf.sensor_location or ""
            fname = sf.file_name or ""
            prefix = f"{loc}_{fname}" if loc else fname

            for col in cols:
                if col in df.columns and not df[col].isna().all():
                    series_df = df[["datetime", col]].copy()
                    series_df.rename(
                        columns={col: f"{prefix}_{col}"},
                        inplace=True,
                    )
                    export_frames.append(series_df)

        if not export_frames:
            raise ValueError(
                f"No usable sensor data for core "
                f"{core_info.get('core_name', core_id)}"
            )

        # 3. Merge all on datetime (outer join, same as batch export)
        merged = export_frames[0]
        for nxt in export_frames[1:]:
            merged = pd.merge(merged, nxt, on="datetime", how="outer")
        merged.sort_values("datetime", inplace=True)
        merged.reset_index(drop=True, inplace=True)

        # Normalise datetime to datetime64[ns] so that
        # .astype('int64') always yields nanoseconds-since-epoch.
        # pyrsktools returns datetime64[ms] which would otherwise
        # produce wrong epoch values when divided by 1e9.
        merged["datetime"] = merged["datetime"].astype('datetime64[ns]')

        # 4. Build metadata dict (same keys csv_loader.load_export_csv extracts)
        metadata: dict = {}
        if core_info.get("core_type_name"):
            metadata["core_type"] = core_info["core_type_name"]

        for key in ("core_length", "trigger_core_length",
                     "trigger_line_length", "scope"):
            val = core_info.get(key)
            if val is not None:
                try:
                    metadata[key] = float(val)
                except (TypeError, ValueError):
                    pass

        # 5. Detect depth columns in the merged frame
        depth_cols = [c for c in merged.columns if "Depth" in c]
        if not depth_cols:
            raise ValueError(
                "No Depth columns found in merged sensor data for core "
                f"{core_info.get('core_name', core_id)}"
            )

        # 6. Construct SensorData
        return SensorData(
            df=merged,
            datetime_col="datetime",
            depth_columns=depth_cols,
            source_file=f"DB:{core_info.get('core_name', str(core_id))}",
            core_title=core_info.get("core_name", ""),
            metadata=metadata,
        )
