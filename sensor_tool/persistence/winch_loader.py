"""
Winch data loader — loads and concatenates winch telemetry from the database.

Ported from winch_plot.py (auto core-overlap) and multiplot_st.py (manual
per-file selection). Uses sediment_app helpers for DB access and parsing.
"""
from __future__ import annotations

import json
import os
from typing import Optional

import pandas as pd
from sqlalchemy import text

from config import get_full_path
from db_util import get_connection
from utils import parse_winch_dat

_EXCLUDE_PARAM_COLS = frozenset({
    'index', 'datetime', 'date', 'time',
    'year', 'month', 'day', 'hour', 'minute', 'second',
})


def _strip_tz(dt_val) -> pd.Timestamp:
    dt = pd.to_datetime(dt_val, errors='coerce')
    if dt is not pd.NaT and hasattr(dt, 'tz') and dt.tz is not None:
        return dt.tz_localize(None)
    return dt


def _parsing_settings_from_row(settings_raw, file_name: str) -> dict:
    try:
        settings = json.loads(settings_raw) if settings_raw else {}
    except (json.JSONDecodeError, TypeError):
        settings = {}

    if settings:
        parsing = {
            'delimiter': settings.get('delimiter', ','),
            'header_lines': settings.get('header_lines', 0),
            'columns': settings.get('columns', []),
            'datetime_code': settings.get(
                'datetime_code', "pd.to_datetime(df['datetime'])"
            ),
        }
        if 'numeric_columns' in settings:
            parsing['numeric_columns'] = settings['numeric_columns']
        return parsing

    file_ext = os.path.splitext(file_name)[1].lower()
    if file_ext == '.dat':
        return {
            'delimiter': r'\s+',
            'header_lines': 0,
            'datetime_code': (
                "pd.to_datetime(df[['year', 'month', 'day', "
                "'hour', 'minute', 'second']])"
            ),
        }
    return {
        'delimiter': ',',
        'header_lines': 0,
        'datetime_code': "pd.to_datetime(df['datetime'])",
    }


def _parse_winch_row(file_path: str, file_name: str, settings_raw) -> Optional[pd.DataFrame]:
    relative_path = os.path.join(file_path, file_name)
    full_path = get_full_path(relative_path)
    parsing_settings = _parsing_settings_from_row(settings_raw, file_name)
    try:
        df = parse_winch_dat(full_path, parsing_settings)
        if df is not None and 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime']).dt.tz_localize(None)
            return df
    except Exception as exc:
        print(f"  ⚠ Could not load winch file {file_name}: {exc}")
    return None


def _core_deployment_window(core_row: pd.Series) -> Optional[tuple[pd.Timestamp, pd.Timestamp]]:
    date_col = next((c for c in ('date', 'core_date') if c in core_row.index), None)
    launch_col = next(
        (c for c in ('time_launched', 'time_launch', 'time_launched_utc')
         if c in core_row.index),
        None,
    )
    recover_col = next(
        (c for c in ('time_recovered', 'time_recover', 'time_recovered_utc')
         if c in core_row.index),
        None,
    )
    if not (date_col and launch_col and recover_col):
        return None

    core_start = (
        pd.to_datetime(core_row[date_col], errors='coerce')
        + pd.to_timedelta(str(core_row[launch_col]), errors='coerce')
    )
    core_end = (
        pd.to_datetime(core_row[date_col], errors='coerce')
        + pd.to_timedelta(str(core_row[recover_col]), errors='coerce')
    )
    if pd.isna(core_start) or pd.isna(core_end):
        return None
    if core_end < core_start:
        core_end += pd.Timedelta(days=1)
    return core_start, core_end


def get_winch_parameters(df: Optional[pd.DataFrame]) -> list[str]:
    """Return sorted numeric plottable column names from a winch DataFrame."""
    if df is None or df.empty:
        return []
    numeric_cols = [
        col for col in df.select_dtypes(include='number').columns
        if col.lower() not in _EXCLUDE_PARAM_COLS
    ]
    return sorted(numeric_cols)


def datetime_to_epoch(df: pd.DataFrame) -> pd.Series:
    """Convert winch datetime column to Unix epoch seconds."""
    vals = pd.to_datetime(df['datetime']).values.astype('datetime64[ns]')
    return pd.Series(vals.view('int64') / 1e9, index=df.index)


