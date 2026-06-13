"""
recoil_results_io — Persistence layer for recoil_tool fitting results.

Table: recoil_analysis_results
  One row per (core_id, curve_type).  Upsert pattern — re-saving overwrites
  the existing row for that core × curve-type combination.

  Columns
  -------
  deployment_params JSONB  : full DeploymentParams snapshot (dataclasses.asdict)
  trip_time_epoch          : absolute UTC epoch seconds of the trip instant
  fit_end_epoch            : absolute UTC epoch seconds of the fit-end marker
  E_gpa, C_drag            : physics model tuning params (NULL for empirical rows)
  v0_ms … k_nm             : physics model outputs     (NULL for empirical rows)
  A_m, tau_s, omega_rads   : empirical fit params      (NULL for physics rows)
  saved_at                 : timestamp of last save
"""
from __future__ import annotations

import json
import math
import os
import sys
from typing import Optional

import numpy as np

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from db_util import get_connection   # noqa: E402
from sqlalchemy import text           # noqa: E402


# ---------------------------------------------------------------------------
# JSON encoder (handles numpy scalars and non-finite floats)
# ---------------------------------------------------------------------------

class _NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return None if (math.isnan(obj) or math.isinf(obj)) else float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

    def iterencode(self, o, _one_shot=False):
        return super().iterencode(self._sanitize(o), _one_shot)

    def _sanitize(self, obj):
        if isinstance(obj, float):
            return None if (math.isnan(obj) or math.isinf(obj)) else obj
        if isinstance(obj, dict):
            return {k: self._sanitize(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self._sanitize(v) for v in obj]
        return obj


# ---------------------------------------------------------------------------
# Table management
# ---------------------------------------------------------------------------

def create_table_if_not_exists() -> None:
    """Create recoil_analysis_results if it does not already exist."""
    with get_connection() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS recoil_analysis_results (
                id                   SERIAL PRIMARY KEY,
                core_id              INTEGER NOT NULL REFERENCES cores(core_id),
                curve_type           VARCHAR(32) NOT NULL,

                deployment_params    JSONB,

                trip_time_epoch      DOUBLE PRECISION,
                fit_end_epoch        DOUBLE PRECISION,

                -- Physics model tuning + outputs (NULL for empirical rows)
                E_gpa                DOUBLE PRECISION,
                C_drag               DOUBLE PRECISION,
                v0_ms                DOUBLE PRECISION,
                peak_displacement_m  DOUBLE PRECISION,
                peak_time_s          DOUBLE PRECISION,
                k_nm                 DOUBLE PRECISION,

                -- Empirical fit parameters (NULL for physics rows)
                A_m                  DOUBLE PRECISION,
                tau_s                DOUBLE PRECISION,
                omega_rads           DOUBLE PRECISION,

                saved_at             TIMESTAMPTZ DEFAULT now(),

                -- Sync tracking
                created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                modified_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_on_ship      BOOLEAN DEFAULT TRUE,
                sync_status          VARCHAR(20) DEFAULT 'pending',
                last_synced_at       TIMESTAMP,
                central_id           INTEGER,

                UNIQUE (core_id, curve_type)
            )
        """))
        conn.commit()


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def upsert_result(
    core_id: int,
    curve_type: str,
    trip_time_epoch: float,
    fit_end_epoch: float,
    deployment_params: dict,
    *,
    E_gpa: Optional[float] = None,
    C_drag: Optional[float] = None,
    v0_ms: Optional[float] = None,
    peak_displacement_m: Optional[float] = None,
    peak_time_s: Optional[float] = None,
    k_nm: Optional[float] = None,
    A_m: Optional[float] = None,
    tau_s: Optional[float] = None,
    omega_rads: Optional[float] = None,
) -> None:
    """
    Insert or overwrite one recoil_analysis_results row.

    The unique key is (core_id, curve_type).  All columns are overwritten on
    conflict so re-saving always reflects the latest run.
    """
    params_json = json.dumps(deployment_params, cls=_NumpyEncoder)

    with get_connection() as conn:
        conn.execute(text("""
            INSERT INTO recoil_analysis_results
                (core_id, curve_type, deployment_params,
                 trip_time_epoch, fit_end_epoch,
                 E_gpa, C_drag, v0_ms, peak_displacement_m, peak_time_s, k_nm,
                 A_m, tau_s, omega_rads, saved_at,
                 created_at, modified_at, created_on_ship, sync_status)
            VALUES
                (:core_id, :curve_type, (:params_json)::jsonb,
                 :trip_time_epoch, :fit_end_epoch,
                 :E_gpa, :C_drag, :v0_ms, :peak_displacement_m, :peak_time_s, :k_nm,
                 :A_m, :tau_s, :omega_rads, now(),
                 now(), now(), :created_on_ship, :sync_status)
            ON CONFLICT (core_id, curve_type) DO UPDATE SET
                deployment_params   = EXCLUDED.deployment_params,
                trip_time_epoch     = EXCLUDED.trip_time_epoch,
                fit_end_epoch       = EXCLUDED.fit_end_epoch,
                E_gpa               = EXCLUDED.E_gpa,
                C_drag              = EXCLUDED.C_drag,
                v0_ms               = EXCLUDED.v0_ms,
                peak_displacement_m = EXCLUDED.peak_displacement_m,
                peak_time_s         = EXCLUDED.peak_time_s,
                k_nm                = EXCLUDED.k_nm,
                A_m                 = EXCLUDED.A_m,
                tau_s               = EXCLUDED.tau_s,
                omega_rads          = EXCLUDED.omega_rads,
                saved_at            = now(),
                sync_status         = 'pending',
                modified_at         = now()
        """), {
            'core_id':              core_id,
            'curve_type':           curve_type,
            'params_json':          params_json,
            'trip_time_epoch':      float(trip_time_epoch),
            'fit_end_epoch':        float(fit_end_epoch),
            'E_gpa':                E_gpa,
            'C_drag':               C_drag,
            'v0_ms':                v0_ms,
            'peak_displacement_m':  peak_displacement_m,
            'peak_time_s':          peak_time_s,
            'k_nm':                 k_nm,
            'A_m':                  A_m,
            'tau_s':                tau_s,
            'omega_rads':           omega_rads,
            'created_on_ship':      True,
            'sync_status':          'pending',
        })
        conn.commit()


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def load_results_for_core(core_id: int) -> dict[str, dict]:
    """
    Return all saved results for a core as a dict keyed by curve_type.

    Each value is a plain dict of column values.  The deployment_params JSONB
    column is decoded to a Python dict.
    """
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT * FROM recoil_analysis_results WHERE core_id = :cid"),
            {'cid': core_id},
        ).fetchall()

    results: dict[str, dict] = {}
    for row in rows:
        d = dict(row._mapping)
        dp = d.get('deployment_params')
        if isinstance(dp, str):
            d['deployment_params'] = json.loads(dp)
        elif dp is None:
            d['deployment_params'] = {}
        results[d['curve_type']] = d
    return results

