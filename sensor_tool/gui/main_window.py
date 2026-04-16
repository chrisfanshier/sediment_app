"""
MainWindow - The top-level application window.

Layout:
    ┌──────────────────────────────────────────┐
    │  [Mode Selector ▾]  [Load File]  [About] │  ← Toolbar
    ├─────────────────┬────────────────────────┤
    │                 │                        │
    │  Control Panel  │  Main Plot             │
    │  (QStacked)     │                        │
    │                 │                        │
    │                 ├────────────────────────┤
    │                 │  Secondary View        │
    │                 │  (velocity / stats)    │
    │                 │                        │
    └─────────────────┴────────────────────────┘
    │  Status bar                              │
    └──────────────────────────────────────────┘
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QComboBox, QSplitter, QStackedWidget,
    QToolBar, QLabel, QFileDialog, QSizePolicy, QVBoxLayout,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction

from ..gui.views.sensor_plot_view import SensorPlotView
from ..gui.views.velocity_plot_view import HeavePlotView
from ..gui.views.statistics_table import StatisticsTableView
from ..gui.views.trip_plot_view import TripPlotView
from ..gui.views.calculation_plot_view import CalculationPlotView
from ..gui.panels.view_data_panel import ViewDataPanel
from ..gui.panels.depth_offset_panel import DepthOffsetPanel
from ..gui.panels.time_offset_panel import TimeOffsetPanel
from ..gui.panels.create_calibration_panel import CreateCalibrationPanel
from ..gui.panels.trip_detector_panel import TripDetectorPanel
from ..gui.panels.piston_position_panel import PistonPositionPanel
from ..gui.panels.calculate_panel import CalculatePanel
from ..controllers.analysis_controller import AnalysisController

MODES = ['View Data', 'Depth Offset', 'Time Offset', 'Create Calibration',
         'Trip Detector', 'Piston Position', 'Calculate']


class MainWindow(QMainWindow):
    """Application main window with mode-based panel switching."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sensor Alignment Tool v2.0")
        self.resize(1600, 1000)

        # Controller
        self.controller = AnalysisController()
        self.controller.main_window = self

        self._build_toolbar()
        self._build_central()
        self._build_status_bar()

        # Wire everything
        self.controller.connect_signals()

        # Set initial mode
        self.mode_combo.setCurrentIndex(0)
        self._on_mode_changed(MODES[0])

    # ==================================================================
    # Construction
    # ==================================================================

    def _build_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)

        toolbar.addWidget(QLabel("  Mode: "))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(MODES)
        self.mode_combo.setMinimumWidth(200)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        toolbar.addWidget(self.mode_combo)

        toolbar.addSeparator()

        load_action = QAction("Load CSV…", self)
        load_action.triggered.connect(self._on_load_file)
        toolbar.addAction(load_action)

        toolbar.addSeparator()

        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        toolbar.addAction(about_action)

    def _build_central(self):
        # -- Control panels (left) --
        self.panel_stack = QStackedWidget()

        self.view_panel = ViewDataPanel()
        self.depth_panel = DepthOffsetPanel()
        self.time_panel = TimeOffsetPanel()
        self.calibration_panel = CreateCalibrationPanel()
        self.trip_panel = TripDetectorPanel()
        self.piston_panel = PistonPositionPanel()
        self.calculate_panel = CalculatePanel()

        self.panel_stack.addWidget(self.view_panel)      # 0
        self.panel_stack.addWidget(self.depth_panel)      # 1
        self.panel_stack.addWidget(self.time_panel)       # 2
        self.panel_stack.addWidget(self.calibration_panel) # 3
        self.panel_stack.addWidget(self.trip_panel)       # 4
        self.panel_stack.addWidget(self.piston_panel)     # 5
        self.panel_stack.addWidget(self.calculate_panel)  # 6

        self.panel_stack.setMinimumWidth(400)
        self.panel_stack.setMaximumWidth(550)

        # -- Main plot --
        self.main_plot = SensorPlotView()

        # -- Secondary views (bottom-right) --
        self.heave_plot = HeavePlotView()
        self.statistics_table = StatisticsTableView()
        self.trip_plot = TripPlotView()
        self.calculation_plot = CalculationPlotView()

        self.secondary_stack = QStackedWidget()
        self.secondary_stack.addWidget(self.heave_plot)       # 0
        self.secondary_stack.addWidget(self.statistics_table) # 1
        self.secondary_stack.addWidget(self.trip_plot)        # 2
        self.secondary_stack.addWidget(self.calculation_plot) # 3
        self.secondary_stack.setVisible(False)

        # -- Right splitter (main plot + secondary) --
        self.right_splitter = QSplitter(Qt.Vertical)
        self.right_splitter.addWidget(self.main_plot)
        self.right_splitter.addWidget(self.secondary_stack)
        self.right_splitter.setStretchFactor(0, 3)
        self.right_splitter.setStretchFactor(1, 1)

        # -- Main splitter (panels + plots) --
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.addWidget(self.panel_stack)
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)

        self.setCentralWidget(self.main_splitter)

        # -- Assign to controller --
        self.controller.main_plot = self.main_plot
        self.controller.heave_plot = self.heave_plot
        self.controller.statistics_table = self.statistics_table
        self.controller.trip_plot = self.trip_plot
        self.controller.calculation_plot = self.calculation_plot
        self.controller.view_panel = self.view_panel
        self.controller.depth_panel = self.depth_panel
        self.controller.time_panel = self.time_panel
        self.controller.calibration_panel = self.calibration_panel
        self.controller.trip_panel = self.trip_panel
        self.controller.piston_panel = self.piston_panel
        self.controller.calculate_panel = self.calculate_panel

    def _build_status_bar(self):
        self.statusBar().showMessage("Ready")

    # ==================================================================
    # Mode management
    # ==================================================================

    def _on_mode_changed(self, mode_name: str):
        idx = MODES.index(mode_name) if mode_name in MODES else 0
        self.panel_stack.setCurrentIndex(idx)
        self.controller.on_mode_changed(mode_name)
        self.statusBar().showMessage(f"Mode: {mode_name}")

    def get_current_mode(self) -> str:
        return self.mode_combo.currentText()

    def show_secondary_view(self, view_type: str):
        """Show the secondary view area (velocity, statistics, or trip)."""
        if view_type == 'heave':
            self.secondary_stack.setCurrentIndex(0)
        elif view_type == 'statistics':
            self.secondary_stack.setCurrentIndex(1)
        elif view_type == 'trip':
            self.secondary_stack.setCurrentIndex(2)
        elif view_type == 'calculation':
            self.secondary_stack.setCurrentIndex(3)
        self.secondary_stack.setVisible(True)

    def hide_secondary_view(self):
        self.secondary_stack.setVisible(False)

    # ==================================================================
    # Toolbar actions
    # ==================================================================

    def _on_load_file(self):
        """Load CSV via toolbar button - delegates to current mode."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open CSV File", "",
            "CSV Files (*.csv);;All Files (*)"
        )
        if not file_path:
            return

        mode = self.get_current_mode()
        if mode == 'Create Calibration':
            self.calibration_panel.load_cast_requested.emit(file_path)
        else:
            self.controller.load_export_csv(file_path)

    def _show_about(self):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.about(
            self,
            "Sensor Alignment Tool",
            "Sensor Alignment Tool v2.0\n\n"
            "Multi-sensor depth comparison, calibration,\n"
            "and time-offset correction tool.\n\n"
            "Built with PySide6 + pyqtgraph."
        )