class WinchLoader:
    """Database-backed winch file loading."""

    @staticmethod
    def fetch_winch_files_for_cruise(cruise_id: int) -> list[dict]:
        """Return all winch files registered for a cruise."""
        with _get_connection() as conn:
            rows = conn.execute(text("""
                SELECT winch_file_id, file_name, file_path,
                       start_time, end_time, settings
                FROM winch_data
                WHERE cruise_id = :cid
                ORDER BY file_name
            """), {'cid': cruise_id}).fetchall()

        return [
            {
                'winch_file_id': r.winch_file_id,
                'file_name': r.file_name,
                'file_path': r.file_path,
                'start_time': _strip_tz(r.start_time),
                'end_time': _strip_tz(r.end_time),
                'settings': r.settings,
            }
            for r in rows
        ]

    @staticmethod
    def load_winch_file(winch_file_id: int) -> tuple[Optional[pd.DataFrame], str]:
        """Load a single winch file by database id."""
        with _get_connection() as conn:
            row = conn.execute(text("""
                SELECT file_name, file_path, settings
                FROM winch_data
                WHERE winch_file_id = :wid
            """), {'wid': winch_file_id}).fetchone()

        if row is None:
            return None, ''

        df = _parse_winch_row(row.file_path, row.file_name, row.settings)
        return df, row.file_name

    @staticmethod
    def load_winch_files_concat(
        winch_file_ids: list[int],
    ) -> tuple[Optional[pd.DataFrame], list[str]]:
        """Load and concatenate multiple winch files, sorted by datetime."""
        if not winch_file_ids:
            return None, []

        dfs: list[pd.DataFrame] = []
        names: list[str] = []
        for wid in winch_file_ids:
            df, name = WinchLoader.load_winch_file(wid)
            if df is not None and not df.empty:
                dfs.append(df)
                names.append(name)

        if not dfs:
            return None, names

        combined = (
            pd.concat(dfs, ignore_index=True)
            .sort_values('datetime')
            .reset_index(drop=True)
        )
        return combined, names

    @staticmethod
    def load_core_winch_data(
        core_id: int,
        cruise_id: int,
    ) -> tuple[Optional[pd.DataFrame], list[str]]:
        """
        Load and concatenate all winch files overlapping a core's deployment
        window, trimmed to that window.
        """
        with _get_connection() as conn:
            core_row = pd.read_sql(
                text('SELECT * FROM cores WHERE core_id = :cid'),
                conn,
                params={'cid': core_id},
            )
            winch_files = pd.read_sql(
                text("""
                    SELECT winch_file_id, file_name, file_path,
                           start_time, end_time, settings
                    FROM winch_data
                    WHERE cruise_id = :cruise_id
                    ORDER BY start_time
                """),
                conn,
                params={'cruise_id': cruise_id},
            )

        if core_row.empty or winch_files.empty:
            return None, []

        core_row = core_row.iloc[0]
        window = _core_deployment_window(core_row)
        if window is None:
            return None, []

        core_start, core_end = window
        winch_files['start_time'] = winch_files['start_time'].apply(_strip_tz)
        winch_files['end_time'] = winch_files['end_time'].apply(_strip_tz)

        overlap_mask = (
            (winch_files['start_time'] <= core_end)
            & (winch_files['end_time'] >= core_start)
        )
        overlapping = winch_files[overlap_mask]
        if overlapping.empty:
            return None, []

        winch_dfs: list[pd.DataFrame] = []
        file_names: list[str] = []
        for _, wrow in overlapping.iterrows():
            df = _parse_winch_row(
                wrow['file_path'], wrow['file_name'], wrow['settings'],
            )
            if df is not None:
                winch_dfs.append(df)
                file_names.append(wrow['file_name'])

        if not winch_dfs:
            return None, file_names

        all_winch = (
            pd.concat(winch_dfs, ignore_index=True)
            .sort_values('datetime')
            .reset_index(drop=True)
        )
        trim_mask = (
            (all_winch['datetime'] >= core_start)
            & (all_winch['datetime'] <= core_end)
        )
        trimmed = all_winch[trim_mask].copy().reset_index(drop=True)
        if trimmed.empty:
            return None, file_names
        return trimmed, file_names
