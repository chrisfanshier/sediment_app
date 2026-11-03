"""Headless smoke test for sensor_tool.

Constructs the real MainWindow under the offscreen Qt platform and exercises
mode switching, the Winch-mode wiring, and the restore mode-selection branch.
No database is required: the controller tolerates DB-less operation.

Run from the repository root:

    QT_QPA_PLATFORM=offscreen python3 tests/smoke_sensor_tool.py
"""
import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

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


from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from sensor_tool.gui.main_window import MainWindow, MODES  # noqa: E402


def t_imports():
    import sensor_tool.controllers.analysis_controller  # noqa: F401
    import sensor_tool.persistence.winch_loader  # noqa: F401
    import sensor_tool.persistence.analysis_results_io  # noqa: F401
    import sensor_tool.domain.processing.winch_trip_detection  # noqa: F401
    import sensor_tool.gui.panels.winch_panel  # noqa: F401
    import sensor_tool.gui.views.winch_plot_view  # noqa: F401


check("all sensor_tool modules import", t_imports)

window = MainWindow()
window.show()
ctrl = window.controller


def t_window_title():
    # Integration-side rebrand must survive the merge.
    assert window.windowTitle() == "Sensorius", window.windowTitle()


def t_predict_mode_registered():
    assert "Predict" in MODES, MODES
    assert window.predict_panel is not None
    assert window.predict_plot_view is not None
    assert ctrl.predict_panel is window.predict_panel


def t_winch_mode_registered():
    assert "Winch" in MODES, MODES
    assert window.winch_panel is not None
    assert window.winch_plot_view is not None
    assert ctrl.winch_panel is window.winch_panel
    assert ctrl.winch_plot_view is window.winch_plot_view


def t_panel_stack_indices():
    # Winch panel/view were inserted mid-stack; every mode must map to its panel.
    assert window.panel_stack.count() == len(MODES), (
        window.panel_stack.count(), len(MODES))
    expected = {
        "Winch": window.winch_panel,
        "Calculate": window.calculate_panel,
        "Alter": window.alter_panel,
        "Piston Analysis": window.piston_analysis_panel,
        "Predict": window.predict_panel,
        "Trip Detector": window.trip_panel,
        "Piston Position": window.piston_panel,
    }
    for mode, panel in expected.items():
        window.set_mode(mode)
        app.processEvents()
        assert window.panel_stack.currentWidget() is panel, (
            f"{mode} -> {type(window.panel_stack.currentWidget()).__name__}")


def t_secondary_view_indices():
    window.show_secondary_view("winch")
    assert window.secondary_stack.currentWidget() is window.winch_plot_view
    window.show_secondary_view("piston_analysis")
    assert window.secondary_stack.currentWidget() is window.piston_analysis_view
    window.show_secondary_view("calculation")
    assert window.secondary_stack.currentWidget() is window.calculation_plot
    window.show_secondary_view("calibration_plot")
    assert window.secondary_stack.currentWidget() is window.calibration_plot
    window.show_secondary_view("trip")
    assert window.secondary_stack.currentWidget() is window.trip_plot
    window.show_secondary_view("predict")
    assert window.secondary_stack.currentWidget() is window.predict_plot_view


def t_mode_cycle():
    for mode in MODES:
        window.set_mode(mode)
        app.processEvents()
        assert window.get_current_mode() == mode, mode


def t_plot_item_property():
    # Winch plot view links its X axis to this integration-era plot widget.
    import pyqtgraph as pg
    assert isinstance(window.main_plot.plot_item, pg.PlotItem)
    window.winch_plot_view.set_x_link(window.main_plot.plot_item)


def t_plot_helpers_no_data():
    # Both replot paths used by the resolved restore branch must be safe
    # with no sensor data loaded.
    ctrl.sensor_data = None
    ctrl._plot_calculate_mode()
    ctrl._plot_winch_mode()


def t_sensor_plot_removals():
    # Integration-side clear path calls these; winch adds start_pen/seafloor.
    v = window.main_plot
    for name in ("remove_trip_line", "remove_start_core_line",
                 "remove_end_pen_line", "remove_pullout_line",
                 "remove_start_pen_line", "remove_seafloor_line",
                 "remove_piston_trace", "remove_smoothed_traces"):
        assert hasattr(v, name), name
        getattr(v, name)()


def t_restore_mode_branch():
    """The conflict resolution: mode choice + unconditional replot."""
    calls = []
    window.set_mode("View Data")
    app.processEvents()

    orig_calc, orig_winch = ctrl._plot_calculate_mode, ctrl._plot_winch_mode
    ctrl._plot_calculate_mode = lambda: calls.append("calc")
    ctrl._plot_winch_mode = lambda: calls.append("winch")
    try:
        src = _restore_tail_source()
        # winch restored -> Winch mode + winch replot
        exec_restore(src, restored=["winch alignment", "trip"])
        assert window.get_current_mode() == "Winch", window.get_current_mode()
        assert calls == ["winch"], calls

        calls.clear()
        # no winch -> Calculate mode + calculate replot (integration behaviour)
        exec_restore(src, restored=["trip", "calculations"])
        assert window.get_current_mode() == "Calculate", window.get_current_mode()
        assert calls == ["calc"], calls

        calls.clear()
        # already in Calculate: set_mode emits nothing, replot must still happen
        exec_restore(src, restored=["calculations"])
        assert window.get_current_mode() == "Calculate"
        assert calls == ["calc"], calls
    finally:
        ctrl._plot_calculate_mode = orig_calc
        ctrl._plot_winch_mode = orig_winch


