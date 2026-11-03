"""End-to-end check of the workflow the save/restore rework is for.

Drag every event line, save, switch to another core, come back, restore, and
every line must return to the sample it was dragged to. Runs against a real
SQLite project store, so the save and restore paths are the production ones.

    QT_QPA_PLATFORM=offscreen python3 tests/scenario_drag_save_restore.py
"""
import os
import sys
import tempfile
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from sensor_standalone.domain.models.sensor_data import SensorData  # noqa: E402
from sensor_standalone.domain.processing.trip_detection import (  # noqa: E402
    TripDetectionResult,
)
from sensor_standalone.gui.analysis_window import AnalysisWindow  # noqa: E402
from sensor_standalone.persistence.project import ProjectStore  # noqa: E402
from sensor_standalone.persistence import results_io  # noqa: E402
import sensor_standalone.controllers.analysis_controller as ctrl_mod  # noqa: E402

N = 1200
BASE = pd.Timestamp("2024-06-01 12:00:00")
TRIP = 600

# Where the user drags each line. Kept in analysis order and well clear of the
# values the automatics would pick, so a restored auto-recompute is visible.
DRAG = {
    "trip": 612,
    "start_core": 620,
    "start_pen": 640,
    "end_pen": 668,
    "pullout": 720,
}

_DEPTH = np.concatenate([
    np.linspace(0, 300, 600),
    np.linspace(300, 295, 100),
    np.linspace(295, 0, 500),
])


def make_sensor_data(core_id, core_name):
    df = pd.DataFrame({
        "datetime": pd.date_range(BASE, periods=N, freq="s"),
        "Sensor_A_depth": _DEPTH,
        "Sensor_B_depth": _DEPTH + 0.4,
        "Sensor_C_depth": _DEPTH - 8.0,
    })
    return SensorData(
        df, core_title=core_name, source_file="",
        depth_columns=["Sensor_A_depth", "Sensor_B_depth", "Sensor_C_depth"],
        metadata={"core_id": core_id, "core_name": core_name,
                  "core_length": 40.0, "scope": 30.0,
                  "trigger_core_length": 10.0},
    )


# Modal dialogs block forever offscreen; record them instead.
DIALOGS = []
for _name in ("information", "critical", "warning"):
    setattr(ctrl_mod.QMessageBox, _name, staticmethod(
        lambda *a, _n=_name, **k: DIALOGS.append((_n,) + tuple(a[1:3]))))

tmpdir = tempfile.mkdtemp()
store = ProjectStore(tmpdir)
cruise_id = store.add_cruise("TEST", vessel_name="RV Test")
CORES = {}
for name in ("CORE-A", "CORE-B"):
    CORES[name] = store.add_core(
        cruise_id, core_name=name, core_type="Jumbo Piston Core",
        core_length=40.0, scope=30.0,
        start_datetime=str(BASE), end_datetime=str(BASE + pd.Timedelta(seconds=N)),
        trigger_line_length=25.0, trigger_core_length=10.0,
        trigger_core_penetration=1.5,
    )

window = AnalysisWindow()
window.show()
window.set_store(store)
ctrl = window.controller


class FakeLoader:
    """Serves synthetic traces; the store itself stays real."""

    @staticmethod
    def load_core_sensor_data(core_id, core_info):
        return make_sensor_data(core_id, core_info.get("core_name", ""))


ctrl._data_loader = FakeLoader

failures = []


def check(name, fn):
    try:
        fn()
    except Exception:
        failures.append(name)
        print(f"FAIL  {name}")
        traceback.print_exc()
    else:
        print(f"ok    {name}")


def load_core(name):
    ctrl.load_from_database(
        CORES[name], {"core_id": CORES[name], "core_name": name,
                      "trigger_core_penetration": 1.5},
        cruise_id=cruise_id,
    )
    app.processEvents()


def _select_column(combo, column):
    for i in range(combo.count()):
        if combo.itemData(i) == column:
            combo.setCurrentIndex(i)
            return
    raise AssertionError(
        f"{column} not offered; options: "
        f"{[combo.itemData(i) for i in range(combo.count())]}"
    )


def _set_trip(index=TRIP):
    ts = ctrl.sensor_data.df["datetime"].iloc[index]
    ctrl.trip_detection_result = TripDetectionResult(
        trip_index=index, trip_datetime=ts, confidence=1.0,
        derivative_order=2, derivative_label="d2", threshold=1.0,
        derivative_profiles={}, divergence=np.zeros(N),
        depth_columns=list(ctrl.sensor_data.depth_columns),
    )
    trip_str = str(ts)
    window.piston_panel.set_trip_time(trip_str, source="detection")
    window.calculate_panel.set_trip_time(trip_str, source="detection")
    return ts


