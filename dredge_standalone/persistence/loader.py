"""Dataset assembly for the standalone dredge app.

Ports the concatenation/merge pipeline of the database-integrated
``dredge_app/persistence/database_loader.py`` onto the SQLite
:class:`~dredge_standalone.persistence.project.ProjectStore`:

for a selected dredge it produces
    * ``usbl_df``   — concatenated USBL fixes overlapping the deployment window
    * ``sensor_df`` — Star-Oddi sensor data outer-merged with winch data on
                      ``datetime``
both truncated to the deployment window and returned timezone-aware (UTC).

Winch and USBL files are pooled per cruise and matched to the dredge by time
overlap; sensor files are explicitly assigned to the dredge.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import pandas as pd

from . import file_parsers as fp
from .project import ProjectStore

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


class ProjectDataLoader:
    """Build dredge datasets from a :class:`ProjectStore`."""

    def __init__(self, store: ProjectStore):
        self.store = store

    # ── per-source loading ────────────────────────────────────────────

    def _load_sensors(self, dredge_id: int) -> Optional[pd.DataFrame]:
        """Load + outer-merge all Star-Oddi sensor files for the dredge."""
        frames: list[pd.DataFrame] = []
        for row in self.store.fetch_sensor_files(dredge_id):
            full = self.store.full_path(row["rel_path"], row["file_name"])
            df = fp.process_star_oddi_data(full)
            if df is None:
                continue
            frames.append(_strip_tz(df))

        if not frames:
            return None

        merged = frames[0].copy()
        for i, nxt in enumerate(frames[1:], start=1):
            merged = pd.merge(merged, nxt, on="datetime", how="outer", suffixes=("", f"_{i}"))
        return merged.sort_values("datetime").reset_index(drop=True)

    def _load_usbl(self, cruise_id: int, start, end) -> Optional[pd.DataFrame]:
        """Load the cruise's USBL files that overlap the deployment window."""
        files = pd.DataFrame(self.store.fetch_usbl_files(cruise_id))
        if files.empty:
            return None

        frames: list[pd.DataFrame] = []
        for _, row in _filter_by_overlap(files, start, end).iterrows():
            full = self.store.full_path(row["rel_path"], row["file_name"])
            df = fp.load_usbl_file(full)
            if df is None:
                continue
            frames.append(_strip_tz(df))

        if not frames:
            return None

        combined = pd.concat(frames, ignore_index=True)
        combined = combined.sort_values("datetime").reset_index(drop=True)
        return combined.drop_duplicates(subset=["datetime"], keep="first")

    def _load_winch(self, cruise_id: int, start, end) -> Optional[pd.DataFrame]:
        """Load the cruise's winch files that overlap the deployment window."""
        files = pd.DataFrame(self.store.fetch_winch_files(cruise_id))
        if files.empty:
            return None

        frames: list[pd.DataFrame] = []
        for _, row in _filter_by_overlap(files, start, end).iterrows():
            full = self.store.full_path(row["rel_path"], row["file_name"])
            try:
                settings = json.loads(row["settings"]) if row["settings"] else {}
            except (TypeError, ValueError) as exc:
                logger.error("Bad winch settings JSON for %s: %s", row["file_name"], exc)
                continue
            df = fp.parse_winch_dat(full, settings)
            if df is None or "datetime" not in df.columns:
                continue
            frames.append(_strip_tz(df))

        if not frames:
            return None

        combined = pd.concat(frames, ignore_index=True)
        combined = combined.sort_values("datetime").reset_index(drop=True)
        return combined.drop_duplicates(subset=["datetime"], keep="first")

    # ── full load ─────────────────────────────────────────────────────

    def load_dredge_dataset(self, dredge: dict) -> DredgeDataset:
        """Load and assemble the full dataset for a dredge deployment.

        ``dredge`` is a row dict from :meth:`ProjectStore.fetch_dredges`.
        Returns a :class:`DredgeDataset` with timezone-aware (UTC) frames.
        """
        core_name = dredge["dredge_name"]
        start = pd.Timestamp(dredge["start_datetime"])
        end = pd.Timestamp(dredge["end_datetime"])
        if pd.isna(start) or pd.isna(end):
            raise ValueError(
                f"Dredge '{core_name}' is missing start/end datetimes, so the "
                "deployment window cannot be determined."
            )

        cruise_id = dredge["cruise_id"]
        combined_sensors = self._load_sensors(dredge["dredge_id"])
        combined_usbl = self._load_usbl(cruise_id, start, end)
        combined_winch = self._load_winch(cruise_id, start, end)

        # The viewer's "sensor" time series = Star-Oddi merged with winch.
        sensor_df = _outer_merge_on_datetime(
            [df for df in (combined_sensors, combined_winch) if df is not None]
        )
        usbl_df = combined_usbl

        if sensor_df is not None:
            sensor_df = _truncate(sensor_df, start, end)
        if usbl_df is not None:
            usbl_df = _truncate(usbl_df, start, end)
            # Plain latitude/longitude aliases so annotation metadata is populated.
            if "latitude" not in usbl_df.columns and "latitude_deg" in usbl_df.columns:
                usbl_df["latitude"] = usbl_df["latitude_deg"]
            if "longitude" not in usbl_df.columns and "longitude_deg" in usbl_df.columns:
                usbl_df["longitude"] = usbl_df["longitude_deg"]

        return DredgeDataset(
            usbl_df=_localize_utc(usbl_df),
            sensor_df=_localize_utc(sensor_df),
            core_name=core_name,
            start_datetime=pd.Timestamp(start, tz="UTC"),
            end_datetime=pd.Timestamp(end, tz="UTC"),
        )


# ---------------------------------------------------------------------------
# helpers (identical to the database-integrated loader)
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
    """Keep rows whose [start_time, end_time] overlaps the deployment window."""
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
    return merged.sort_values("datetime").reset_index(drop=True)


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
