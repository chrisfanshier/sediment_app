"""
RestoreResultsDialog — picker for selecting a saved sensor_analysis_results row.

Shows a list of all saved results for the current core (newest first).
The user can select one and click OK, or Cancel to abort.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QDialogButtonBox, QGroupBox,
)
from PySide6.QtCore import Qt


def _section_summary(row: dict) -> str:
    """Build a short string listing which analysis sections were saved."""
    params = row.get('params') or {}
    parts = []
    if 'depth_offset' in params:
        parts.append('depth')
    if 'time_offset' in params:
        parts.append('time')
    if row.get('trip_index') is not None:
        parts.append('trip')
    if row.get('start_core_index') is not None and 'piston' in params:
        parts.append('piston')
    if 'calc_inputs' in params:
        parts.append('calc')
    if row.get('winch_time_offset_sec') is not None or (
        params.get('winch', {}).get('aligned')
    ):
        parts.append('winch')
    return ', '.join(parts) if parts else 'no sections'


class RestoreResultsDialog(QDialog):
    """
    Dialog for choosing which saved result to restore.

    Parameters
    ----------
    results : list[dict]
        Rows from ``fetch_results_for_core()``, newest first.  Each dict must
        contain at least ``result_id`` and ``analyzed_at``.
    parent : QWidget or None
        Parent window for modality.
    """

    def __init__(self, results: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Restore Saved Analysis Results")
        self.setMinimumWidth(520)
        self.setMinimumHeight(320)

        self._results = results
        self._selected_id: Optional[int] = None

        layout = QVBoxLayout(self)

        # Instruction label
        intro = QLabel(
            f"Found <b>{len(results)}</b> saved result(s) for this core.  "
            "Select one to restore and click <b>Restore</b>."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # List of results
        list_group = QGroupBox("Saved Results")
        list_layout = QVBoxLayout(list_group)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        for row in results:
            rid = row.get('result_id', '?')
            date_str = str(row.get('analyzed_at') or 'unknown date')
            sections = _section_summary(row)
            label = f"#{rid}  —  {date_str[:19]}  [{sections}]"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, rid)
            self._list.addItem(item)

        # Pre-select the first (most recent) item
        if self._list.count():
            self._list.setCurrentRow(0)

        self._list.itemDoubleClicked.connect(self._accept_if_selected)
        list_layout.addWidget(self._list)
        layout.addWidget(list_group)

        # Detail label
        self._detail_label = QLabel()
        self._detail_label.setWordWrap(True)
        self._detail_label.setStyleSheet("QLabel { color: #555; font-style: italic; }")
        layout.addWidget(self._detail_label)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._on_row_changed(0)

        # Buttons
        btn_box = QDialogButtonBox()
        self._restore_btn = btn_box.addButton("Restore", QDialogButtonBox.AcceptRole)
        btn_box.addButton("Cancel", QDialogButtonBox.RejectRole)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def selected_result_id(self) -> Optional[int]:
        """Return the result_id of the chosen row, or None if nothing selected."""
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _on_row_changed(self, row: int):
        if row < 0 or row >= len(self._results):
            self._detail_label.setText('')
            return
        r = self._results[row]
        recoil = r.get('result_recoil_max')
        recoil_str = f"{recoil:.3f} m" if recoil is not None else 'n/a'
        trip_idx = r.get('trip_index')
        sc_idx = r.get('start_core_index')
        winch_offset = r.get('winch_time_offset_sec')
        winch_str = (
            f"{winch_offset:+.2f} s" if winch_offset is not None else 'n/a'
        )
        self._detail_label.setText(
            f"Result #{r.get('result_id')}  |  "
            f"Trip index: {trip_idx if trip_idx is not None else 'n/a'}  |  "
            f"Start core: {sc_idx if sc_idx is not None else 'n/a'}  |  "
            f"Recoil max: {recoil_str}  |  "
            f"Winch offset: {winch_str}"
        )

    def _accept_if_selected(self):
        if self._list.currentItem() is not None:
            self.accept()
