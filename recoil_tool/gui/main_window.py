"""
MainWindow — top-level window for the recoil fitting tool.

Layout:
    ┌──────────────────────────────────────────────────────────┐
    │ [Cruise ▾] [Core ▾] [Load]                              │  ← Toolbar
    ├───────────────────────┬──────────────────────────────────┤
    │                       │                                  │
    │  DeploymentPanel      │  RecoilPlotView                  │
    │                       │  (depth trace + trip marker;     │
    │  ResultsPanel         │   diagnostic panels after fit)   │
    │                       │                                  │
    └───────────────────────┴──────────────────────────────────┘
    │  Status bar                                              │
    └──────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QComboBox, QToolBar,
    QPushButton, QLabel, QMessageBox, QSizePolicy,
)

from ..gui.panels.deployment_panel import DeploymentPanel
from ..gui.panels.results_panel import ResultsPanel
from ..gui.views.recoil_plot_view import RecoilPlotView
from ..controllers.recoil_controller import RecoilController


class MainWindow(QMainWindow):
    """Recoil tool main window."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Recoil Fitting Tool")
        self.resize(1400, 900)

        # Panels
        self.deployment_panel = DeploymentPanel()
        self.results_panel = ResultsPanel()
        self.plot_view = RecoilPlotView()

        # Controller
        self.controller = RecoilController(
            deployment_panel=self.deployment_panel,
            results_panel=self.results_panel,
            plot_view=self.plot_view,
            main_window=self,
        )

        # DB dropdown state
        self._cruises: list[dict] = []
        self._cores: list[dict] = []

        self._build_toolbar()
        self._build_central()
        self._build_status_bar()

        # Load cruise list at startup
        self._populate_cruises()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        tb.addWidget(QLabel("  Cruise: "))
        self.cruise_combo = QComboBox()
        self.cruise_combo.setMinimumWidth(200)
        self.cruise_combo.currentIndexChanged.connect(self._on_cruise_changed)
        tb.addWidget(self.cruise_combo)

        tb.addWidget(QLabel("  Core: "))
        self.core_combo = QComboBox()
        self.core_combo.setMinimumWidth(200)
        tb.addWidget(self.core_combo)

        tb.addSeparator()

        self.load_btn = QPushButton("Load")
        self.load_btn.setMinimumWidth(70)
        self.load_btn.clicked.connect(self._on_load_clicked)
        tb.addWidget(self.load_btn)

    def _build_central(self):
        outer = QSplitter(Qt.Horizontal)
        self.setCentralWidget(outer)

        # Left: stacked control panels
        left = QSplitter(Qt.Vertical)
        left.addWidget(self.deployment_panel)
        left.addWidget(self.results_panel)
        left.setSizes([350, 350])
        left.setMinimumWidth(260)
        left.setMaximumWidth(380)
        outer.addWidget(left)

        # Right: plot
        outer.addWidget(self.plot_view)
        outer.setSizes([320, 1080])

    def _build_status_bar(self):
        self.statusBar().showMessage("Ready — select a cruise and core to begin.")

    # ------------------------------------------------------------------
    # Populate dropdowns
    # ------------------------------------------------------------------

    def _populate_cruises(self):
        self.cruise_combo.clear()
        self.cruise_combo.addItem("— select cruise —", None)
        try:
            self._cruises = self.controller.fetch_cruises()
            for c in self._cruises:
                label = c['cruise_name']
                if c.get('vessel_name'):
                    label = f"{c['cruise_name']}  ({c['vessel_name']})"
                self.cruise_combo.addItem(label, c['cruise_id'])
        except Exception as exc:
            self.statusBar().showMessage(f"DB error: {exc}")

    def _on_cruise_changed(self, _index: int):
        cruise_id = self.cruise_combo.currentData()
        self.core_combo.clear()
        self.core_combo.addItem("— select core —", None)
        self._cores = []
        if cruise_id is None:
            return
        try:
            self._cores = self.controller.fetch_cores(cruise_id)
            for c in self._cores:
                self.core_combo.addItem(c['core_name'], c['core_id'])
        except Exception as exc:
            self.statusBar().showMessage(f"DB error: {exc}")

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def _on_load_clicked(self):
        core_id = self.core_combo.currentData()
        if core_id is None:
            QMessageBox.warning(self, "No Core", "Please select a core first.")
            return

        # Find matching core_info dict
        core_info = next(
            (c for c in self._cores if c['core_id'] == core_id), {}
        )
        self.statusBar().showMessage(
            f"Loading {core_info.get('core_name', core_id)}…"
        )
        self.controller.load_core(core_id, core_info)
