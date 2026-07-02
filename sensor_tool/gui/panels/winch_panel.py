"""
WinchPanel - Control panel for the "Winch" mode.

Provides auto (core-overlap) and manual winch file selection, plus
configuration for one or two winch plot windows.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QPushButton, QListWidget, QAbstractItemView,
    QRadioButton, QButtonGroup,
)
from PySide6.QtCore import Signal

from .base_panel import BaseModePanel
from ..widgets.log_widget import LogWidget


class WinchPanel(BaseModePanel):
    """
    Panel for Winch mode.

    Signals
    -------
    reload_requested
        User clicked reload or changed data-source settings.
    plot_settings_changed
        Column or window-count selection changed.
    """

    reload_requested = Signal()
    plot_settings_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._winch_files: list[dict] = []
        self._auto_file_names: list[str] = []
        self._parameters: list[str] = []

        # -- Data source -------------------------------------------------
        source_group = QGroupBox('Winch Data Source')
        source_layout = QVBoxLayout()

        self.auto_status_label = QLabel('Auto: no core selected')
        self.auto_status_label.setWordWrap(True)
        source_layout.addWidget(self.auto_status_label)

        self.use_auto_radio = QRadioButton('Use auto (core overlap)')
        self.use_manual_radio = QRadioButton('Use manual file selection')
        self.use_auto_radio.setChecked(True)
        source_btn_group = QButtonGroup(self)
        source_btn_group.addButton(self.use_auto_radio)
        source_btn_group.addButton(self.use_manual_radio)

        mode_row = QHBoxLayout()
        mode_row.addWidget(self.use_auto_radio)
        mode_row.addWidget(self.use_manual_radio)
        mode_row.addStretch()
        source_layout.addLayout(mode_row)

        self.manual_group_box = QGroupBox('Manual Selection')
        manual_layout = QVBoxLayout()

        self.winch_file_list = QListWidget()
        self.winch_file_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.winch_file_list.setMinimumHeight(120)
        self.winch_file_list.setEnabled(False)
        manual_layout.addWidget(QLabel('Winch files (cruise):'))
        manual_layout.addWidget(self.winch_file_list)

        self.manual_group_box.setLayout(manual_layout)
        source_layout.addWidget(self.manual_group_box)

        btn_row = QHBoxLayout()
        self.reload_btn = QPushButton('Reload Winch Data')
        btn_row.addWidget(self.reload_btn)
        btn_row.addStretch()
        source_layout.addLayout(btn_row)

        source_group.setLayout(source_layout)
        self._layout.addWidget(source_group)

        # -- Plot windows ------------------------------------------------
        plot_group = QGroupBox('Winch Plots')
        plot_layout = QVBoxLayout()

        row1 = QHBoxLayout()
        row1.addWidget(QLabel('Window 1 column:'))
        self.column1_combo = QComboBox()
        self.column1_combo.setMinimumWidth(180)
        row1.addWidget(self.column1_combo)
        row1.addStretch()
        plot_layout.addLayout(row1)

        self.second_window_check = QCheckBox('Show second window')
        plot_layout.addWidget(self.second_window_check)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel('Window 2 column:'))
        self.column2_combo = QComboBox()
        self.column2_combo.setMinimumWidth(180)
        self.column2_combo.setEnabled(False)
        row2.addWidget(self.column2_combo)
        row2.addStretch()
        plot_layout.addLayout(row2)

        plot_group.setLayout(plot_layout)
        self._layout.addWidget(plot_group)

        # -- Log ---------------------------------------------------------
        self.log_widget = LogWidget()
        self._layout.addWidget(self.log_widget)

        self._finish_layout()

        self.reload_btn.clicked.connect(self.reload_requested.emit)
        self.use_auto_radio.toggled.connect(self._on_source_mode_changed)
        self.use_manual_radio.toggled.connect(self._on_source_mode_changed)
        self.winch_file_list.itemSelectionChanged.connect(self.reload_requested.emit)
        self.column1_combo.currentTextChanged.connect(self.plot_settings_changed.emit)
        self.column2_combo.currentTextChanged.connect(self.plot_settings_changed.emit)
        self.second_window_check.toggled.connect(self._on_second_window_toggled)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_cruise_winch_files(self, files: list[dict]) -> None:
        """Populate the manual file list for the current cruise."""
        self._winch_files = files
        self.winch_file_list.blockSignals(True)
        self.winch_file_list.clear()
        for f in files:
            label = f['file_name']
            if f.get('start_time') is not None:
                label += f"  ({f['start_time']} – {f['end_time']})"
            self.winch_file_list.addItem(label)
        self.winch_file_list.blockSignals(False)

    def set_auto_status(
        self,
        file_names: list[str],
        has_data: bool,
        core_name: str = '',
    ) -> None:
        """Update the auto-load status readout."""
        self._auto_file_names = file_names
        if not core_name:
            self.auto_status_label.setText('Auto: no core selected')
            return
        if has_data and file_names:
            files_str = ', '.join(file_names)
            self.auto_status_label.setText(
                f'Auto ({core_name}): {len(file_names)} file(s) — {files_str}'
            )
        else:
            self.auto_status_label.setText(
                f'Auto ({core_name}): no overlapping winch files found'
            )

    def set_parameters(self, params: list[str]) -> None:
        """Refresh column dropdowns."""
        self._parameters = params
        for combo, current in (
            (self.column1_combo, self.column1_combo.currentText()),
            (self.column2_combo, self.column2_combo.currentText()),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(params)
            if current in params:
                combo.setCurrentText(current)
            elif params:
                combo.setCurrentIndex(0)
            combo.blockSignals(False)

    def uses_manual_selection(self) -> bool:
        return self.use_manual_radio.isChecked()

    def get_selected_winch_file_ids(self) -> list[int]:
        ids: list[int] = []
        for item in self.winch_file_list.selectedItems():
            row = self.winch_file_list.row(item)
            if 0 <= row < len(self._winch_files):
                ids.append(self._winch_files[row]['winch_file_id'])
        return ids

    def get_column_1(self) -> Optional[str]:
        text = self.column1_combo.currentText()
        return text or None

    def get_column_2(self) -> Optional[str]:
        text = self.column2_combo.currentText()
        return text or None

    def show_second_window(self) -> bool:
        return self.second_window_check.isChecked()

    def update_file_info(self, text: str) -> None:
        pass  # reserved for parity with other panels

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_source_mode_changed(self, _checked: bool = False) -> None:
        manual = self.uses_manual_selection()
        self.winch_file_list.setEnabled(manual)
        self.reload_requested.emit()

    def _on_second_window_toggled(self, checked: bool) -> None:
        self.column2_combo.setEnabled(checked)
        self.plot_settings_changed.emit()
