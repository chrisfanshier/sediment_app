"""Regression tests for trip-time fidelity across a save/restore round trip.

The bug these cover: detect a trip, save, switch cores, come back, restore, and
the trip line sat ~0.5 s earlier than detected, with no dragging involved.

Two independent causes, both covered here:

1. ``results_io`` wrote every ``*_datetime`` as ``str(val)[:19]``, truncating
   sub-second precision. Truncation always biases earlier.
2. Calculate and Piston modes re-derive the trip index from their panel time
   widget (``_resolve_calc_trip_index``) rather than trusting the exact
   ``trip_index`` column, so a truncated panel time moved the line to the
   previous sample -- and, because ``_restore_calculate`` re-runs
   ``run_calculations()``, moved the recomputed results with it.
"""
import os
import sys
import tempfile
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

pytest.importorskip("PySide6")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from sensor_standalone.persistence import results_io as rio  # noqa: E402
from sensor_standalone.persistence.project import ProjectStore  # noqa: E402

SAMPLE_INTERVAL_S = 0.5
N_SAMPLES = 2000
TRIP_IDX = 1001


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        st = ProjectStore(tmp)
        cruise_id = st.add_cruise("C", vessel_name="V")
        core_id = st.add_core(
            cruise_id, core_name="JP01", core_type="Jumbo Piston Core",
            core_length=30.0, scope=100.0,
            start_datetime="2024-01-01 09:00:00",
            end_datetime="2024-01-01 11:00:00",
            trigger_line_length=5.0, trigger_core_length=3.0,
            trigger_core_penetration=1.5,
        )
        yield st, core_id


def _timestamps():
    return pd.date_range(
        "2024-01-01 10:00:00",
        periods=N_SAMPLES,
        freq=pd.Timedelta(seconds=SAMPLE_INTERVAL_S),
    )


def _sensor_data():
    from sensor_standalone.domain.models.sensor_data import SensorData

    times = _timestamps()
    df = pd.DataFrame({
        "datetime": times,
        "S1": np.linspace(0, 100, N_SAMPLES),
    })
    return SensorData(df=df, datetime_col="datetime", depth_columns=["S1"])


def test_insert_preserves_sub_second_datetime(store):
    st, core_id = store
    trip_dt = _timestamps()[TRIP_IDX].to_pydatetime()
    assert trip_dt.microsecond, "fixture must use a sub-second trip time"

    rid = rio.insert_result(st, core_id, {"trip_index": TRIP_IDX,
                                          "trip_datetime": trip_dt})
    row = rio.fetch_result_by_id(st, rid)

    assert pd.Timestamp(row["trip_datetime"]) == pd.Timestamp(trip_dt)


def test_update_preserves_sub_second_datetime(store):
    st, core_id = store
    rid = rio.insert_result(st, core_id, {"trip_index": 0})

    trip_dt = _timestamps()[TRIP_IDX].to_pydatetime()
    rio.update_result(st, rid, {"trip_datetime": trip_dt})
    row = rio.fetch_result_by_id(st, rid)

    assert pd.Timestamp(row["trip_datetime"]) == pd.Timestamp(trip_dt)


def _restore_trip_on_stub(sensor_data, trip_index, stored_datetime):
    """Invoke the real _restore_trip against a minimal stub controller."""
    from sensor_standalone.controllers.analysis_controller import AnalysisController

    class _Panel:
        def __init__(self):
            self.value = None

        def set_trip_time(self, s, source=""):
            self.value = s

    class _Plot:
        def __init__(self):
            self.index = None

        def add_trip_line(self, i):
            self.index = i

    stub = types.SimpleNamespace(
        sensor_data=sensor_data,
        piston_panel=_Panel(),
        calculate_panel=_Panel(),
        main_plot=_Plot(),
        trip_detection_result=None,
    )
    ok = AnalysisController._restore_trip(
        stub, trip_index, stored_datetime, lambda _m: None
    )
    return ok, stub


def test_restore_trip_uses_sample_time_at_saved_index(qapp):
    """A legacy row with a truncated datetime must still restore exactly.

    The saved index was always written exactly, so it is the authoritative
    value and must win over a lossy stored timestamp.
    """
    sd = _sensor_data()
    true_ts = _timestamps()[TRIP_IDX]
    legacy_truncated = str(true_ts)[:19]
    assert pd.Timestamp(legacy_truncated) != true_ts, "fixture must lose precision"

    ok, stub = _restore_trip_on_stub(sd, TRIP_IDX, legacy_truncated)

    assert ok
    assert stub.main_plot.index == TRIP_IDX
    assert pd.Timestamp(stub.calculate_panel.value) == true_ts
    assert pd.Timestamp(stub.piston_panel.value) == true_ts


def test_restored_panel_time_re_derives_the_saved_index(qapp):
    """Guards the actual user-visible symptom.

    Calculate mode recomputes the index from the panel time via searchsorted,
    so that round trip has to land back on the saved index or both the trip
    line and every trip-dependent result shift by a sample.
    """
    sd = _sensor_data()
    true_ts = _timestamps()[TRIP_IDX]
    _, stub = _restore_trip_on_stub(sd, TRIP_IDX, str(true_ts)[:19])

    panel_epoch = pd.Timestamp(stub.calculate_panel.value).value / 1e9
    epochs = sd.get_timestamps_epoch()
    resolved = min(int(np.searchsorted(epochs, panel_epoch)), len(epochs) - 1)

    assert resolved == TRIP_IDX, (
        f"trip re-resolved to index {resolved} instead of {TRIP_IDX}; "
        f"line would shift {epochs[resolved] - epochs[TRIP_IDX]:+.3f} s"
    )


def test_full_save_restore_round_trip_has_no_shift(qapp, store):
    """End to end: detect, save, restore, re-resolve. No dragging involved."""
    st, core_id = store
    sd = _sensor_data()
    epochs = sd.get_timestamps_epoch()
    trip_dt = _timestamps()[TRIP_IDX].to_pydatetime()

    rid = rio.insert_result(st, core_id, {"trip_index": TRIP_IDX,
                                          "trip_datetime": trip_dt})
    row = rio.fetch_result_by_id(st, rid)

    _, stub = _restore_trip_on_stub(sd, int(row["trip_index"]),
                                    row["trip_datetime"])

    panel_epoch = pd.Timestamp(stub.calculate_panel.value).value / 1e9
    resolved = min(int(np.searchsorted(epochs, panel_epoch)), len(epochs) - 1)

    assert resolved == TRIP_IDX
    assert epochs[resolved] == pytest.approx(epochs[TRIP_IDX])
