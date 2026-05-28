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
    QPushButton, QGroupBox, QLabel, QSizePolicy,
)

from ...domain.models.recoil_params import DeploymentParams

_ROPE_TYPES = ['hmpe', 'steel']
_WIRE_TYPE_MAP = {
    'hmpe': 'hmpe',
    'dyneema': 'hmpe',
    'steel': 'steel',
    'wire': 'steel',
}


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

    plot_requested = Signal(object)   # DeploymentParams

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
        self._corer_spin.setRange(0.0, 5000.0)
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

        # ── Button ──
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
        RecoilLoader.fetch_cores_with_results().
        """
        seafloor = core_info.get('result_seafloor')
        if seafloor is not None:
            self._depth_spin.setValue(float(seafloor))

        wire_type = core_info.get('wire_type') or ''
        self._rope_combo.setCurrentText(_guess_rope_type(wire_type))

        self._dia_spin.setValue(14.3)

        pig = core_info.get('pig_weights')
        self._pig_label.setText(str(pig) if pig is not None else "—")

        # Reset corer weight to zero — always manual
        self._corer_spin.setValue(0.0)

    def get_params(self) -> DeploymentParams:
        """Read current form values into a DeploymentParams."""
        return DeploymentParams(
            depth_m=self._depth_spin.value(),
            corer_lbs=self._corer_spin.value(),
            instrument_lbs=self._instrument_spin.value(),
            rope_type=self._rope_combo.currentText(),
            rope_dia_mm=self._dia_spin.value(),
            E_gpa=self._E_spin.value(),
            C_drag=self._Cd_spin.value(),
        )

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_plot_clicked(self):
        self.plot_requested.emit(self.get_params())
