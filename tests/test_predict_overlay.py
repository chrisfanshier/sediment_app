"""Tests for predict-mode actual sensor overlay."""
import numpy as np

from sensor_tool.domain.processing.predict_overlay import (
    build_actual_overlay,
    effective_trigger_line_ft,
)
from sensor_tool.domain.processing.calculations import FT_TO_M


def test_effective_trigger_line_ft():
    ws = np.array([100.0, 100.0])
    trig = np.array([101.0, 101.0])
    assert abs(effective_trigger_line_ft(ws, trig, 0) - 1.0 / FT_TO_M) < 1e-6


def test_build_actual_overlay_zero_at_trip():
    n = 200
    t = np.linspace(0, 20, n)
    ws = 100.0 + 0.1 * t
    rel = ws + 2.0
    trip = 50
    grid = np.array([-1.0, 0.0, 1.0, 2.0, 3.0])

    trig = ws + 3.28

    overlay = build_actual_overlay(
        weight_stand=ws,
        release=rel,
        timestamps_epoch=t,
        trip_idx=trip,
        time_grid=grid,
        release_above_corer_m=2.0,
        piston=None,
        trigger_core=trig,
        planned_trigger_line_ft=30.0,
    )

    assert abs(overlay.corer_rel[1]) < 1e-6
    assert abs(overlay.release_rel[1] + 2.0) < 1e-6
    assert overlay.trigger_rel is not None
    assert abs(overlay.trigger_rel[1] - 3.28) < 1e-6
    assert overlay.planned_trigger_line_ft == 30.0
