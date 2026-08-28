"""Restore/winch interaction scenarios for sensor_tool.

Covers the two cases where a core's saved result has no winch section but winch
files exist for its cruise:

  1. Restoring that result must not crash, must plot the sensor results, and
     must leave the user able to enter Winch mode, align, and save.
  2. Winch alignment from a previously loaded core must not survive a core
     switch, or the old core's trip index and file ids get written to the new
     core's row.

Database access and modal dialogs are stubbed, so no live database or display
is needed. Run from the repository root:

    QT_QPA_PLATFORM=offscreen python3 tests/scenario_restore_winch.py
"""
import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from sensor_tool.domain.models.sensor_data import SensorData  # noqa: E402
from sensor_tool.domain.processing.trip_detection import (  # noqa: E402
    TripDetectionResult,
)
from sensor_tool.gui.main_window import MainWindow  # noqa: E402
import sensor_tool.controllers.analysis_controller as ctrl_mod  # noqa: E402
import sensor_tool.persistence.analysis_results_io as io_mod  # noqa: E402

N = 1200
BASE = pd.Timestamp("2024-06-01 12:00:00")
SENSOR_TRIP = 600
WINCH_TRIP = 630  # winch series starts 30 s earlier, so this is the same instant

# ---------------------------------------------------------------------------
# Synthetic data
# ---------------------------------------------------------------------------

_DEPTH = np.concatenate([
    np.linspace(0, 300, 600),    # lowering
    np.linspace(300, 295, 100),  # impact / penetration
    np.linspace(295, 0, 500),    # recovery
])


def make_sensor_data(core_id, core_name, base):
    df = pd.DataFrame({
        "datetime": pd.date_range(base, periods=N, freq="s"),
        "Sensor_A_depth": _DEPTH,
        "Sensor_B_depth": _DEPTH + 0.4,
    })
    return SensorData(
        df, core_title=core_name, source_file="",
        depth_columns=["Sensor_A_depth", "Sensor_B_depth"],
        metadata={"core_id": core_id, "core_name": core_name},
    )


WINCH_TS = pd.date_range(BASE - pd.Timedelta(seconds=30), periods=N, freq="s")
WINCH_DF = pd.DataFrame({
    "datetime": WINCH_TS,
    "tension": np.concatenate([
        np.full(WINCH_TRIP, 8000.0), np.full(N - WINCH_TRIP, 3000.0),
    ]),
    "payout": np.linspace(0, 400, N),
})

CRUISE_WINCH_FILES = [
    {"winch_file_id": 41, "file_name": "winch_20240601.dat",
     "start_time": WINCH_TS[0], "end_time": WINCH_TS[-1]},
    {"winch_file_id": 42, "file_name": "winch_20240602.dat",
     "start_time": WINCH_TS[0], "end_time": WINCH_TS[-1]},
]


def saved_row_without_winch(result_id, core_id, base):
    """A previously saved result carrying every section except winch."""
    return {
        "result_id": result_id,
        "core_id": core_id,
        "analyzed_at": base,
        "trip_index": SENSOR_TRIP,
        "trip_datetime": pd.date_range(base, periods=N, freq="s")[SENSOR_TRIP],
        "start_core_index": SENSOR_TRIP + 5,
        "result_recoil_max": 1.23,
        "winch_trip_index": None,
        "winch_time_offset_sec": None,
        "params": {
            "piston": {
                "weight_stand_col": "Sensor_A_depth",
                "release_col": "Sensor_B_depth",
                "scope_ft": 30.0,
                "core_length_ft": 40.0,
            },
            "calc_inputs": {},
        },
    }


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class FakeWinchLoader:
    calls = []

    @staticmethod
    def fetch_winch_files_for_cruise(cruise_id):
        FakeWinchLoader.calls.append(("list", cruise_id))
        return CRUISE_WINCH_FILES

    @staticmethod
    def load_winch_files_concat(file_ids):
        FakeWinchLoader.calls.append(("concat", tuple(file_ids)))
        return WINCH_DF.copy(), [f"winch_file_{i}.dat" for i in file_ids]

    @staticmethod
    def load_core_winch_data(core_id, cruise_id):
        FakeWinchLoader.calls.append(("auto", core_id, cruise_id))
        return WINCH_DF.copy(), ["winch_20240601.dat"], [41]


