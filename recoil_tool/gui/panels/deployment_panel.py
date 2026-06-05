"""
DeploymentPanel — form for entering deployment parameters before running the
forward rebound model.

Pre-populates from DB where possible:
  - Deployment depth (m) from result_seafloor
  - Rope type from wire table
  - pig_weights shown read-only for reference

Emits plot_requested(DeploymentParams) when the user clicks "Plot Model".
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QDoubleSpinBox, QComboBox,
    QPushButton, QGroupBox, QLabel, QSizePolicy, QCheckBox,
)

from ...domain.models.recoil_params import DeploymentParams

_ROPE_TYPES = ['hmpe', 'steel']
_WIRE_TYPE_MAP = {
    'hmpe': 'hmpe',
    'dyneema': 'hmpe',
    'steel': 'steel',
    'wire': 'steel',
}
_CURVE_TYPES = [
    'physics', 'exponential', 'critically_damped', 'gamma_pulse', 'damped_sine',
]


def _guess_rope_type(wire_type: str) -> str:
    """Map a DB wire_type string to 'hmpe' or 'steel'."""
    for key, val in _WIRE_TYPE_MAP.items():
        if key in wire_type.lower():
            return val
    return 'hmpe'


class DeploymentPanel(QWidget):
    """
    Input form for deployment parameters.

    Signals
    -------
    plot_requested(DeploymentParams)
        Emitted when user clicks "Plot Model".
    """

    plot_requested    = Signal(object)   # DeploymentParams
    curve_type_changed = Signal(str)     # emitted when user changes curve type combobox

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._setup_ui()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # ── Deployment parameters group ──
        params_group = QGroupBox("Deployment Parameters")
        form = QFormLayout(params_group)
        form.setLabelAlignment(Qt.AlignRight)

        self._depth_spin = QDoubleSpinBox()
        self._depth_spin.setRange(0.0, 12000.0)
        self._depth_spin.setDecimals(1)
        self._depth_spin.setSuffix(" m")
        self._depth_spin.setValue(0.0)
        form.addRow("Deployment depth:", self._depth_spin)

        self._corer_spin = QDoubleSpinBox()
        self._corer_spin.setRange(0.0, 20000.0)
        self._corer_spin.setDecimals(1)
        self._corer_spin.setSuffix(" lbs")
        self._corer_spin.setValue(0.0)
        form.addRow("Corer weight:", self._corer_spin)

        self._instrument_spin = QDoubleSpinBox()
        self._instrument_spin.setRange(0.0, 500.0)
        self._instrument_spin.setDecimals(1)
        self._instrument_spin.setSuffix(" lbs")
        self._instrument_spin.setValue(0.0)
        form.addRow("Instrument weight:", self._instrument_spin)

        self._rope_combo = QComboBox()
        self._rope_combo.addItems(_ROPE_TYPES)
        form.addRow("Rope type:", self._rope_combo)

        self._dia_spin = QDoubleSpinBox()
        self._dia_spin.setRange(1.0, 100.0)
        self._dia_spin.setDecimals(1)
        self._dia_spin.setSuffix(" mm")
        self._dia_spin.setValue(14.3)
        form.addRow("Rope diameter:", self._dia_spin)

        self._pig_label = QLabel("—")
        self._pig_label.setStyleSheet("color: #666;")
        form.addRow("Pig weights (ref):", self._pig_label)

        self._E_spin = QDoubleSpinBox()
        self._E_spin.setRange(1.0, 500.0)
        self._E_spin.setDecimals(1)
        self._E_spin.setSuffix(" GPa")
        self._E_spin.setValue(45.0)
        form.addRow("Elastic modulus E:", self._E_spin)

        self._Cd_spin = QDoubleSpinBox()
        self._Cd_spin.setRange(0.0, 10.0)
        self._Cd_spin.setDecimals(4)
        self._Cd_spin.setSingleStep(0.001)
        self._Cd_spin.setValue(0.01)
        form.addRow("Drag coeff C_d:", self._Cd_spin)

        root.addWidget(params_group)

        # ── Curve fitting group ──
        curve_group = QGroupBox("Curve Fitting")
        curve_vlayout = QVBoxLayout(curve_group)

        curve_form = QFormLayout()
        self._curve_combo = QComboBox()
        self._curve_combo.addItems([
            "Physics model",
            "Exponential",
            "Critically damped",
            "Gamma Pulse",
            "Damped Sine",
        ])
        self._curve_combo.currentIndexChanged.connect(self._on_curve_type_changed)
        curve_form.addRow("Curve type:", self._curve_combo)
        curve_vlayout.addLayout(curve_form)

        # Empirical parameter widgets — hidden when Physics model is selected
        self._empirical_widget = QWidget()
        self._emp_form = QFormLayout(self._empirical_widget)
        self._emp_form.setContentsMargins(0, 0, 0, 0)

        self._A_spin = QDoubleSpinBox()
        self._A_spin.setRange(0.0, 50.0)
        self._A_spin.setDecimals(3)
        self._A_spin.setSuffix(" m")
        self._A_spin.setValue(2.0)
        self._emp_form.addRow("A:", self._A_spin)

        self._tau_spin = QDoubleSpinBox()
        self._tau_spin.setRange(0.01, 100.0)
        self._tau_spin.setDecimals(3)
        self._tau_spin.setSuffix(" s")
        self._tau_spin.setValue(1.0)
        self._emp_form.addRow("tau:", self._tau_spin)

        self._omega_spin = QDoubleSpinBox()
        self._omega_spin.setRange(0.1, 20.0)
        self._omega_spin.setDecimals(3)
        self._omega_spin.setSingleStep(0.1)
        self._omega_spin.setSuffix(" rad/s")
        self._omega_spin.setValue(1.0)
        self._emp_form.addRow("ω:", self._omega_spin)

        self._autofit_check = QCheckBox("Auto-fit on plot")
        self._autofit_check.setChecked(True)
        self._emp_form.addRow("", self._autofit_check)

        curve_vlayout.addWidget(self._empirical_widget)
        self._empirical_widget.setVisible(False)

        root.addWidget(curve_group)

        # ── Buttons ──
        self._autofit_btn = QPushButton("Autofit")
        self._autofit_btn.setMinimumHeight(32)
        self._autofit_btn.setEnabled(False)   # enabled only for empirical curve types
        self._autofit_btn.clicked.connect(self._on_autofit_clicked)
        root.addWidget(self._autofit_btn)

        self._plot_btn = QPushButton("Plot Model")
        self._plot_btn.setMinimumHeight(32)
        self._plot_btn.clicked.connect(self._on_plot_clicked)
        root.addWidget(self._plot_btn)

        root.addStretch()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def pre_populate(self, core_info: dict):
        """
        Pre-populate form fields from a core_info dict as returned by
        RecoilLoader.fetch_cores_with_results() (optionally augmented with
        'depth_at_trip' and 'core_length' by the controller).
        """
        # Deployment depth: prefer actual sensor depth at trip time
        depth_at_trip = core_info.get('depth_at_trip')
        if depth_at_trip is not None:
            self._depth_spin.setValue(float(depth_at_trip))
        else:
            seafloor = core_info.get('result_seafloor')
            if seafloor is not None:
                self._depth_spin.setValue(float(seafloor))

        wire_type = core_info.get('wire_type') or ''
        self._rope_combo.setCurrentText(_guess_rope_type(wire_type))

        self._dia_spin.setValue(14.3)

        pig = core_info.get('pig_weights')
        self._pig_label.setText(str(pig) if pig is not None else "—")

        # Auto-compute corer weight: base + barrel length term + pig weights
        # Formula: 3200 + (200 * core_length_ft / 10) + 200 + (600 * num_pigs)
        core_length_ft = float(core_info.get('core_length') or 0.0)
        num_pigs = int(core_info.get('pig_weights') or 0)
        if core_length_ft > 0:
            corer_wt = 3200 + (200 * core_length_ft / 10) + 200 + (600 * num_pigs)
            self._corer_spin.setValue(round(corer_wt, 1))
        else:
            self._corer_spin.setValue(0.0)

    def get_params(self) -> DeploymentParams:
        """Read current form values into a DeploymentParams."""
        curve_type = _CURVE_TYPES[self._curve_combo.currentIndex()]
        return DeploymentParams(
            depth_m=self._depth_spin.value(),
            corer_lbs=self._corer_spin.value(),
            instrument_lbs=self._instrument_spin.value(),
            rope_type=self._rope_combo.currentText(),
            rope_dia_mm=self._dia_spin.value(),
            E_gpa=self._E_spin.value(),
            C_drag=self._Cd_spin.value(),
            curve_type=curve_type,
            A_m=self._A_spin.value(),
            tau_s=self._tau_spin.value(),
            omega_rads=self._omega_spin.value(),
            auto_fit=self._autofit_check.isChecked(),
        )

    # ------------------------------------------------------------------
    # Public: empirical params push-back
    # ------------------------------------------------------------------

    def set_empirical_params(self, A: float, tau: float, omega: 'float | None' = None):
        """Push fitted A, tau (and optionally omega) into the spinboxes."""
        self._A_spin.blockSignals(True)
        self._tau_spin.blockSignals(True)
        self._omega_spin.blockSignals(True)
        self._A_spin.setValue(round(A, 3))
        self._tau_spin.setValue(round(tau, 3))
        if omega is not None:
            self._omega_spin.setValue(round(omega, 3))
        self._A_spin.blockSignals(False)
        self._tau_spin.blockSignals(False)
        self._omega_spin.blockSignals(False)

    def restore_params(self, params: DeploymentParams):
        """
        Set all form fields from a saved DeploymentParams without emitting
        curve_type_changed (so the controller's restore loop doesn't re-trigger).
        """
        idx = _CURVE_TYPES.index(params.curve_type) if params.curve_type in _CURVE_TYPES else 0

        self._depth_spin.setValue(params.depth_m)
        self._corer_spin.setValue(params.corer_lbs)
        self._instrument_spin.setValue(params.instrument_lbs)
        rope_idx = self._rope_combo.findText(params.rope_type)
        if rope_idx >= 0:
            self._rope_combo.setCurrentIndex(rope_idx)
        self._dia_spin.setValue(params.rope_dia_mm)
        self._E_spin.setValue(params.E_gpa)
        self._Cd_spin.setValue(params.C_drag)

        # Set curve combobox without emitting curve_type_changed
        self._curve_combo.blockSignals(True)
        self._curve_combo.setCurrentIndex(idx)
        self._curve_combo.blockSignals(False)
        self._apply_curve_type_ui(idx)   # update visibility

        self._A_spin.setValue(params.A_m)
        self._tau_spin.setValue(params.tau_s)
        self._omega_spin.setValue(params.omega_rads)
        self._autofit_check.setChecked(False)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _apply_curve_type_ui(self, index: int):
        """Update widget visibility/enabled state for the given curve index."""
        self._empirical_widget.setVisible(index != 0)
        self._emp_form.setRowVisible(self._omega_spin, index == 4)
        self._autofit_btn.setEnabled(index != 0)

    def _on_curve_type_changed(self, index: int):
        self._apply_curve_type_ui(index)
        self.curve_type_changed.emit(_CURVE_TYPES[index])

    def _on_autofit_clicked(self):
        params = self.get_params()
        params.auto_fit = True   # force regardless of checkbox state
        self.plot_requested.emit(params)

    def _on_plot_clicked(self):
        self.plot_requested.emit(self.get_params())
