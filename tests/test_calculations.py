"""Unit tests for calculate-mode domain logic."""
import numpy as np

from sensor_tool.domain.processing.calculations import (
    DEFAULT_WEIGHT_STAND_LENGTH_M,
    compute_calculations,
    penetration_deficit,
    FT_TO_M,
)


def _seafloor_case(
    *,
    ws_max: float,
    seafloor: float,
    weight_stand_length_m: float = DEFAULT_WEIGHT_STAND_LENGTH_M,
    manual: bool = False,
):
    n = 50
    trip_idx = 10
    trigger_pen = 0.0
    trigger_core_length_ft = 10.0
    timestamps = np.arange(n, dtype=float)
    weight_stand = np.full(n, ws_max)
    weight_stand[:trip_idx] = ws_max - 1.0
    release = weight_stand + 2.0
    trigger_core = weight_stand - 1.0
    if not manual:
        trigger_core[trip_idx] = (
            seafloor - trigger_core_length_ft * FT_TO_M + trigger_pen
        )
    kwargs = {
        "weight_stand": weight_stand,
        "release": release,
        "timestamps_epoch": timestamps,
        "trip_idx": trip_idx,
        "trigger_core": trigger_core,
        "trigger_core_length_ft": trigger_core_length_ft,
        "trigger_pen": trigger_pen,
        "core_length_ft": 60.0,
        "weight_stand_length_m": weight_stand_length_m,
    }
    if manual:
        kwargs["seafloor_override"] = seafloor
    return compute_calculations(**kwargs)


def test_eff_trig_line_ft_at_trip():
    """Effective trigger line is trigger−WS depth difference converted to feet."""
    n = 100
    timestamps = np.arange(n, dtype=float)
    weight_stand = np.linspace(100.0, 110.0, n)
    release = weight_stand + 2.0
    trigger_core = weight_stand + 1.0

    res = compute_calculations(
        weight_stand=weight_stand,
        release=release,
        timestamps_epoch=timestamps,
        trip_idx=50,
        trigger_core=trigger_core,
    )

    assert res.eff_trig_line_ft is not None
    assert abs(res.eff_trig_line_ft - 1.0 / FT_TO_M) < 1e-6


def test_eff_trig_line_ft_none_without_trigger_sensor():
    res = compute_calculations(
        weight_stand=np.array([100.0, 101.0]),
        release=np.array([102.0, 103.0]),
        timestamps_epoch=np.array([0.0, 1.0]),
        trip_idx=0,
        trigger_core=None,
    )
    assert res.eff_trig_line_ft is None


def test_penetration_deficit_helper():
    assert penetration_deficit(100.0, 98.5, 1.5) == 0.0
    assert penetration_deficit(100.0, 100.0, 1.5) == -1.5
    assert penetration_deficit(100.0, 96.5, 1.5) == 2.0


def test_pen_deficit_trigger_core_branch_default_length():
    ws_len = DEFAULT_WEIGHT_STAND_LENGTH_M
    seafloor = 100.0
    res = _seafloor_case(ws_max=seafloor - ws_len, seafloor=seafloor)
    assert res.pen_deficit is not None
    assert abs(res.pen_deficit) < 1e-9

    res_short = _seafloor_case(ws_max=seafloor - ws_len - 2.0, seafloor=seafloor)
    assert abs(res_short.pen_deficit - 2.0) < 1e-9

    res_over = _seafloor_case(ws_max=seafloor, seafloor=seafloor)
    assert abs(res_over.pen_deficit + ws_len) < 1e-9


def test_pen_deficit_manual_seafloor_branch():
    ws_len = DEFAULT_WEIGHT_STAND_LENGTH_M
    seafloor = 200.0
    res = _seafloor_case(
        ws_max=seafloor - ws_len,
        seafloor=seafloor,
        manual=True,
    )
    assert abs(res.pen_deficit) < 1e-9


def test_pen_deficit_non_default_weight_stand_length():
    ws_len = 2.0
    seafloor = 100.0
    res = _seafloor_case(
        ws_max=seafloor - ws_len,
        seafloor=seafloor,
        weight_stand_length_m=ws_len,
    )
    assert abs(res.pen_deficit) < 1e-9
    assert res.freefall_est is not None


def test_freefall_est_uses_weight_stand_length_not_changed_by_pen_deficit_fix():
    """freefall_est still uses L_WS in tip depth; default 1.5 unchanged."""
    n = 30
    timestamps = np.arange(n, dtype=float)
    trip = 5
    weight_stand = np.linspace(100.0, 101.0, n)
    release = weight_stand + 2.0
    trigger_core = weight_stand - 0.5
    core_ft = 60.0
    ws_len = DEFAULT_WEIGHT_STAND_LENGTH_M
    sf = float(trigger_core[trip]) + 10.0 * FT_TO_M

    res = compute_calculations(
        weight_stand=weight_stand,
        release=release,
        timestamps_epoch=timestamps,
        trip_idx=trip,
        trigger_core=trigger_core,
        trigger_core_length_ft=10.0,
        core_length_ft=core_ft,
        weight_stand_length_m=ws_len,
    )
    expected = abs(
        float(weight_stand[trip]) + ws_len + core_ft * FT_TO_M - sf
    )
    assert res.freefall_est is not None
    assert abs(res.freefall_est - expected) < 1e-9