def setup_through_calculate():
    """Trip detect → piston position → Calculate, the usual save-your-place path."""
    _set_trip()

    window.set_mode("Piston Position")
    app.processEvents()
    piston = window.piston_panel
    _select_column(piston.weight_stand_combo, "Sensor_A_depth")
    _select_column(piston.release_combo, "Sensor_B_depth")
    app.processEvents()
    ctrl.calculate_piston()
    app.processEvents()
    assert ctrl._piston_start_core_idx is not None, "piston did not detect start_core"

    # Column picks have to be in place before the plot runs: _plot_calculate_mode
    # reads them to compute the seafloor intersection that places start_pen.
    calc = window.calculate_panel
    window.set_mode("Calculate")
    app.processEvents()
    _select_column(calc.weight_stand_combo, "Sensor_A_depth")
    _select_column(calc.release_combo, "Sensor_B_depth")
    _select_column(calc.trigger_combo, "Sensor_C_depth")
    calc.set_trigger_pen(1.5)
    app.processEvents()
    ctrl._plot_calculate_mode()
    app.processEvents()

    # _plot_calculate_mode auto-places end_pen and pullout and computes start_pen.
    # and pullout and computes start_pen. Every draggable line must be present
    # before we simulate the user's drags.
    missing = [attr for attr in (
        "_trip_line", "_start_core_line", "_start_pen_line",
        "_end_pen_line", "_pullout_line",
    ) if getattr(ctrl.main_plot, attr) is None]
    assert not missing, f"lines missing before drag: {missing}"


def drag(line_attr, target_idx):
    """Drop a line between samples, the way a mouse drag ends."""
    view = ctrl.main_plot
    line = getattr(view, line_attr)
    assert line is not None, f"{line_attr} is not on the plot"
    epochs = ctrl.sensor_data.get_timestamps_epoch()
    # Land 40% of a sample past the target so snapping has work to do.
    sample_s = float(epochs[1] - epochs[0])
    line.setValue(float(epochs[target_idx]) + 0.4 * sample_s)
    line.sigPositionChangeFinished.emit(line)
    app.processEvents()


def line_indices():
    """Where each line currently sits, as a sample index."""
    epochs = ctrl.sensor_data.get_timestamps_epoch()
    out = {}
    for key, attr in (("trip", "_trip_line"),
                      ("start_core", "_start_core_line"),
                      ("start_pen", "_start_pen_line"),
                      ("end_pen", "_end_pen_line"),
                      ("pullout", "_pullout_line")):
        line = getattr(ctrl.main_plot, attr)
        out[key] = (None if line is None
                    else int(np.argmin(np.abs(epochs - line.value()))))
    return out


# ---------------------------------------------------------------------------
# Drag every line, then save
# ---------------------------------------------------------------------------

load_core("CORE-A")
setup_through_calculate()

for key, attr in (("trip", "_trip_line"),
                  ("start_core", "_start_core_line"),
                  ("start_pen", "_start_pen_line"),
                  ("end_pen", "_end_pen_line"),
                  ("pullout", "_pullout_line")):
    drag(attr, DRAG[key])

ctrl.run_calculations()
app.processEvents()

after_drag = line_indices()


def t_drags_landed_on_their_samples():
    assert after_drag == DRAG, f"{after_drag} != {DRAG}"


check("every dragged line sits on the sample it was dropped near",
      t_drags_landed_on_their_samples)


def t_calculations_ran():
    assert ctrl._last_calc_results is not None, "Calculate produced no results"


check("calculations run from the dragged positions", t_calculations_ran)

pen_deficit_before = getattr(ctrl._last_calc_results, "pen_deficit", None)

DIALOGS.clear()
ctrl.save_all_to_db()
app.processEvents()


def t_saved_one_row():
    rows = results_io.fetch_results_for_core(store, CORES["CORE-A"])
    assert len(rows) == 1, f"expected one row, got {len(rows)}"


def t_saved_dragged_indices():
    row = results_io.fetch_latest_result(store, CORES["CORE-A"])
    calc = row["params"]["calc_inputs"]
    assert row["trip_index"] == DRAG["trip"], row["trip_index"]
    assert calc["start_core_idx"] == DRAG["start_core"], calc["start_core_idx"]
    assert calc["end_pen_idx"] == DRAG["end_pen"], calc["end_pen_idx"]
    assert calc["pullout_idx"] == DRAG["pullout"], calc["pullout_idx"]
    assert calc["start_pen_manual"] == DRAG["start_pen"], calc["start_pen_manual"]