def _restore_tail_source():
    return (
        "if main_window is not None and restored:\n"
        "    if 'winch alignment' in restored:\n"
        "        main_window.set_mode('Winch')\n"
        "        self._plot_winch_mode()\n"
        "    else:\n"
        "        main_window.set_mode('Calculate')\n"
        "        self._plot_calculate_mode()\n"
    )


def exec_restore(src, restored):
    exec(src, {}, {"main_window": window, "restored": restored, "self": ctrl})
    app.processEvents()


def t_restore_source_matches_smoke_copy():
    """Guard: the smoke test's copy of the branch matches the real source."""
    import inspect
    from sensor_tool.controllers.analysis_controller import AnalysisController
    src = inspect.getsource(AnalysisController.restore_from_db)
    assert "self.main_window.set_mode('Winch')" in src
    assert "self._plot_winch_mode()" in src
    assert "self.main_window.set_mode('Calculate')" in src
    assert "self._plot_calculate_mode()" in src
    assert "<<<<<<<" not in src


def t_no_conflict_markers():
    import subprocess
    out = subprocess.run(
        ["git", "grep", "-l", "-E", r"^(<<<<<<<|>>>>>>>) ", "--", "."],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert out.stdout.strip() == "", out.stdout


def t_winch_trip_detection():
    import numpy as np
    import pandas as pd
    from sensor_tool.domain.processing.winch_trip_detection import (
        WinchTripDetectionProcessor,
    )
    n = 600
    ts = pd.Series(pd.date_range("2024-01-01", periods=n, freq="s"))
    tension = np.concatenate([np.full(300, 5000.0), np.full(300, 1200.0)])

    res = WinchTripDetectionProcessor.detect_trip(
        tension, ts, "tension", edge_buffer=10, drop_threshold=1000.0,
    )
    assert res is not None, "expected a trip on the synthetic 3800-unit drop"
    assert res.trip_index == 300, res.trip_index
    assert abs(res.drop_magnitude - 3800.0) < 1e-6, res.drop_magnitude
    assert res.column == "tension"
    assert "Winch trip at index 300" in res.summary

    # Threshold above the drop finds nothing.
    assert WinchTripDetectionProcessor.detect_trip(
        tension, ts, "tension", edge_buffer=10, drop_threshold=1e6,
    ) is None

    # Search window excluding the drop finds nothing.
    assert WinchTripDetectionProcessor.detect_trip(
        tension, ts, "tension", edge_buffer=10, drop_threshold=1000.0,
        search_start=ts.iloc[350], search_end=ts.iloc[400],
    ) is None


def t_winch_loader_parameters():
    import numpy as np
    import pandas as pd
    from sensor_tool.persistence.winch_loader import (
        get_winch_parameters, datetime_to_epoch, timestamp_to_epoch,
    )
    ts = pd.date_range("2024-01-01", periods=10, freq="s")
    df = pd.DataFrame({
        "datetime": ts,
        "tension": np.linspace(0, 100, 10),
        "payout": np.linspace(0, 50, 10),
    })
    params = get_winch_parameters(df)
    assert "tension" in params and "payout" in params, params
    assert "datetime" not in params, params

    epochs = datetime_to_epoch(df)
    assert len(epochs) == 10
    assert abs(float(epochs[0]) - timestamp_to_epoch(ts[0])) < 1e-6


def t_winch_panel_widgets():
    p = window.winch_panel
    for attr in ("edge_buffer_spin", "drop_threshold_spin", "use_manual_radio",
                 "use_auto_radio", "winch_file_list", "column1_combo",
                 "second_window_check", "column2_combo",
                 "show_search_region_check", "log_widget"):
        assert hasattr(p, attr), attr
    p.set_winch_trip_status("smoke")
    p.set_alignment_status("smoke")
    p.set_parameters({"tension": None, "payout": None})


def t_persisted_columns():
    """Winch columns (winch side) and recoil_time_s (integration side) both kept."""
    import sensor_tool.persistence.analysis_results_io as io_mod
    import sensor_tool.controllers.analysis_controller as ctrl_mod
    io_src = open(io_mod.__file__).read()
    for col in ("winch_trip_index", "winch_time_offset_sec"):
        assert col in io_src, f"{col} missing from analysis_results_io"

    ctrl_src = open(ctrl_mod.__file__).read()
    assert ctrl_src.count('"result_recoil_time_s"') == 2, (
        "integration-side result_recoil_time_s save paths not intact")
    assert ctrl_src.count('"result_eff_trig_line"') == 2, (
        "integration-side result_eff_trig_line save paths not intact")
    for col in ("winch_trip_index", "winch_time_offset_sec"):
        assert col in ctrl_src, f"{col} missing from analysis_controller"


def _db_columns_written_by_controller():
    """Column names the controller sends to insert_result/update_result.

    insert_result builds its INSERT column list from the payload dict keys, so
    any key here that the schema lacks fails the whole save at runtime. The
    payloads are literal dicts assigned to flat_data/calc_flat, plus subscript
    assignments on flat_data, so they can be read statically.
    """
    import ast
    import sensor_tool.controllers.analysis_controller as ctrl_mod

    tree = ast.parse(open(ctrl_mod.__file__).read())
    targets = {"flat_data", "calc_flat"}
    columns = set()

    def is_target(node):
        return isinstance(node, ast.Name) and node.id in targets

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        lhs = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in lhs:
            if is_target(t) and isinstance(node.value, ast.Dict):
                columns.update(
                    k.value for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                )
            elif (isinstance(t, ast.Subscript) and is_target(t.value)
                  and isinstance(t.slice, ast.Constant)
                  and isinstance(t.slice.value, str)):
                columns.add(t.slice.value)

    return columns


def _sensor_analysis_table_source():
    src = open(os.path.join(REPO_ROOT, "prepare_db.py")).read()
    start = src.index("CREATE TABLE IF NOT EXISTS sensor_analysis_results")
    end = src.index("print(\"  ✓ sensor_analysis_results table ready\")")
    return src[start:end]


def _prepare_db_columns():
    """Columns prepare_db.py gives sensor_analysis_results (CREATE plus ALTER)."""
    import re
    body = _sensor_analysis_table_source()
    create_body = body[:body.index("ALTER TABLE")]
    # Column names are lowercase; the type that follows is uppercase. Anchoring
    # on that keeps SQL keywords out of the result.
    created = set(re.findall(
        r"^\s+([a-z_]+)\s+[A-Z]", create_body, re.MULTILINE))
    altered = set(re.findall(r"ADD COLUMN IF NOT EXISTS\s+([a-z_]+)", body))
    return created | altered


def t_save_columns_exist_in_schema():
    written = _db_columns_written_by_controller()
    schema = _prepare_db_columns()
    assert "result_recoil_max" in written, "payload extraction found nothing"
    assert "result_recoil_max" in schema, "schema extraction found nothing"
    # Anything that is not a plausible column name means a parse slip.
    assert all(c.islower() for c in schema), sorted(
        c for c in schema if not c.islower())
    missing = sorted(written - schema)
    assert not missing, (
        f"controller writes columns prepare_db.py never creates: {missing}")


def t_migrations_cover_added_columns():
    """Every column added after the original CREATE TABLE needs a migration too,
    for databases that were prepared before it existed."""
    import re
    mig_dir = os.path.join(REPO_ROOT, "migrations")
    sql = "".join(
        open(os.path.join(mig_dir, f)).read() for f in sorted(os.listdir(mig_dir))
    )
    migrated = set(re.findall(r"ADD COLUMN IF NOT EXISTS\s+([a-z_]+)", sql))

    altered = set(re.findall(
        r"ADD COLUMN IF NOT EXISTS\s+([a-z_]+)", _sensor_analysis_table_source()))

    assert altered, "prepare_db.py has no backfill ALTER block"
    missing = sorted(altered - migrated)
    assert not missing, f"columns backfilled by prepare_db but not migrated: {missing}"


def t_migration_example_present():
    path = os.path.join(
        REPO_ROOT, "migrations",
        "001_add_winch_columns_to_sensor_analysis_results.sql.example",
    )
    sql = open(path).read()
    for col in ("winch_trip_index", "winch_time_offset_sec"):
        assert col in sql, col


check("window title preserved (Sensorius)", t_window_title)
check("Predict mode wired into main window", t_predict_mode_registered)
check("Winch mode wired into main window", t_winch_mode_registered)
check("panel stack index mapping intact", t_panel_stack_indices)
check("secondary view index mapping intact", t_secondary_view_indices)
check("cycle through every mode", t_mode_cycle)
check("main_plot.plot_item + winch x-link", t_plot_item_property)
check("replot helpers safe without data", t_plot_helpers_no_data)
check("sensor plot overlay removal API", t_sensor_plot_removals)
check("restore mode-selection branch (merge resolution)", t_restore_mode_branch)
check("restore source matches resolution", t_restore_source_matches_smoke_copy)
check("no leftover conflict markers", t_no_conflict_markers)
check("winch trip detection on synthetic data", t_winch_trip_detection)
check("winch loader parameter/epoch helpers", t_winch_loader_parameters)
check("winch panel widgets present", t_winch_panel_widgets)
check("winch + recoil_time persisted columns", t_persisted_columns)
check("winch migration example present", t_migration_example_present)
check("every saved column exists in prepare_db schema", t_save_columns_exist_in_schema)
check("added columns have migrations", t_migrations_cover_added_columns)

print()
if failures:
    print(f"SMOKE TEST FAILED: {len(failures)} failure(s): {failures}")
    sys.exit(1)
print("SMOKE TEST PASSED")
sys.exit(0)
