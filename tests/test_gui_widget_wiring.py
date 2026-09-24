"""Headless GUI regression tests for two bug classes that only surface on use.

Both classes escaped review because nothing fails at import or construction
time:

1. A Qt signal connected with the wrong argument arity raises only when the
   widget is actually operated. Connecting ``QCheckBox.toggled`` (which always
   emits a bool) straight to a zero-argument ``Signal.emit`` raised a TypeError
   on every click, and because the emit itself raised, the signal never
   propagated -- so the handler silently never ran.

2. A plot that omits ``setDownsampling``/``setClipToView`` renders dense traces
   at full resolution. That cost seconds per repaint and hung the UI once the
   global OpenGL viewport was removed.
"""
import importlib
import os
import pkgutil
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QRadioButton,
    QSpinBox,
)

# sensor_tool reaches the legacy streamlit-based utils through its winch
# loader, so only sensor_standalone is importable in a bare test environment.
# The gui/views trees are kept byte-identical between the two apps, and
# test_view_trees_stay_identical below enforces that, which is what lets the
# sensor_standalone results carry over to sensor_tool.
APP = "sensor_standalone"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _panel_classes():
    panels_pkg = importlib.import_module(f"{APP}.gui.panels")
    found = []
    for mod_info in pkgutil.iter_modules(panels_pkg.__path__):
        if mod_info.name == "base_panel":
            continue
        mod = importlib.import_module(f"{APP}.gui.panels.{mod_info.name}")
        for attr in dir(mod):
            obj = getattr(mod, attr)
            if (
                isinstance(obj, type)
                and attr.endswith("Panel")
                and obj.__module__ == mod.__name__
            ):
                found.append(obj)
    return sorted(found, key=lambda c: c.__name__)


def _toggle(child):
    """Operate one control the way a user would. Returns True if exercised."""
    if isinstance(child, (QCheckBox, QRadioButton)):
        child.setChecked(not child.isChecked())
        child.setChecked(not child.isChecked())
        return True
    if isinstance(child, QComboBox) and child.count() > 1:
        original = child.currentIndex()
        child.setCurrentIndex((original + 1) % child.count())
        child.setCurrentIndex(original)
        return True
    if isinstance(child, (QSpinBox, QDoubleSpinBox)):
        original = child.value()
        child.setValue(min(original + child.singleStep(), child.maximum()))
        child.setValue(original)
        return True
    return False


@pytest.mark.parametrize("panel_cls", _panel_classes(), ids=lambda c: c.__name__)
def test_panel_controls_operate_without_raising(qapp, panel_cls, monkeypatch):
    """Toggling any control must not raise, e.g. from a signal arity mismatch.

    Qt routes slot exceptions through sys.excepthook rather than letting them
    propagate out of setChecked, so failures are captured there.
    """
    raised = []
    monkeypatch.setattr(sys, "excepthook", lambda t, e, tb: raised.append(f"{t.__name__}: {e}"))

    panel = panel_cls()
    for child in panel.findChildren(object):
        if _toggle(child):
            qapp.processEvents()

    qapp.processEvents()
    assert not raised, f"{panel_cls.__name__} raised on control use: {raised}"


def test_predict_panel_plot_options_emit_overlay_changed(qapp, monkeypatch):
    """The three Predict plot-option checkboxes must drive overlay_changed.

    Regression test for the TypeError that both spammed the console and
    stopped the live plot refresh from ever running.
    """
    raised = []
    monkeypatch.setattr(sys, "excepthook", lambda t, e, tb: raised.append(f"{t.__name__}: {e}"))

    from sensor_standalone.gui.panels.predict_panel import PredictPanel

    panel = PredictPanel()
    fired = []
    panel.overlay_changed.connect(lambda: fired.append(1))

    for name in ("show_piston_check", "show_trigger_check", "overlay_actual_check"):
        box = getattr(panel, name)
        before = len(fired)
        box.setChecked(not box.isChecked())
        qapp.processEvents()
        assert len(fired) == before + 1, (
            f"toggling {name} did not emit overlay_changed (errors: {raised})"
        )

    assert not raised, f"toggling plot options raised: {raised}"


# Plots whose traces are always sparse, so downsampling would be a no-op.
# CalculationPlotView draws a geometry diagram: two-point cap lines, bars and
# text labels.
SPARSE_PLOT_VIEWS = {"CalculationPlotView"}


def test_dense_plots_set_downsampling_and_clip(qapp):
    """Every plot that can receive a full-resolution trace must be guarded."""
    import pyqtgraph as pg

    guards = {}
    created = []

    orig_ds = pg.PlotItem.setDownsampling
    orig_clip = pg.PlotItem.setClipToView
    orig_init = pg.PlotItem.__init__

    def tracked_ds(self, *a, **k):
        guards.setdefault(id(self), set()).add("downsample")
        return orig_ds(self, *a, **k)

    def tracked_clip(self, *a, **k):
        guards.setdefault(id(self), set()).add("clip")
        return orig_clip(self, *a, **k)

    def tracked_init(self, *a, **k):
        orig_init(self, *a, **k)
        created.append(self)

    pg.PlotItem.setDownsampling = tracked_ds
    pg.PlotItem.setClipToView = tracked_clip
    pg.PlotItem.__init__ = tracked_init
    try:
        views_pkg = importlib.import_module(f"{APP}.gui.views")
        unguarded = []
        for mod_info in pkgutil.iter_modules(views_pkg.__path__):
            mod = importlib.import_module(f"{APP}.gui.views.{mod_info.name}")
            for attr in sorted(dir(mod)):
                obj = getattr(mod, attr)
                if not (
                    isinstance(obj, type)
                    and attr.endswith("View")
                    and obj.__module__ == mod.__name__
                ):
                    continue
                if attr in SPARSE_PLOT_VIEWS:
                    continue
                created.clear()
                try:
                    obj()
                except Exception:
                    continue  # needs constructor args; not covered here
                for plot in created:
                    missing = {"downsample", "clip"} - guards.get(id(plot), set())
                    if missing:
                        unguarded.append(f"{attr} missing {sorted(missing)}")

        assert not unguarded, (
            "dense plots lack render guards, which can hang the UI: "
            f"{unguarded}"
        )
    finally:
        pg.PlotItem.setDownsampling = orig_ds
        pg.PlotItem.setClipToView = orig_clip
        pg.PlotItem.__init__ = orig_init


def test_antialiasing_stays_off_globally(qapp):
    """Software antialiasing of dense traces costs seconds per repaint."""
    import pyqtgraph as pg

    importlib.import_module(f"{APP}.gui.views.sensor_plot_view")
    assert pg.getConfigOption("antialias") is False
    assert pg.getConfigOption("useOpenGL") is False


def test_view_trees_stay_identical():
    """sensor_tool and sensor_standalone must share identical plot views.

    The GUI audits above import only sensor_standalone; this equality is what
    makes those results apply to sensor_tool too.
    """
    import filecmp

    standalone = os.path.join(REPO_ROOT, "sensor_standalone", "gui", "views")
    tool = os.path.join(REPO_ROOT, "sensor_tool", "gui", "views")
    names = sorted(f for f in os.listdir(standalone) if f.endswith(".py"))

    differing = [
        name
        for name in names
        if os.path.exists(os.path.join(tool, name))
        and not filecmp.cmp(
            os.path.join(standalone, name), os.path.join(tool, name), shallow=False
        )
    ]
    assert not differing, f"plot views drifted between apps: {differing}"