def t_no_stale_warning_on_a_full_save():
    stale = [d for d in DIALOGS if "out of date" in str(d)]
    assert not stale, f"unexpected staleness warning: {stale}"


check("a full save writes one row", t_saved_one_row)
check("saved row carries every dragged index", t_saved_dragged_indices)
check("a full save raises no staleness warning", t_no_stale_warning_on_a_full_save)

# ---------------------------------------------------------------------------
# Switch away, come back, restore
# ---------------------------------------------------------------------------

load_core("CORE-B")
app.processEvents()


def t_core_switch_clears_the_drags():
    assert ctrl._manual_start_pen is None
    assert ctrl._end_pen_idx is None
    assert ctrl._pullout_idx is None


check("switching cores clears the previous core's drags",
      t_core_switch_clears_the_drags)

load_core("CORE-A")
DIALOGS.clear()
ctrl._on_restore_results()
app.processEvents()

after_restore = line_indices()


def t_restore_needs_no_picker():
    picked = [d for d in DIALOGS if "No saved analysis" in str(d)]
    assert not picked, DIALOGS


def t_every_line_came_back_where_it_was_dragged():
    diffs = {k: (DRAG[k], after_restore[k])
             for k in DRAG if after_restore[k] != DRAG[k]}
    assert not diffs, f"lines moved on restore (dragged, restored): {diffs}"


check("restore runs without a picker", t_restore_needs_no_picker)
check("every line returns to where it was dragged",
      t_every_line_came_back_where_it_was_dragged)


def t_controller_state_matches_the_restored_lines():
    assert ctrl._manual_start_pen == DRAG["start_pen"], ctrl._manual_start_pen
    assert ctrl._start_pen_idx == DRAG["start_pen"], ctrl._start_pen_idx
    assert ctrl._end_pen_idx == DRAG["end_pen"], ctrl._end_pen_idx
    assert ctrl._pullout_idx == DRAG["pullout"], ctrl._pullout_idx
    assert ctrl._calc_start_core_idx == DRAG["start_core"], ctrl._calc_start_core_idx
    assert ctrl.trip_detection_result.trip_index == DRAG["trip"]


check("restored controller state matches the restored lines",
      t_controller_state_matches_the_restored_lines)


def t_results_survive_the_round_trip():
    row = results_io.fetch_latest_result(store, CORES["CORE-A"])
    if pen_deficit_before is None or not np.isfinite(pen_deficit_before):
        return  # nothing was computed to compare against
    assert row["result_pen_deficit"] is not None, "pen deficit was lost"
    assert abs(row["result_pen_deficit"] - pen_deficit_before) < 1e-6, (
        f"{row['result_pen_deficit']} != {pen_deficit_before}")


check("calculation results survive the round trip",
      t_results_survive_the_round_trip)

# ---------------------------------------------------------------------------
# A partial re-save keeps what it did not touch, and says results are stale
# ---------------------------------------------------------------------------

load_core("CORE-A")
DIALOGS.clear()
_set_trip(TRIP + 30)
ctrl.save_all_to_db()
app.processEvents()


def t_partial_resave_keeps_calculations():
    row = results_io.fetch_latest_result(store, CORES["CORE-A"])
    assert row["trip_index"] == TRIP + 30, row["trip_index"]
    assert row["result_recoil_max"] is not None, (
        "a trip-only re-save erased the stored calculation results")
    assert row["params"].get("calc_inputs"), (
        "a trip-only re-save erased the stored calculation inputs")


def t_partial_resave_warns_about_stale_results():
    stale = [d for d in DIALOGS if "out of date" in str(d)]
    assert stale, f"no staleness warning was shown; dialogs: {DIALOGS}"


check("a trip-only re-save keeps the stored calculations",
      t_partial_resave_keeps_calculations)
check("a trip-only re-save warns that they are stale",
      t_partial_resave_warns_about_stale_results)


def t_still_one_row():
    rows = results_io.fetch_results_for_core(store, CORES["CORE-A"])
    assert len(rows) == 1, f"re-saves forked the row: {len(rows)} rows"


check("re-saves stay in the same row", t_still_one_row)

print()
if failures:
    print(f"SCENARIOS FAILED: {len(failures)} failure(s): {failures}")
    sys.exit(1)
print("SCENARIOS PASSED")
sys.exit(0)
