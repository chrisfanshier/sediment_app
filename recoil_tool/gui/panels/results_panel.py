"""
ResultsPanel — displays ModelResult fields after running the forward model.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QGroupBox,
)
from PySide6.QtCore import Qt

from ...domain.models.recoil_params import ModelResult

_PLACEHOLDER = "—"


class ResultsPanel(QWidget):
    """Read-only display of the most recent ModelResult."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._setup_ui()
        self.clear()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        results_group = QGroupBox("Model Results")
        form = QFormLayout(results_group)
        form.setLabelAlignment(Qt.AlignRight)

        def _lbl() -> QLabel:
            l = QLabel(_PLACEHOLDER)
            l.setTextInteractionFlags(Qt.TextSelectableByMouse)
            return l

        self._v0_lbl = _lbl()
        form.addRow("v₀ (m/s):", self._v0_lbl)

        self._k_lbl = _lbl()
        form.addRow("k (N/m):", self._k_lbl)

        self._peak_disp_lbl = _lbl()
        form.addRow("Peak displacement (m):", self._peak_disp_lbl)

        self._peak_time_lbl = _lbl()
        form.addRow("Peak time (s):", self._peak_time_lbl)

        root.addWidget(results_group)
        root.addStretch()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_result(self, result: ModelResult):
        """Populate labels from a ModelResult."""
        self._v0_lbl.setText(f"{result.v0_ms:.4f}")
        self._k_lbl.setText(f"{result.k_nm:,.1f}")
        self._peak_disp_lbl.setText(f"{result.peak_displacement_m:.3f}")
        self._peak_time_lbl.setText(f"{result.peak_time_s:.2f}")

    def clear(self):
        """Reset all labels to placeholder."""
        for lbl in (self._v0_lbl, self._k_lbl,
                    self._peak_disp_lbl, self._peak_time_lbl):
            lbl.setText(_PLACEHOLDER)
