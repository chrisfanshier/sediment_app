"""Unit tests for forward recoil prediction."""
import json
import os
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sensor_tool.domain.models.recoil_calibration import RecoilCalibration
from sensor_tool.domain.processing.predict import (
    default_inputs,
    run_prediction,
    training_warnings,
)

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "recoil_calibration_fixture.json"


def _load_calibration() -> dict:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return RecoilCalibration.from_dict(data).body


def test_recoil_calibration_round_trip():
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))
    model = RecoilCalibration.from_dict(original)
    restored = RecoilCalibration.from_dict(model.to_dict())
    assert restored.calibration["row_count_working"] == original["calibration"]["row_count_working"]


def test_run_prediction_produces_finite_bands():
    cal = _load_calibration()
    inputs = default_inputs()
    result = run_prediction(inputs, cal)

    assert "time" in result
    assert len(result["time"]) > 10
    assert set(result["corer_bands"]) == {10, 50, 90}
    assert set(result["trigger_bands"]) == {10, 50, 90}
    offset = result["trigger_line_m"]
    time = result["time"]
    pre = time < 0.0
    post = time >= 0.0
    assert np.allclose(result["trigger_bands"][50][pre], result["corer_bands"][50][pre] + offset)
    assert np.allclose(result["trigger_bands"][50][post], offset)
    for curve, bands in result["release_bands"].items():
        assert np.all(np.isfinite(bands[50]))
    assert len(result["event_summary"]) == 6
    assert np.isfinite(result["seafloor_m"])


def test_training_warnings_out_of_range_depth():
    cal = _load_calibration()
    inputs = default_inputs()
    inputs.depth_m = 10.0
    inputs.rope_type = "steel"
    warnings = training_warnings(inputs, cal)
    assert any("Depth" in w for w in warnings)


def test_hmpe_physics_uses_linear_depth():
    cal = _load_calibration()
    assert cal["physics"]["hmpe"]["use_log"] is False
    assert cal["physics"]["hmpe"]["predictor"] == "depth_m"
