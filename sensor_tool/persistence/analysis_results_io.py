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
import sys
import os
from typing import Optional

# Allow running from the sensor_tool package context.
# db_util lives two levels up from this file (scripts/).
_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from db_util import get_connection, add_sync_tracking  # noqa: E402
from sqlalchemy import text                            # noqa: E402


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
    data: dict = dict(flat_data or {})
    data["core_id"] = core_id

    if params_section is not None:
        data["params"] = json.dumps(params_section)

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
    data: dict = dict(flat_data or {})
    data = add_sync_tracking(data, is_update=True)

    set_parts: list[str] = [f"{k} = :{k}" for k in data.keys()]

    if params_section is not None:
        # Merge into existing JSONB: COALESCE handles NULL initial value.
        data["_params_merge"] = json.dumps(params_section)
        set_parts.append(
            "params = COALESCE(params, '{}'::jsonb) || :_params_merge::jsonb"
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
