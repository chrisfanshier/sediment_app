"""
ResultsPanel — displays ModelResult fields after running the forward model,
or fitted empirical parameters after an empirical curve fit.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QGroupBox, QPushButton,
)

from ...domain.models.recoil_params import ModelResult

_PLACEHOLDER = "—"


class ResultsPanel(QWidget):
    """Read-only display of the most recent ModelResult or empirical fit."""

    save_requested = Signal()
    """Emitted when the user clicks Save Result."""

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

        # Physics model results
        results_group = QGroupBox("Physics Model Results")
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

        # Empirical fit results
        emp_group = QGroupBox("Empirical Fit Parameters")
        emp_form = QFormLayout(emp_group)
        emp_form.setLabelAlignment(Qt.AlignRight)

        self._curve_type_lbl = _lbl()
        emp_form.addRow("Curve type:", self._curve_type_lbl)

        self._A_lbl = _lbl()
        self._A_row_label = QLabel("A (m):")
        emp_form.addRow(self._A_row_label, self._A_lbl)

        self._tau_lbl = _lbl()
        self._tau_row_label = QLabel("tau (s):")
        emp_form.addRow(self._tau_row_label, self._tau_lbl)

        self._omega_lbl = _lbl()
        self._omega_row_label = QLabel("ω (rad/s):")
        emp_form.addRow(self._omega_row_label, self._omega_lbl)

        root.addWidget(emp_group)

        # Save button
        self._save_btn = QPushButton("Save Result")
        self._save_btn.setMinimumHeight(30)
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self.save_requested)
        root.addWidget(self._save_btn)

        root.addStretch()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_result(self, result: ModelResult):
        """Populate physics model labels from a ModelResult."""
        self._v0_lbl.setText(f"{result.v0_ms:.4f}")
        self._k_lbl.setText(f"{result.k_nm:,.1f}")
        self._peak_disp_lbl.setText(f"{result.peak_displacement_m:.3f}")
        self._peak_time_lbl.setText(f"{result.peak_time_s:.2f}")
        self._save_btn.setEnabled(True)

    def show_empirical_result(
        self,
        curve_type: str,
        A: float,
        tau: float,
        omega: 'float | None' = None,
    ):
        """Populate empirical fit labels."""
        self._curve_type_lbl.setText(curve_type.replace('_', ' ').title())

        if curve_type == 'single_lobe_damped':
            # A = H, tau = t_p
            self._A_row_label.setText("H (m):")
            self._tau_row_label.setText("t_p (s):")
            self._omega_row_label.setText("alpha:")
            self._A_lbl.setText(f"{A:.4f}")       # H
            self._tau_lbl.setText(f"{tau:.4f}")   # t_p
            self._omega_lbl.setText(f"{omega:.4f}" if omega is not None else _PLACEHOLDER)
        else:
            self._A_row_label.setText("A (m):")
            self._tau_row_label.setText("tau (s):")
            self._omega_row_label.setText("ω (rad/s):")
            self._A_lbl.setText(f"{A:.4f}")
            self._tau_lbl.setText(f"{tau:.4f}")
            self._omega_lbl.setText(f"{omega:.4f}" if omega is not None else _PLACEHOLDER)

        self._save_btn.setEnabled(True)


    def clear(self):
        """Reset all labels to placeholder and disable Save."""
        for lbl in (self._v0_lbl, self._k_lbl,
                    self._peak_disp_lbl, self._peak_time_lbl,
                    self._curve_type_lbl, self._A_lbl,
                    self._tau_lbl, self._omega_lbl):
            lbl.setText(_PLACEHOLDER)
        self._save_btn.setEnabled(False)
