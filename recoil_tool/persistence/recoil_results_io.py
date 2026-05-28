"""
Persistence layer for recoil fitting results.

Provides insert/update functions for the recoil_calibration table.
Mirrors the pattern from sensor_tool/persistence/analysis_results_io.py.
"""
from __future__ import annotations

import os
import sys
from typing import Optional

from sqlalchemy import text

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from db_util import get_connection, add_sync_tracking  # noqa: E402

from ..domain.models.recoil_params import FitResult, DeploymentParams


def save_fit_result(
    result_id: int,
    core_id: int,
    fit: FitResult,
    notes: str = "",
) -> int:
    """
    Insert a FitResult into the recoil_calibration table.

    Parameters
    ----------
    result_id : int
        FK to sensor_analysis_results.result_id this fit was derived from.
    core_id : int
        FK to cores.core_id.
    fit : FitResult
        Completed fit output from recoil_model.fit_rebound().
    notes : str
        Optional user annotation.

    Returns
    -------
    int
        The new cal_id primary key.
    """
    p = fit.deployment

    data: dict = {
        "result_id":            result_id,
        "core_id":              core_id,
        # Deployment params
        "depth_m":              p.depth_m,
        "corer_lbs":            p.corer_lbs,
        "instrument_lbs":       p.instrument_lbs,
        "rope_type":            p.rope_type,
        "rope_dia_mm":          p.rope_dia_mm,
        # Fit results
        "E_eff_gpa":            fit.E_eff_gpa,
        "C_drag":               fit.C_drag,
        "v0_ms":                fit.v0_ms,
        "rebound_magnitude_m":  fit.rebound_magnitude_m,
        "rebound_time_s":       fit.rebound_time_s,
        "rmse_m":               fit.rmse_m,
        "r_squared":            fit.r_squared,
        "k_nm":                 fit.k_nm,
        "static_stretch_m":     fit.static_stretch_m,
        "notes":                notes,
    }

    data = add_sync_tracking(data, created_on_ship=True, is_update=False)

    columns = ", ".join(data.keys())
    placeholders = ", ".join(f":{k}" for k in data.keys())
    sql = (
        f"INSERT INTO recoil_calibration ({columns}) "
        f"VALUES ({placeholders}) RETURNING cal_id"
    )

    with get_connection() as conn:
        row = conn.execute(text(sql), data).fetchone()
        conn.commit()

    return row.cal_id


def fetch_calibration_dataset() -> list[dict]:
    """
    Return all rows from recoil_calibration joined with core name.
    Useful for building the calibration dataset for future predictions.
    """
    with get_connection() as conn:
        rows = conn.execute(text("""
            SELECT rc.*, c.core_name, cr.cruise_name
            FROM recoil_calibration rc
            LEFT JOIN cores c ON rc.core_id = c.core_id
            LEFT JOIN cruises cr ON c.cruise_id = cr.cruise_id
            ORDER BY rc.fitted_at DESC
        """)).fetchall()
    return [dict(r._mapping) for r in rows]
