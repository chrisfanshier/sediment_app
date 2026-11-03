"""
analysis_results_io - Persistence layer for sensor_tool analysis results.

Provides insert/update functions for the sensor_analysis_results table.
Partial updates are supported: only the columns present in flat_data are
written; params_section is merged (via PostgreSQL ||) into the existing
JSONB params column so each panel can save independently without
overwriting other panels' data.
"""
from __future__ import annotations

import json
import math
import sys
import os
from typing import Optional

import numpy as np


class _NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy scalar types and non-finite floats."""

    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

    def iterencode(self, o, _one_shot=False):
        # Also convert plain Python float NaN/Inf to null.
        return super().iterencode(self._sanitize(o), _one_shot)

    def _sanitize(self, obj):
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        if isinstance(obj, dict):
            return {k: self._sanitize(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self._sanitize(v) for v in obj]
        return obj

# Allow running from the sensor_tool package context.
# db_util lives two levels up from this file (scripts/).
_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from db_util import get_connection, add_sync_tracking  # noqa: E402
from sqlalchemy import text                            # noqa: E402


def _is_blank(val) -> bool:
    """True for values that must never overwrite a stored one.

    ``None`` writes a NULL. A non-finite float is worse: PostgreSQL accepts
    NaN in a double precision column, so it would be stored and then read back
    as a real result. Either way a previously saved number is lost, which is
    the one thing a single-row-per-core layout cannot afford.
    """
    if val is None:
        return True
    if isinstance(val, float) and not math.isfinite(val):
        return True
    if isinstance(val, np.floating) and not math.isfinite(float(val)):
        return True
    return False


def _writable_flat(flat_data: Optional[dict]) -> dict:
    """Keep only the columns carrying a value worth writing."""
    return {
        k: v for k, v in (flat_data or {}).items() if not _is_blank(v)
    }


def insert_result(core_id: int,
                  flat_data: Optional[dict] = None,
                  params_section: Optional[dict] = None) -> int:
    """
    Insert a new sensor_analysis_results row.

    Parameters
    ----------
    core_id : int
        FK to cores.core_id.
    flat_data : dict, optional
        Real-column values to set (trip_index, result_recoil_max, etc.).
    params_section : dict, optional
        Dict to store as the initial params JSONB value.

    Returns
    -------
    int
        The new result_id.
    """
    data: dict = _writable_flat(flat_data)
    data["core_id"] = core_id

    if params_section is not None:
        data["params"] = json.dumps(params_section, cls=_NumpyEncoder)

    data = add_sync_tracking(data, created_on_ship=True, is_update=False)

    columns = ", ".join(data.keys())
    placeholders = ", ".join(f":{k}" for k in data.keys())
    sql = (
        f"INSERT INTO sensor_analysis_results ({columns}) "
        f"VALUES ({placeholders}) RETURNING result_id"
    )

    with get_connection() as conn:
        row = conn.execute(text(sql), data).fetchone()
        conn.commit()
    return row.result_id


def update_result(result_id: int,
                  flat_data: Optional[dict] = None,
                  params_section: Optional[dict] = None) -> None:
    """
    Update an existing sensor_analysis_results row.

    Only the columns present in flat_data are written.
    params_section, if provided, is *merged* into the existing params
    JSONB using the PostgreSQL || operator so that other panels' data
    is preserved.

    Parameters
    ----------
    result_id : int
        PK of the row to update.
    flat_data : dict, optional
        Real-column values to update.
    params_section : dict, optional
        Dict whose top-level keys are merged into the existing params JSONB.
    """
    data: dict = _writable_flat(flat_data)
    data = add_sync_tracking(data, is_update=True)

    set_parts: list[str] = [f"{k} = :{k}" for k in data.keys()]
    # analyzed_at is only defaulted on insert, and with one row per core the
    # row is updated for the rest of its life, so bump it here or it would
    # report when the core was first touched rather than last saved.
    set_parts.append("analyzed_at = CURRENT_TIMESTAMP")

    if params_section is not None:
        # Merge into existing JSONB: COALESCE handles NULL initial value.
        data["_params_merge"] = json.dumps(params_section, cls=_NumpyEncoder)
        set_parts.append(
            "params = COALESCE(params, '{}'::jsonb) || (:_params_merge)::jsonb"
        )

    if not set_parts:
        return  # nothing to update

    data["_result_id"] = result_id
    sql = (
        f"UPDATE sensor_analysis_results SET {', '.join(set_parts)} "
        f"WHERE result_id = :_result_id"
    )

    with get_connection() as conn:
        conn.execute(text(sql), data)
        conn.commit()


def latest_result_id(core_id: int) -> Optional[int]:
    """Return the analysis row for *core_id*, or None if it has never been saved.

    A core has one analysis row. Older databases can hold several from when
    each save forked a new one; the highest result_id is the most recently
    inserted (result_id is SERIAL, so the sequence only moves forward), which
    is the one those databases were already restoring from.
    """
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT MAX(result_id) AS rid FROM sensor_analysis_results "
                 "WHERE core_id = :cid"),
            {'cid': core_id},
        ).fetchone()
    if row is None or row.rid is None:
        return None
    return int(row.rid)


def upsert_result(core_id: int,
                  flat_data: Optional[dict] = None,
                  params_section: Optional[dict] = None) -> tuple[int, bool]:
    """Write into the core's analysis row, creating it on first save.

    Returns ``(result_id, created)``.
    """
    result_id = latest_result_id(core_id)
    if result_id is None:
        return insert_result(core_id, flat_data, params_section), True
    update_result(result_id, flat_data, params_section)
    return result_id, False


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def fetch_results_for_core(core_id: int) -> list[dict]:
    """Return summary rows for all saved analysis results for *core_id*, newest first.

    Each dict contains ``result_id``, ``analyzed_at``, ``trip_index``,
    ``start_core_index``, ``result_recoil_max``, and ``params``
    (the JSONB blob decoded to a Python dict).
    """
    with get_connection() as conn:
        rows = conn.execute(
            text("""
                SELECT result_id, analyzed_at, trip_index, start_core_index,
                       result_recoil_max, winch_trip_index, winch_time_offset_sec,
                       params
                FROM sensor_analysis_results
                WHERE core_id = :cid
                ORDER BY analyzed_at DESC NULLS LAST
            """),
            {'cid': core_id},
        ).fetchall()
    results = []
    for row in rows:
        d = dict(row._mapping)
        if d.get('params') is not None and isinstance(d['params'], str):
            d['params'] = json.loads(d['params'])
        results.append(d)
    return results


def fetch_latest_result(core_id: int) -> dict | None:
    """Return the core's analysis row in full, or None if never saved."""
    result_id = latest_result_id(core_id)
    return None if result_id is None else fetch_result_by_id(result_id)


def fetch_result_by_id(result_id: int) -> dict | None:
    """Return a full analysis result row by primary key, or ``None`` if not found.

    The ``params`` JSONB column is decoded to a Python dict.
    """
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT * FROM sensor_analysis_results WHERE result_id = :rid"),
            {'rid': result_id},
        ).fetchone()
    if row is None:
        return None
    d = dict(row._mapping)
    if d.get('params') is not None and isinstance(d['params'], str):
        d['params'] = json.loads(d['params'])
    return d
