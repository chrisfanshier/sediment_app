"""
Database loader for the dredge app.

Reproduces the concatenation/merge pipeline from
``sediment_app/usbl_sensor_winch_export.py`` (the ``vm-deploy`` Streamlit
"Export Dredge Sensor + USBL + Winch Data" tool) but returns in-memory
DataFrames for the desktop dredge app instead of writing CSVs.

For a selected cruise + dredge it produces:
    * ``usbl_df``   — concatenated USBL fixes (lat/lon, beacon, error ellipse)
    * ``sensor_df`` — Star-Oddi sensor data outer-merged with winch data on
                      ``datetime`` (the high-frequency time series)
both truncated to the dredge deployment window and returned as timezone-aware
UTC frames so the viewer's existing logic works unchanged.

Database access and file-path resolution reuse the sediment_app helpers
(``db_util.get_connection`` and ``config.get_full_path``), matching the pattern
already established by ``sensor_tool/persistence/database_loader.py``.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

import pandas as pd
from sqlalchemy import text

# sediment_app helpers — available because dredge_app lives inside the repo.
from db_util import get_connection as _get_connection
from config import get_full_path as _full_path

from . import file_parsers as fp

logger = logging.getLogger(__name__)


class DredgeDataset:
    """Container for a loaded dredge deployment."""

    def __init__(
        self,
        usbl_df: Optional[pd.DataFrame],
        sensor_df: Optional[pd.DataFrame],
        core_name: str,
        start_datetime: Optional[pd.Timestamp],
        end_datetime: Optional[pd.Timestamp],
    ):
        self.usbl_df = usbl_df
        self.sensor_df = sensor_df
        self.core_name = core_name
        self.start_datetime = start_datetime
        self.end_datetime = end_datetime


class DredgeDatabaseLoader:
    """Query the sediment_app database and build dredge datasets."""

    # ── dropdown data ─────────────────────────────────────────────────

    @staticmethod
    def fetch_cruises() -> list[dict]:
        """Return cruises that have at least one dredge *and* USBL data.

        (Answer #2: only show cruises with dredges that have USBL data.)
        """
        with _get_connection() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT cr.cruise_id, cr.cruise_name
                FROM cruises cr
                JOIN cores c
                  ON c.cruise_id = cr.cruise_id
                 AND c.core_dredge = 'dredge'
                JOIN usbl_files uf
                  ON uf.cruise_id = cr.cruise_id
                ORDER BY cr.cruise_name
            """)).fetchall()
        return [{"cruise_id": r.cruise_id, "cruise_name": r.cruise_name} for r in rows]

    @staticmethod
    def fetch_dredges(cruise_id: int) -> list[dict]:
        """Return dredge cores for a cruise (Answer #1: filter for dredge)."""
        with _get_connection() as conn:
            rows = conn.execute(text("""
                SELECT core_id, core_name, date, time_launched, time_recovered,
                       latitude, longitude
                FROM cores
                WHERE cruise_id = :cid
                  AND core_dredge = 'dredge'
                ORDER BY core_name
            """), {"cid": cruise_id}).fetchall()
        return [
            {
                "core_id": r.core_id,
                "core_name": r.core_name,
                "date": r.date,
                "time_launched": r.time_launched,
                "time_recovered": r.time_recovered,
                "latitude": r.latitude,
                "longitude": r.longitude,
            }
            for r in rows
        ]

    # ── deployment window ─────────────────────────────────────────────

    @staticmethod
    def _deployment_window(core: dict) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Compute the (naive UTC) deployment window with midnight rollover.

        Mirrors ``usbl_sensor_winch_export.py``:
            start = date + time_launched
            end   = date + time_recovered
            if end < start: end += 1 day   (rollover past midnight)
        """
        date = core.get("date")
        launched = core.get("time_launched")
        recovered = core.get("time_recovered")
        if date is None or launched is None or recovered is None:
            raise ValueError(
                "Dredge is missing required date / time_launched / time_recovered "
                "values, so the deployment window cannot be determined."
            )

        start = pd.to_datetime(date) + pd.to_timedelta(str(launched))
        end = pd.to_datetime(date) + pd.to_timedelta(str(recovered))
        if end < start:
            end += pd.Timedelta(days=1)
        return start, end

    # ── per-source loading ────────────────────────────────────────────

    @staticmethod
    def _load_sensors(core_id: int) -> Optional[pd.DataFrame]:
        """Load + outer-merge all Star-Oddi sensor files for the core."""
        with _get_connection() as conn:
            sensor_files = conn.execute(text("""
                SELECT file_id, file_name, file_path, sensor_type
                FROM sensor_files
                WHERE core_id = :cid
                ORDER BY sensor_type, file_name
            """), {"cid": core_id}).fetchall()

        if not sensor_files:
            return None

        frames: list[pd.DataFrame] = []
        for row in sensor_files:
            if not row.file_path:
                logger.warning("Sensor file %s has no file_path; skipping", row.file_name)
                continue
            full = _full_path(os.path.join(row.file_path, row.file_name))
            df = fp.process_star_oddi_data(full)
            if df is None:
                continue
            df = _strip_tz(df)
            frames.append(df)

        if not frames:
            return None

        merged = frames[0].copy()
        for i, nxt in enumerate(frames[1:], start=1):
            merged = pd.merge(merged, nxt, on="datetime", how="outer", suffixes=("", f"_{i}"))
        merged = merged.sort_values("datetime").reset_index(drop=True)
        return merged

    @staticmethod
    def _load_usbl(cruise_id: int, start, end) -> Optional[pd.DataFrame]:
        """Load USBL files for the cruise that overlap the deployment window."""
        with _get_connection() as conn:
            usbl_files = pd.read_sql(
                text("""
                    SELECT usbl_file_id, file_name, file_path, start_time, end_time
                    FROM usbl_files
                    WHERE cruise_id = :cid
                """),
                conn,
                params={"cid": cruise_id},
            )
        if usbl_files.empty:
            return None

        matched = _filter_by_overlap(usbl_files, start, end)
        frames: list[pd.DataFrame] = []
        for _, row in matched.iterrows():
            if not row["file_path"]:
                logger.warning("USBL file %s has no file_path; skipping", row["file_name"])
                continue
            full = _full_path(os.path.join(row["file_path"], row["file_name"]))
            df = fp.load_usbl_file(full)
            if df is None:
                continue
            df = _strip_tz(df)
            frames.append(df)

        if not frames:
            return None

        combined = pd.concat(frames, ignore_index=True)
        combined = combined.sort_values("datetime").reset_index(drop=True)
        combined = combined.drop_duplicates(subset=["datetime"], keep="first")
        return combined

    @staticmethod
    def _load_winch(cruise_id: int, start, end) -> Optional[pd.DataFrame]:
        """Load winch files for the cruise that overlap the deployment window."""
        with _get_connection() as conn:
            winch_files = pd.read_sql(
                text("""
                    SELECT winch_file_id, file_name, file_path, start_time, end_time, settings
                    FROM winch_data
                    WHERE cruise_id = :cid
                """),
                conn,
                params={"cid": cruise_id},
            )
        if winch_files.empty:
            return None

        matched = _filter_by_overlap(winch_files, start, end)
        frames: list[pd.DataFrame] = []
        for _, row in matched.iterrows():
            if not row["file_path"]:
                logger.warning("Winch file %s has no file_path; skipping", row["file_name"])
                continue
            full = _full_path(os.path.join(row["file_path"], row["file_name"]))
            try:
                settings = json.loads(row["settings"]) if row["settings"] else {}
            except (TypeError, ValueError) as exc:
                logger.error("Bad winch settings JSON for %s: %s", row["file_name"], exc)
                continue
            df = fp.parse_winch_dat(full, settings)
            if df is None or "datetime" not in df.columns:
                continue
            df = _strip_tz(df)
            frames.append(df)

        if not frames:
            return None

        combined = pd.concat(frames, ignore_index=True)
        combined = combined.sort_values("datetime").reset_index(drop=True)
        combined = combined.drop_duplicates(subset=["datetime"], keep="first")
        return combined

    # ── full load ─────────────────────────────────────────────────────

    @staticmethod
    def load_dredge_dataset(cruise_id: int, core: dict) -> DredgeDataset:
        """Load and assemble the full dataset for a dredge deployment.

        Returns a :class:`DredgeDataset` with timezone-aware (UTC) frames.
        """
        core_name = core.get("core_name", str(core.get("core_id", "")))
        start, end = DredgeDatabaseLoader._deployment_window(core)

        combined_sensors = DredgeDatabaseLoader._load_sensors(core["core_id"])
        combined_usbl = DredgeDatabaseLoader._load_usbl(cruise_id, start, end)
        combined_winch = DredgeDatabaseLoader._load_winch(cruise_id, start, end)

        # The viewer's "sensor" time series = Star-Oddi merged with winch on datetime.
        sensor_df = _outer_merge_on_datetime(
            [df for df in (combined_sensors, combined_winch) if df is not None]
        )

        usbl_df = combined_usbl

        # Truncate both to the deployment window (matches the export tool).
        if sensor_df is not None:
            sensor_df = _truncate(sensor_df, start, end)
        if usbl_df is not None:
            usbl_df = _truncate(usbl_df, start, end)
            # Provide plain latitude/longitude aliases so annotation metadata
            # (which looks for 'latitude'/'longitude') is populated.
            if "latitude" not in usbl_df.columns and "latitude_deg" in usbl_df.columns:
                usbl_df["latitude"] = usbl_df["latitude_deg"]
            if "longitude" not in usbl_df.columns and "longitude_deg" in usbl_df.columns:
                usbl_df["longitude"] = usbl_df["longitude_deg"]

        # Localize to UTC so the viewer's tz-aware comparisons work unchanged.
        usbl_df = _localize_utc(usbl_df)
        sensor_df = _localize_utc(sensor_df)

        return DredgeDataset(
            usbl_df=usbl_df,
            sensor_df=sensor_df,
            core_name=core_name,
            start_datetime=pd.Timestamp(start, tz="UTC"),
            end_datetime=pd.Timestamp(end, tz="UTC"),
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _strip_tz(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure ``datetime`` is a tz-naive column (drop index if needed)."""
    if "datetime" not in df.columns and df.index.name == "datetime":
        df = df.reset_index()
    if "datetime" in df.columns and pd.api.types.is_datetime64_any_dtype(df["datetime"]):
        if getattr(df["datetime"].dt, "tz", None) is not None:
            df = df.copy()
            df["datetime"] = df["datetime"].dt.tz_localize(None)
    return df