class FakeDatabaseLoader:
    cores = {}

    @staticmethod
    def load_core_sensor_data(core_id, core_info):
        return FakeDatabaseLoader.cores[core_id]


SAVED_ROWS = {}

ctrl_mod.WinchLoader = FakeWinchLoader
ctrl_mod.DatabaseLoader = FakeDatabaseLoader
# restore_from_db imports fetch_result_by_id lazily from the module.
io_mod.fetch_result_by_id = lambda rid: SAVED_ROWS.get(rid)

# Modal dialogs block forever under the offscreen platform; record them instead.
DIALOGS = []
for _name in ("information", "critical", "warning"):
    setattr(ctrl_mod.QMessageBox, _name, staticmethod(
        lambda *a, _n=_name, **k: DIALOGS.append((_n,) + tuple(a[1:3]))))

UPSERTS = []

window = MainWindow()
window.show()
ctrl = window.controller
ctrl._upsert_analysis_result = lambda flat_data=None, params_section=None: (
    UPSERTS.append((ctrl._loaded_core_id, flat_data or {}, params_section or {})))

RESTORE_SUMMARIES = []
window.statusBar().messageChanged.connect(
    lambda m: RESTORE_SUMMARIES.append(m) if m.startswith("Restore complete") else None)

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


def set_sensor_trip(index):
    """Give the controller a sensor trip so winch alignment has a reference."""
    ts = ctrl.sensor_data.df[ctrl.sensor_data.datetime_col].iloc[index]
    ctrl.trip_detection_result = TripDetectionResult(
        trip_index=index, trip_datetime=ts, confidence=1.0,
        derivative_order=2, derivative_label="d2", threshold=1.0,
        derivative_profiles={}, divergence=np.zeros(N),
        depth_columns=list(ctrl.sensor_data.depth_columns),
    )


def load_core(core_id, core_name, cruise_id=9):
    """Load a DB core the way MainWindow._on_core_changed does."""
    ctrl.load_from_database(
        core_id, {"core_id": core_id, "core_name": core_name},
        cruise_id=cruise_id,
    )
    if window.get_current_mode() == "Winch":
        ctrl.reload_winch_data()
    app.processEvents()


def align_winch_in_winch_mode():
    """Enter Winch mode, detect the trip, and align."""
    window.set_mode("Winch")
    app.processEvents()
    if ctrl._winch_df is None:
        # Already in Winch mode, so set_mode emitted nothing and
        # on_mode_changed never ran the load.
        ctrl.reload_winch_data()
        app.processEvents()
    window.winch_panel.column1_combo.setCurrentText("tension")
    window.winch_panel.edge_buffer_spin.setValue(10)
    window.winch_panel.drop_threshold_spin.setValue(1000.0)
    app.processEvents()
    ctrl.detect_winch_trip()
    ctrl.align_winch_data()
    app.processEvents()


def winch_columns(flat):
    return {k: v for k, v in flat.items() if k.startswith("winch")}


# ---------------------------------------------------------------------------
# Scenario 1 — restore a result with no winch section
# ---------------------------------------------------------------------------

FakeDatabaseLoader.cores = {
    5: make_sensor_data(5, "CORE-A", BASE),
    6: make_sensor_data(6, "CORE-B", BASE + pd.Timedelta(days=3)),
}
SAVED_ROWS[77] = saved_row_without_winch(77, 5, BASE)
SAVED_ROWS[88] = saved_row_without_winch(88, 6, BASE + pd.Timedelta(days=3))

window.set_mode("View Data")
app.processEvents()
load_core(5, "CORE-A")

RESTORE_SUMMARIES.clear()
ctrl.restore_from_db(77)
app.processEvents()


def t_restore_does_not_crash():
    assert RESTORE_SUMMARIES, "restore produced no summary"
    assert "winch alignment (not saved)" in RESTORE_SUMMARIES[-1], (
        RESTORE_SUMMARIES[-1])
    assert "trip" in RESTORE_SUMMARIES[-1]


def t_restore_lands_in_calculate_and_plots():
    assert window.get_current_mode() == "Calculate", window.get_current_mode()
    assert len(ctrl.main_plot.plot_item.listDataItems()) > 0, "main plot is empty"


