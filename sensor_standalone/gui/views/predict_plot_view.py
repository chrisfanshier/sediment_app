"""Matplotlib canvas for Predict mode recoil curves."""
from __future__ import annotations

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ...domain.processing.predict import draw_curve


class PredictPlotView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._canvas = FigureCanvasQTAgg()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)

    def clear(self) -> None:
        self._canvas.figure.clear()
        self._canvas.draw_idle()

    def show_prediction(
        self,
        result: dict,
        selected_curves: list[str],
        show_piston: bool,
    ) -> None:
        fig = draw_curve(result, selected_curves, show_piston)
        self._canvas.figure = fig
        self._canvas.draw_idle()