def _filter_by_overlap(files: pd.DataFrame, start, end) -> pd.DataFrame:
    """Filter a files DataFrame to rows whose [start_time, end_time] overlaps
    the deployment window.  ``start_time`` / ``end_time`` may be text or
    timestamps; they are coerced to tz-naive datetimes.
    """
    files = files.copy()
    files["start_time"] = pd.to_datetime(files["start_time"], errors="coerce", utc=True).dt.tz_localize(None)
    files["end_time"] = pd.to_datetime(files["end_time"], errors="coerce", utc=True).dt.tz_localize(None)
    mask = (files["start_time"] <= end) & (files["end_time"] >= start)
    return files[mask]


def _outer_merge_on_datetime(frames: list[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Outer-merge frames on ``datetime`` (no interpolation)."""
    frames = [f for f in frames if f is not None and "datetime" in f.columns]
    if not frames:
        return None
    merged = frames[0].copy()
    for nxt in frames[1:]:
        merged = pd.merge(merged, nxt, on="datetime", how="outer", suffixes=("", "_other"))
    merged = merged.sort_values("datetime").reset_index(drop=True)
    return merged


def _truncate(df: pd.DataFrame, start, end) -> pd.DataFrame:
    """Keep only rows within [start, end] (naive bounds)."""
    if df is None or "datetime" not in df.columns:
        return df
    mask = (df["datetime"] >= start) & (df["datetime"] <= end)
    return df[mask].reset_index(drop=True)


def _localize_utc(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Localize a tz-naive ``datetime`` column to UTC (tz-aware)."""
    if df is None or "datetime" not in df.columns:
        return df
    if pd.api.types.is_datetime64_any_dtype(df["datetime"]):
        if getattr(df["datetime"].dt, "tz", None) is None:
            df = df.copy()
            df["datetime"] = df["datetime"].dt.tz_localize("UTC")
    return df
