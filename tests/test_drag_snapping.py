"""Regression tests: a dragged event line must be saved where the user sees it.

Only the sample *index* of each event line is persisted. Before these tests,
dropping a line between two samples kept it drawn at the drop position while
the index resolved to the nearest sample, so a save/restore round trip moved
the line by up to half a sample. Snapping on drop makes the drawn position and
the saved index the same thing.
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

SAMPLE_INTERVAL_S = 0.5
N_SAMPLES = 500

# view attribute -> (add method, signal name)
DRAGGABLE_LINES = [
    ("_trip_line", "add_trip_line", "trip_line_changed"),
    ("_start_core_line", "add_start_core_line", "start_core_changed"),
    ("_start_pen_line", "add_start_pen_line", "start_pen_changed"),
    ("_end_pen_line", "add_end_pen_line", "end_pen_changed"),
    ("_pullout_line", "add_pullout_line", "pullout_changed"),
]


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _timestamps():
    return pd.date_range(
        "2024-01-01 10:00:00",
        periods=N_SAMPLES,
        freq=pd.Timedelta(seconds=SAMPLE_INTERVAL_S),
    )


def _sensor_data():
    from sensor_standalone.domain.models.sensor_data import SensorData

    df = pd.DataFrame({
        "datetime": _timestamps(),
        "S1": np.linspace(0, 100, N_SAMPLES),
    })
    return SensorData(df=df, datetime_col="datetime", depth_columns=["S1"])


def _plot_view(sensor_data):
    from sensor_standalone.gui.views.sensor_plot_view import SensorPlotView

    view = SensorPlotView()
    view.set_sensor_data(sensor_data)
    return view


@pytest.mark.parametrize("attr,adder,signal", DRAGGABLE_LINES)
def test_dragged_line_snaps_onto_the_sample_it_reports(qapp, attr, adder, signal):
    sd = _sensor_data()
    view = _plot_view(sd)
    epochs = sd.get_timestamps_epoch()

    start_idx = 200
    getattr(view, adder)(
        start_idx if adder == "add_trip_line" else float(epochs[start_idx])
    )
    line = getattr(view, attr)
    assert line is not None, f"{adder} did not create a line"

    emitted = []
    getattr(view, signal).connect(emitted.append)

    # Drop the line 40% of a sample past sample 210 -- the worst case for a
    # line that is drawn where dropped but saved as the nearest index.
    dropped_at = float(epochs[210]) + 0.4 * SAMPLE_INTERVAL_S
    line.setValue(dropped_at)
    line.sigPositionChangeFinished.emit(line)

    assert emitted, f"{signal} was not emitted on drop"
    reported_idx = emitted[-1]
    assert reported_idx == 210

    drawn_at = line.value()
    # Exact: epoch seconds are ~1.7e9, where approx()'s default relative
    # tolerance would accept a half-hour of drift.
    assert drawn_at == float(epochs[reported_idx]), (
        f"line is drawn at {drawn_at} but saved as index {reported_idx} "
        f"({epochs[reported_idx]}); restore would shift it "
        f"{epochs[reported_idx] - drawn_at:+.3f} s"
    )


def test_winch_trip_line_snaps_onto_its_sample(qapp):
    from sensor_standalone.gui.views.winch_plot_view import WinchPlotView

    times = _timestamps()
    view = WinchPlotView()
    view.plot(
        pd.DataFrame({"datetime": times,
                      "tension": np.linspace(0, 1000, N_SAMPLES)}),
        "tension",
    )
    epochs = view._x_epochs
    assert epochs is not None, "winch plot did not build an epoch axis"
    view.add_winch_trip_line(100)

    emitted = []
    view.winch_trip_line_changed.connect(emitted.append)

    view._winch_trip_line.setValue(float(epochs[100]) + 0.4 * SAMPLE_INTERVAL_S)
    view._winch_trip_line.sigPositionChangeFinished.emit(view._winch_trip_line)

    assert emitted == [100]
    assert view._winch_trip_line.value() == float(epochs[100])


def test_trip_drag_moves_the_stored_datetime_with_the_index(qapp):
    """The saved row carries both trip_index and trip_datetime.

    Restore trusts the index, but the datetime is what a shore-side reader and
    the save summary show, so leaving it on the pre-drag sample records a trip
    time that never matched the line the user placed.
    """
    from sensor_standalone.controllers.analysis_controller import AnalysisController

    sd = _sensor_data()
    times = _timestamps()

    class _Panel:
        def __init__(self):
            self.value = None

        def set_trip_time(self, s, source=""):
            self.value = s

    detection = types.SimpleNamespace(trip_index=100,
                                      trip_datetime=times[100])
    stub = types.SimpleNamespace(
        sensor_data=sd,
        trip_detection_result=detection,
        piston_panel=_Panel(),
        calculate_panel=_Panel(),
        main_window=None,
    )

    AnalysisController._on_trip_line_moved(stub, 250)

    assert detection.trip_index == 250
    assert pd.Timestamp(detection.trip_datetime) == times[250]
    assert pd.Timestamp(stub.piston_panel.value) == times[250]
    assert pd.Timestamp(stub.calculate_panel.value) == times[250]
