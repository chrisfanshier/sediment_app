"""
CreateCalibrationPanel - Control panel for multi-cast calibration workflow.

Load casts, select regions, collect statistics, generate calibration file.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QGridLayout,
    QSpinBox, QDoubleSpinBox, QLineEdit, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Signal

from .base_panel import BaseModePanel
from ..widgets.log_widget import LogWidget
from ..widgets.selection_controls import SelectionControls


class CreateCalibrationPanel(BaseModePanel):
    """
    Panel for the Create Calibration mode.

    Signals:
        load_cast_requested(str): User selected a CSV file to load as a cast.
        add_statistics_requested: Add stats from current selection.
        generate_calibration_requested: Generate calibration from collected stats.
        save_calibration_requested: Save generated calibration.
        selection_mode_changed(bool): Selection mode toggled.
        clear_selection_requested: Clear selection.
        process_cast_requested: Process the loaded cast.
    """

    load_cast_requested = Signal(str)
    add_statistics_requested = Signal()
    generate_calibration_requested = Signal()
    save_calibration_requested = Signal(str)
    selection_mode_changed = Signal(bool)
    clear_selection_requested = Signal()
    process_cast_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # -- Info box --
        info_group = QGroupBox("Instructions")
        info_layout = QVBoxLayout()
        info_label = QLabel(
            "This mode is for developing depth calibrations from\n"
            "multiple test casts.\n\n"
            "Workflow:\n"
            "1. Load a test cast\n"
            "2. Select a stable depth region\n"
            "3. Click 'Add Statistics' to collect data\n"
            "4. Repeat with different casts/regions\n"
            "5. Generate and save calibration file\n\n"
            "Use 'Depth Offset' mode to apply calibrations."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(
            "QLabel { background-color: #e3f2fd; padding: 8px; border-radius: 4px; }"
        )
        info_layout.addWidget(info_label)
        info_group.setLayout(info_layout)
        self._layout.addWidget(info_group)

        # -- Current Cast --
        cast_group = QGroupBox("Current Cast")
        cast_layout = QVBoxLayout()
        self.cast_label = QLabel("No cast loaded")
        self.cast_label.setWordWrap(True)
        cast_layout.addWidget(self.cast_label)

        load_btn = QPushButton("Load Cast")
        load_btn.clicked.connect(self._on_load_cast)
        cast_layout.addWidget(load_btn)

        cast_group.setLayout(cast_layout)
        self._layout.addWidget(cast_group)

        # -- Sensor Configuration --
        sensor_group = QGroupBox("Sensor Configuration")
        sensor_layout = QGridLayout()

        sensor_layout.addWidget(QLabel("Number of Sensors:"), 0, 0)
        self.num_sensors_spin = QSpinBox()
        self.num_sensors_spin.setRange(2, 4)
        self.num_sensors_spin.setValue(3)
        sensor_layout.addWidget(self.num_sensors_spin, 0, 1)

        sensor_layout.addWidget(QLabel("Datetime Col:"), 1, 0)
        self.datetime_col_edit = QLineEdit("datetime")
        sensor_layout.addWidget(self.datetime_col_edit, 1, 1)

        # Sensor pattern fields (serial numbers to match columns)
        self.sensor_entries: list[QLineEdit] = []
        default_sensors = ["230405", "230406", "236222", "236223"]
        for i in range(4):
            label = QLabel(f"Pattern {i+1}:")
            sensor_layout.addWidget(label, 2 + i, 0)
            entry = QLineEdit(default_sensors[i])
            sensor_layout.addWidget(entry, 2 + i, 1)
            self.sensor_entries.append(entry)

        sensor_group.setLayout(sensor_layout)
        self._layout.addWidget(sensor_group)

        # -- Processing Parameters --
        params_group = QGroupBox("Processing Parameters")
        params_layout = QGridLayout()

        params_layout.addWidget(QLabel("Skip Rows:"), 0, 0)
        self.skip_rows_spin = QSpinBox()
        self.skip_rows_spin.setRange(0, 1000)
        self.skip_rows_spin.setValue(16)
        params_layout.addWidget(self.skip_rows_spin, 0, 1)

        params_layout.addWidget(QLabel("Min Depth (m):"), 1, 0)
        self.min_depth_spin = QDoubleSpinBox()
        self.min_depth_spin.setRange(0, 99999)
        self.min_depth_spin.setValue(0.0)
        self.min_depth_spin.setDecimals(2)
        params_layout.addWidget(self.min_depth_spin, 1, 1)

        params_layout.addWidget(QLabel("Max Depth (m):"), 2, 0)
        self.max_depth_spin = QDoubleSpinBox()
        self.max_depth_spin.setRange(0, 99999)
        self.max_depth_spin.setValue(9999.0)
        self.max_depth_spin.setDecimals(2)
        params_layout.addWidget(self.max_depth_spin, 2, 1)

        params_layout.addWidget(QLabel("Trim Rows:"), 3, 0)
        self.trim_rows_spin = QSpinBox()
        self.trim_rows_spin.setRange(0, 10000)
        self.trim_rows_spin.setValue(200)
        params_layout.addWidget(self.trim_rows_spin, 3, 1)

        params_layout.addWidget(QLabel("Smooth Window:"), 4, 0)
        self.smooth_window_spin = QSpinBox()
        self.smooth_window_spin.setRange(1, 1000)
        self.smooth_window_spin.setValue(100)
        params_layout.addWidget(self.smooth_window_spin, 4, 1)

        process_btn = QPushButton("Process Cast")
        process_btn.clicked.connect(self.process_cast_requested.emit)
        params_layout.addWidget(process_btn, 5, 0, 1, 2)

        params_group.setLayout(params_layout)
        self._layout.addWidget(params_group)

        # -- Selection --
        self.selection_controls = SelectionControls("Selection")
        self.selection_controls.selection_mode_changed.connect(
            self.selection_mode_changed.emit
        )
        self.selection_controls.clear_requested.connect(
            self.clear_selection_requested.emit
        )
        self._layout.addWidget(self.selection_controls)

        # -- Add Statistics --
        stats_group = QGroupBox("Collect Statistics")
        stats_layout = QVBoxLayout()

        add_btn = QPushButton("Add Statistics from Selection")
        add_btn.clicked.connect(self.add_statistics_requested.emit)
        stats_layout.addWidget(add_btn)

        self.stats_count_label = QLabel("0 data points collected")
        stats_layout.addWidget(self.stats_count_label)

        stats_group.setLayout(stats_layout)
        self._layout.addWidget(stats_group)

        # -- Generate Calibration --
        gen_group = QGroupBox("Generate Calibration")
        gen_layout = QVBoxLayout()

        gen_btn = QPushButton("Generate Calibration File")
        gen_btn.clicked.connect(self.generate_calibration_requested.emit)
        gen_layout.addWidget(gen_btn)

        save_btn = QPushButton("Save Calibration")
        save_btn.clicked.connect(self._on_save_calibration)
        gen_layout.addWidget(save_btn)

        self.calibration_summary_label = QLabel("")
        self.calibration_summary_label.setWordWrap(True)
        gen_layout.addWidget(self.calibration_summary_label)

        gen_group.setLayout(gen_layout)
        self._layout.addWidget(gen_group)

        # -- Log --
        self.log_widget = LogWidget("Log", max_height=150)
        self._layout.addWidget(self.log_widget)

        self._finish_layout()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def update_cast_info(self, filename: str, sensors: int, rows: int):
        self.cast_label.setText(f"File: {filename}\nSensors: {sensors}  |  Rows: {rows:,}")

    def update_stats_count(self, count: int):
        self.stats_count_label.setText(f"{count} data points collected")

    def update_calibration_summary(self, text: str):
        self.calibration_summary_label.setText(text)

    def get_sensor_patterns(self) -> list[str]:
        n = self.num_sensors_spin.value()
        return [self.sensor_entries[i].text() for i in range(n)]

    def get_processing_params(self) -> dict:
        return {
            'skip_rows': self.skip_rows_spin.value(),
            'min_depth': self.min_depth_spin.value(),
            'max_depth': self.max_depth_spin.value(),
            'trim_rows': self.trim_rows_spin.value(),
            'smooth_window': self.smooth_window_spin.value(),
            'datetime_col': self.datetime_col_edit.text(),
            'num_sensors': self.num_sensors_spin.value(),
        }

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _on_load_cast(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select CTD CSV File", "",
            "CSV Files (*.csv);;All Files (*)"
        )
        if file_path:
            self.load_cast_requested.emit(file_path)

    def _on_save_calibration(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Offset Calibration", "",
            "JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            self.save_calibration_requested.emit(file_path)