def t_restore_leaves_winch_unaligned():
    assert ctrl._winch_aligned is False
    assert ctrl._winch_trip_idx is None


check("restore without winch section does not crash", t_restore_does_not_crash)
check("restore lands in Calculate mode and plots", t_restore_lands_in_calculate_and_plots)
check("restore leaves winch state unaligned", t_restore_leaves_winch_unaligned)

FakeWinchLoader.calls.clear()
window.set_mode("Winch")
app.processEvents()


def t_winch_mode_autoloads_available_files():
    assert window.panel_stack.currentWidget() is window.winch_panel
    assert window.secondary_stack.currentWidget() is window.winch_plot_view
    assert ("auto", 5, 9) in FakeWinchLoader.calls, FakeWinchLoader.calls
    assert ctrl._winch_df is not None, "winch data was not auto-loaded"
    assert window.winch_panel.winch_file_list.count() == len(CRUISE_WINCH_FILES)
    columns = [window.winch_panel.column1_combo.itemText(i)
               for i in range(window.winch_panel.column1_combo.count())]
    assert "tension" in columns and "payout" in columns, columns


check("Winch mode auto-loads cruise winch files", t_winch_mode_autoloads_available_files)

align_winch_in_winch_mode()


def t_align_after_restore():
    assert ctrl._winch_trip_idx == WINCH_TRIP, ctrl._winch_trip_idx
    assert ctrl._winch_aligned is True
    # Synthetic series are built so the two trips are the same instant.
    assert abs(ctrl._winch_time_offset_sec) < 1e-6, ctrl._winch_time_offset_sec


def t_save_payload_after_align():
    flat, params = ctrl._build_winch_save_payload()
    assert flat is not None and params is not None, "payload not built"
    assert flat["winch_trip_index"] == WINCH_TRIP
    assert params["aligned"] is True
    assert params["winch_file_ids"] == [41], params["winch_file_ids"]


check("align winch after restoring sensor results", t_align_after_restore)
check("winch save payload builds after align", t_save_payload_after_align)

# ---------------------------------------------------------------------------
# Scenario 2 — alignment must not survive a core switch
# ---------------------------------------------------------------------------

load_core(5, "CORE-A")
set_sensor_trip(SENSOR_TRIP)
align_winch_in_winch_mode()
UPSERTS.clear()
ctrl.save_all_to_db()


def t_core_a_saves_winch():
    core_id, flat, params = UPSERTS[-1]
    assert core_id == 5, core_id
    assert winch_columns(flat).get("winch_trip_index") == WINCH_TRIP, flat
    assert params.get("winch"), "winch params missing for the aligned core"


check("aligned core saves winch columns", t_core_a_saves_winch)

# Switch cores from Calculate mode, so Winch mode is never re-entered and
# reload_winch_data never runs. This is what MainWindow._on_core_changed does.
window.set_mode("Calculate")
app.processEvents()
load_core(6, "CORE-B")


def t_core_switch_clears_winch_state():
    assert ctrl._winch_df is None, "winch dataframe survived the core switch"
    assert ctrl._winch_df_original is None, "winch snapshot survived the core switch"
    assert ctrl._winch_aligned is False, "alignment flag survived the core switch"
    assert ctrl._winch_trip_idx is None, "winch trip survived the core switch"
    assert ctrl._winch_file_ids == [], ctrl._winch_file_ids
    assert ctrl._winch_time_offset_sec == 0.0, ctrl._winch_time_offset_sec


check("core switch clears winch alignment state", t_core_switch_clears_winch_state)

RESTORE_SUMMARIES.clear()
ctrl.restore_from_db(88)
app.processEvents()
UPSERTS.clear()
ctrl.save_all_to_db()


def t_no_winch_leak_into_new_core():
    core_id, flat, params = UPSERTS[-1]
    assert core_id == 6, core_id
    leaked = winch_columns(flat)
    assert not leaked, f"previous core's winch columns leaked into core 6: {leaked}"
    assert not params.get("winch"), "previous core's winch params leaked into core 6"


check("no winch leak into the next core's saved row", t_no_winch_leak_into_new_core)

print()
if failures:
    print(f"SCENARIOS FAILED: {len(failures)} failure(s): {failures}")
    sys.exit(1)
print("SCENARIOS PASSED")
sys.exit(0)
