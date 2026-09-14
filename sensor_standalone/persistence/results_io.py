"""SQLite persistence for analysis results (replaces sensor_analysis_results)."""
from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np

from .project import ProjectStore

_FLAT_COLUMNS = frozenset({
    "trip_index", "trip_datetime", "start_core_index", "start_core_datetime",
    "result_recoil_max", "result_recoil_time_s", "result_fall_dist", "result_suck_in",
    "result_recoil_start", "result_freefall_start", "result_piston_suck",
    "result_seafloor", "result_piston_alt", "result_pen_deficit", "result_freefall_est",
    "result_eff_trig_line", "trigger_pen_m", "winch_trip_index", "winch_trip_datetime",
    "winch_time_offset_sec",
})


class _NumpyEncoder(json.JSONEncoder):
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


def _conn(store: ProjectStore):
    return store._conn  # noqa: SLF001 — intentional tight coupling


def insert_result(
    store: ProjectStore,
    core_id: int,
    flat_data: Optional[dict] = None,
    params_section: Optional[dict] = None,
) -> int:
    data: dict = dict(flat_data or {})
    data["core_id"] = core_id

    cols = ["core_id"]
    vals = [core_id]
    for key, val in data.items():
        if key == "core_id" or key not in _FLAT_COLUMNS:
            continue
        cols.append(key)
        if key.endswith("_datetime") and val is not None:
            vals.append(str(val)[:19])
        else:
            vals.append(val)

    if params_section is not None:
        cols.append("params")
        vals.append(json.dumps(params_section, cls=_NumpyEncoder))

    placeholders = ", ".join("?" for _ in cols)
    col_sql = ", ".join(cols)
    cur = _conn(store).execute(
        f"INSERT INTO analysis_results ({col_sql}) VALUES ({placeholders})",
        vals,
    )
    _conn(store).commit()
    return cur.lastrowid


def update_result(
    store: ProjectStore,
    result_id: int,
    flat_data: Optional[dict] = None,
    params_section: Optional[dict] = None,
) -> None:
    if flat_data:
        parts = []
        vals = []
        for key, val in flat_data.items():
            if key not in _FLAT_COLUMNS:
                continue
            parts.append(f"{key} = ?")
            if key.endswith("_datetime") and val is not None:
                vals.append(str(val)[:19])
            else:
                vals.append(val)
        if parts:
            vals.append(result_id)
            _conn(store).execute(
                f"UPDATE analysis_results SET {', '.join(parts)} WHERE result_id = ?",
                vals,
            )

    if params_section is not None:
        row = _conn(store).execute(
            "SELECT params FROM analysis_results WHERE result_id = ?",
            (result_id,),
        ).fetchone()
        existing = {}
        if row and row["params"]:
            existing = json.loads(row["params"])
        existing.update(params_section)
        _conn(store).execute(
            "UPDATE analysis_results SET params = ? WHERE result_id = ?",
            (json.dumps(existing, cls=_NumpyEncoder), result_id),
        )

    _conn(store).commit()


def fetch_results_for_core(store: ProjectStore, core_id: int) -> list[dict]:
    rows = _conn(store).execute(
        """SELECT result_id, analyzed_at, trip_index, start_core_index,
                  result_recoil_max, winch_trip_index, winch_time_offset_sec, params
           FROM analysis_results
           WHERE core_id = ?
           ORDER BY analyzed_at DESC""",
        (core_id,),
    ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        if d.get("params"):
            d["params"] = json.loads(d["params"])
        results.append(d)
    return results


def fetch_result_by_id(store: ProjectStore, result_id: int) -> dict | None:
    row = _conn(store).execute(
        "SELECT * FROM analysis_results WHERE result_id = ?",
        (result_id,),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    if d.get("params"):
        d["params"] = json.loads(d["params"])
    return d
