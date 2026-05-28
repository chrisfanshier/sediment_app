"""
RecoilLoader — database queries for the recoil fitting tool.

Fetches analysis results and raw RSK sensor data needed for fitting.
Mirrors patterns from sensor_tool/persistence/database_loader.py.
"""
from __future__ import annotations

import io
import os
import sys
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from db_util import get_connection       # noqa: E402
from config import get_full_path         # noqa: E402


# ---------------------------------------------------------------------------
# Internal: file parsing (mirrors sensor_tool/persistence/database_loader.py)
# ---------------------------------------------------------------------------

def _process_rsk(relative_path: str) -> Optional[pd.DataFrame]:
    """Load an RSK file and return a DataFrame with 'datetime' and 'Depth (m)'."""
    try:
        from pyrsktools import RSK  # type: ignore
    except ImportError:
        raise ImportError("pyrsktools is required: pip install pyrsktools")

    full = get_full_path(relative_path)
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
                "Depth (m)": rsk.data["depth"],
            })
    except Exception as exc:
        print(f"  ⚠ Error loading RSK {full}: {exc}")
        return None


def _process_star_oddi(relative_path: str) -> Optional[pd.DataFrame]:
    """Load a Star-Oddi .dat file and return a DataFrame with 'datetime' and 'Depth (m)'."""
    full = get_full_path(relative_path)
    if not os.path.exists(full):
        print(f"  ⚠ Star-Oddi file not found: {full}")
        return None

    if full.lower().endswith(".acc"):
        print(f"  ⚠ Star-Oddi .acc (acceleration) files have no depth data — cannot use as Release Device: {full}")
        return None

    try:
        with open(full, "rb") as fh:
            lines = fh.read().decode("latin1").splitlines()
        data_start = next(i for i, ln in enumerate(lines) if ln and ln[0].isdigit())

        colnames = [
            "index", "datetime", "temp", "press",
            "tilt_x", "tilt_y", "tilt_z", "EAL", "roll",
        ]
        df = pd.read_csv(
            io.StringIO("\n".join(lines[data_start:])),
            sep="\t", names=colnames, header=None,
            na_values="____", decimal=",",
        )
        df["datetime"] = df["datetime"].astype(str).str.replace(",", ".", regex=False)
        df["datetime"] = pd.to_datetime(
            df["datetime"], format="%d.%m.%Y %H:%M:%S.%f", errors="coerce"
        )
        for col in [c for c in df.columns if c not in ("datetime", "index")]:
            df[col] = df[col].astype(str).str.replace(",", ".", regex=False)
            df[col] = pd.to_numeric(df[col], errors="coerce")

        return pd.DataFrame({
            "datetime": df["datetime"],
            "Depth (m)": df["press"],  # Star-Oddi press column is depth-equivalent
        })
    except Exception as exc:
        print(f"  ⚠ Error loading Star-Oddi {full}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class RecoilLoader:
    """Queries the sediment_app database for recoil tool inputs."""

    # ── Dropdowns ──────────────────────────────────────────────────────────

    @staticmethod
    def fetch_cruises() -> list[dict]:
        """Return [{cruise_id, cruise_name, vessel_name}, …] for the toolbar combo."""
        with get_connection() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT cr.cruise_id, cr.cruise_name, v.vessel_name
                FROM cruises cr
                LEFT JOIN vessels v ON cr.vessel_id = v.vessel_id
                ORDER BY cr.cruise_name
            """)).fetchall()
        return [
            {
                "cruise_id": r.cruise_id,
                "cruise_name": r.cruise_name,
                "vessel_name": r.vessel_name or "",
            }
            for r in rows
        ]

    @staticmethod
    def fetch_cores_with_results(cruise_id: int) -> list[dict]:
        """
        Return cores that have:
          - at least one sensor_analysis_results row with trip_index NOT NULL
          - at least one sensor_files row with sensor_location = 'Release Device'

        Includes pig_weights and wire_type for pre-populating the deployment form.
        """
        with get_connection() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT
                    c.core_id,
                    c.core_name,
                    c.pig_weights,
                    w.wire_type,
                    (
                        SELECT sar.result_seafloor
                        FROM sensor_analysis_results sar
                        WHERE sar.core_id = c.core_id
                          AND sar.trip_index IS NOT NULL
                        ORDER BY sar.analyzed_at DESC
                        LIMIT 1
                    ) AS result_seafloor
                FROM cores c
                LEFT JOIN wire w ON c.wire_type_id = w.wire_type_id
                WHERE c.cruise_id = :cid
                  AND EXISTS (
                      SELECT 1 FROM sensor_analysis_results sar
                      WHERE sar.core_id = c.core_id
                        AND sar.trip_index IS NOT NULL
                  )
                  AND EXISTS (
                      SELECT 1 FROM sensor_files sf
                      WHERE sf.core_id = c.core_id
                        AND sf.sensor_location = 'Release Device'
                  )
                ORDER BY c.core_name
            """), {"cid": cruise_id}).fetchall()

        return [
            {
                "core_id": r.core_id,
                "core_name": r.core_name,
                "pig_weights": r.pig_weights,
                "wire_type": r.wire_type or "",
                "result_seafloor": r.result_seafloor,
            }
            for r in rows
        ]

    # ── Analysis result ────────────────────────────────────────────────────

    @staticmethod
    def load_analysis_result(core_id: int) -> Optional[dict]:
        """
        Fetch the most recent sensor_analysis_results row for core_id
        that has a trip_index.  Returns a plain dict, or None if not found.
        """
        with get_connection() as conn:
            row = conn.execute(text("""
                SELECT *
                FROM sensor_analysis_results
                WHERE core_id = :cid
                  AND trip_index IS NOT NULL
                ORDER BY analyzed_at DESC
                LIMIT 1
            """), {"cid": core_id}).fetchone()

        if row is None:
            return None
        return dict(row._mapping)

    # ── Sensor data ────────────────────────────────────────────────────────

    @staticmethod
    def load_release_device_data(
        core_id: int,
    ) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Load the raw Release Device RSK for core_id.

        Returns
        -------
        (time_s, depth_m)
            time_s : float64 array, seconds from first sample
            depth_m : float64 array, depth in metres (positive downward)
            Both are None on failure.
        """
        with get_connection() as conn:
            row = conn.execute(text("""
                SELECT file_path, file_name, sensor_type
                FROM sensor_files
                WHERE core_id = :cid
                  AND sensor_location = 'Release Device'
                ORDER BY file_name
                LIMIT 1
            """), {"cid": core_id}).fetchone()

        if row is None:
            print(f"  ⚠ No Release Device sensor file found for core {core_id}")
            return None, None

        relative_path = os.path.join(row.file_path, row.file_name)
        ext = os.path.splitext(row.file_name)[1].lower()
        stype = (row.sensor_type or "").lower()

        if ext == ".rsk" or "rbr" in stype:
            df = _process_rsk(relative_path)
        elif ext in (".dat", ".acc") or "star" in stype:
            df = _process_star_oddi(relative_path)
        else:
            print(f"  ⚠ Unrecognised sensor type/extension for Release Device: {row.file_name} (sensor_type={row.sensor_type!r})")
            return None, None

        if df is None:
            return None, None

        if "Depth (m)" not in df.columns:
            print(f"  ⚠ No 'Depth (m)' column in Release Device data for core {core_id}")
            return None, None

        # Use absolute Unix epoch seconds so DateAxisItem renders correct UTC times.
        # Cast to datetime64[ns] first (pyrsktools returns datetime64[ms] which
        # would produce wrong epoch values if divided by 1e9 without the cast).
        datetimes = pd.to_datetime(df["datetime"]).values.astype("datetime64[ns]")
        time_s = datetimes.view("int64") / 1e9
        depth_m = df["Depth (m)"].values.astype(np.float64)

        return time_s, depth_m
