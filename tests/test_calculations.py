"""Unit tests for calculate-mode domain logic."""
import numpy as np

from sensor_tool.domain.processing.calculations import compute_calculations, FT_TO_M


def test_eff_trig_line_ft_at_trip():
    """Effective trigger line is trigger−WS depth difference converted to feet."""
    n = 100
    timestamps = np.arange(n, dtype=float)
    weight_stand = np.linspace(100.0, 110.0, n)
    release = weight_stand + 2.0
    # Trigger 1 m deeper than weight stand at trip → 3.28 ft effective line
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
