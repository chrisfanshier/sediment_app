"""Map ship-side PostgreSQL rows to standalone SQLite project records."""
from __future__ import annotations

import json
import math
import os
from typing import Any, Optional

import pandas as pd

# Flat columns shared by sensor_analysis_results (Postgres) and
# analysis_results (SQLite). Sync/provenance columns are dropped.
ANALYSIS_FLAT_COLUMNS = (
    "trip_index", "trip_datetime", "start_core_index", "start_core_datetime",
    "result_recoil_max", "result_recoil_time_s", "result_fall_dist", "result_suck_in",
    "result_recoil_start", "result_freefall_start", "result_piston_suck",
    "result_seafloor", "result_piston_alt", "result_pen_deficit", "result_freefall_est",
    "result_eff_trig_line", "trigger_pen_m", "winch_trip_index", "winch_trip_datetime",
    "winch_time_offset_sec",
)


def row_mapping(row) -> dict[str, Any]:
    """Normalise a SQLAlchemy row to a plain dict."""
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


def pg_file_path(file_path: str, file_name: str, file_root: str) -> str:
    """Absolute path to a sensor or winch file on disk."""
    return os.path.join(file_root, file_path, file_name)


def _combine_date_time(date_val, time_val) -> Optional[pd.Timestamp]:
    if date_val is None or time_val is None:
        return None
    day = pd.to_datetime(date_val, errors="coerce")
    if pd.isna(day):
        return None
    day = day.normalize()

    if isinstance(time_val, str):
        td = pd.to_timedelta(time_val, errors="coerce")
        if pd.isna(td):
            parts = str(time_val).strip().split(":")
            try:
                h, m = int(parts[0]), int(parts[1])
                s = float(parts[2]) if len(parts) > 2 else 0.0
                td = pd.Timedelta(hours=h, minutes=m, seconds=s)
            except (ValueError, IndexError):
                return None
    else:
        td = pd.to_timedelta(time_val, errors="coerce")
        if pd.isna(td):
            return None

    return day + td


def deployment_datetimes(core_row: dict) -> tuple[Optional[Any], Optional[Any]]:
    """Build standalone start/end datetimes from a postgres ``cores`` row."""
    date_val = core_row.get("date") or core_row.get("core_date")
    launch = (
        core_row.get("time_launched")
        or core_row.get("time_launch")
        or core_row.get("time_launched_utc")
    )
    recover = (
        core_row.get("time_recovered")
        or core_row.get("time_recover")
        or core_row.get("time_recovered_utc")
    )
    start = _combine_date_time(date_val, launch)
    end = _combine_date_time(date_val, recover)
    if start is not None and end is not None and end < start:
        end += pd.Timedelta(days=1)
    return start, end


def _clean_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(f) or pd.isna(f) else f


def analysis_row_to_sqlite(row: dict) -> tuple[dict, Optional[dict]]:
    """Split a postgres analysis row into flat_data and params_section."""
    flat: dict = {}
    for key in ANALYSIS_FLAT_COLUMNS:
        if key not in row:
            continue
        val = row[key]
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            val = None
        flat[key] = val

    params = row.get("params")
    if params is None:
        return flat, None
    if isinstance(params, str):
        params = json.loads(params)
    elif not isinstance(params, dict):
        params = dict(params)
    return flat, params


def parse_winch_settings(raw) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
