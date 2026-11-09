"""Regression tests: a dragged start-pen line must survive recompute and restore.

``_update_start_pen_line`` recomputes start_pen as the first sample where the
core tip reaches the seafloor, and it runs on every seafloor edit, Calculate
re-run and restore. Without a manual-override flag it overwrote any drag, and
start_pen was never persisted at all, so the position could not come back.
"""
import os
import sys
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

pytest.importorskip("PySide6")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

N_SAMPLES = 400
MANUAL_SP = 260


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _sensor_data():
    from sensor_standalone.domain.models.sensor_data import SensorData

    times = pd.date_range("2024-01-01 10:00:00", periods=N_SAMPLES, freq="500ms")
    # The weight stand descends steadily, so the core tip crosses the seafloor
    # at one well-defined sample, far from MANUAL_SP.
    df = pd.DataFrame({
        "datetime": times,
        "WS": np.linspace(0.0, 40.0, N_SAMPLES),
        "TRIG": np.linspace(0.0, 40.0, N_SAMPLES),
    })
    sd = SensorData(df=df, datetime_col="datetime",
                    depth_columns=["WS", "TRIG"])
    sd.metadata.update({"core_length": 32.8, "trigger_core_length": 9.84})
    return sd


class _Log:
    def __init__(self):
        self.lines = []

    def log(self, msg):
        self.lines.append(msg)


class _CalcPanel:
    """Minimal stand-in exposing only what _update_start_pen_line reads."""

    def __init__(self):
        self.log_widget = _Log()

    def get_weight_stand_col(self):
        return "WS"

    def get_trigger_col(self):
        return "TRIG"

    def get_trigger_pen(self):
        return 0.0

    def get_weight_stand_length_m(self):
        return 1.0


class _Plot:
    def __init__(self):
        self.start_pen_x = None

    def remove_start_pen_line(self):
        self.start_pen_x = None

    def remove_seafloor_line(self):
        pass

    def add_seafloor_line(self, depth, movable=False):
        pass

    def add_start_pen_line(self, x_pos):
        self.start_pen_x = x_pos


def _stub(sensor_data):
    return types.SimpleNamespace(
        sensor_data=sensor_data,
        calculate_panel=_CalcPanel(),
        main_plot=_Plot(),
        _manual_seafloor=20.0,
        _manual_start_pen=None,
        _start_pen_idx=None,
    )


def test_recompute_alone_picks_the_computed_sample(qapp):
    """Baseline: with no override the automatic intersection is used."""
    from sensor_standalone.controllers.analysis_controller import AnalysisController

    sd = _sensor_data()
    stub = _stub(sd)
    AnalysisController._update_start_pen_line(stub, 0)

    assert stub._start_pen_idx is not None
    assert stub._start_pen_idx != MANUAL_SP, "fixture must not compute MANUAL_SP"


def test_drag_survives_recompute(qapp):
    from sensor_standalone.controllers.analysis_controller import AnalysisController

    sd = _sensor_data()
    stub = _stub(sd)

    AnalysisController._on_start_pen_moved(stub, MANUAL_SP)
    assert stub._manual_start_pen == MANUAL_SP

    # A seafloor edit, a Calculate re-run and a restore all land here.
    AnalysisController._update_start_pen_line(stub, 0)

    assert stub._start_pen_idx == MANUAL_SP
    epochs = sd.get_timestamps_epoch()
    assert stub.main_plot.start_pen_x == float(epochs[MANUAL_SP])


def _capture_calc_save(manual_start_pen):
    """Run the real calc save path and return the params it would write."""
    from sensor_standalone.controllers.analysis_controller import AnalysisController

    captured = {}

    results = types.SimpleNamespace(
        recoil_max=1.0, recoil_time_s=2.0, fall_dist=3.0, suck_in=0.1,
        recoil_start=10, freefall_start=5, piston_suck=0.2, seafloor=20.0,
        piston_alt=1.0, pen_deficit=0.5, freefall_est=1.0,
        eff_trig_line_ft=30.0, notes=["n"],
    )
    stub = types.SimpleNamespace(
        _last_calc_results=results,
        _last_calc_inputs={"trigger_pen": 0.0, "trip_idx": 100,
                           "start_core_idx": 110},
        _end_pen_idx=120,
        _pullout_idx=180,
        _start_pen_idx=MANUAL_SP,
        _manual_start_pen=manual_start_pen,
        _manual_seafloor=20.0,
        _upsert_analysis_result=(
            lambda flat_data=None, params_section=None: captured.update(
                flat=flat_data, params=params_section
            )
        ),
    )
    AnalysisController.save_calculations_to_db(stub)
    return captured["params"]["calc_inputs"]


def test_dragged_start_pen_is_written_into_the_saved_params(qapp):
    calc_inputs = _capture_calc_save(MANUAL_SP)

    assert calc_inputs["start_pen_idx"] == MANUAL_SP
    assert calc_inputs["start_pen_manual"] == MANUAL_SP


def test_computed_start_pen_is_saved_without_the_override_flag(qapp):
    calc_inputs = _capture_calc_save(None)

    assert calc_inputs["start_pen_idx"] == MANUAL_SP
    assert calc_inputs["start_pen_manual"] is None


def _run_restore(calc_params):
    """Call _restore_calculate on a stub, stubbing out its run_calculations."""
    from sensor_standalone.controllers.analysis_controller import AnalysisController

    stub = _stub(_sensor_data())
    stub.calculate_panel = None
    stub._end_pen_idx = None
    stub._pullout_idx = None
    stub._calc_start_core_idx = None
    stub.run_calculations = lambda: None
    AnalysisController._restore_calculate(stub, calc_params, lambda _m: None)
    return stub


def test_restore_pins_a_dragged_start_pen(qapp):
    stub = _run_restore({"start_pen_idx": MANUAL_SP,
                         "start_pen_manual": MANUAL_SP})

    assert stub._start_pen_idx == MANUAL_SP
    assert stub._manual_start_pen == MANUAL_SP


def test_restore_leaves_a_computed_start_pen_free_to_recompute(qapp):
    stub = _run_restore({"start_pen_idx": MANUAL_SP,
                         "start_pen_manual": None})

    assert stub._manual_start_pen is None


def test_restored_seafloor_override_is_shown_on_the_panel(qapp):
    """Restore set the controller's override but left the panel unchecked.

    The panel then read as "no override" with a stale 0.00 in the spinbox, so
    the next toggle pushed 0.00 back into the analysis.
    """
    from sensor_standalone.controllers.analysis_controller import AnalysisController
    from sensor_standalone.gui.panels.calculate_panel import CalculatePanel

    stub = _stub(_sensor_data())
    stub._manual_seafloor = None
    stub.calculate_panel = CalculatePanel()
    stub._end_pen_idx = None
    stub._pullout_idx = None
    stub._calc_start_core_idx = None
    stub.run_calculations = lambda: None

    AnalysisController._restore_calculate(
        stub, {"seafloor_manual": 1234.5}, lambda _m: None
    )

    panel = stub.calculate_panel
    assert panel.seafloor_check.isChecked()
    assert panel.get_seafloor_override() == pytest.approx(1234.5)
    assert stub._manual_seafloor == pytest.approx(1234.5)
