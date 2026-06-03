"""
RecoilPlotView — PyQtGraph-based plot widget for the recoil overlay tool.

Shows the full Release Device depth trace with a draggable trip marker.
After the user clicks “Plot Model” an orange overlay shows the predicted
rebound depth curve starting from the trip point.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout

pg.setConfigOptions(antialias=True, useOpenGL=True)

_DEPTH_COLOR   = '#6baed6'
_MODEL_COLOR   = '#e6550d'
_TRIP_PEN      = pg.mkPen(color='#888888', width=2, style=Qt.DashLine)
_FIT_END_PEN   = pg.mkPen(color='#2ca02c', width=2, style=Qt.SolidLine)


class RecoilPlotView(QWidget):
    """
    Main plot widget for the recoil tool.

    Signals
    -------
    trip_index_changed(int)
        Emitted when the user finishes dragging the trip marker.
        Value is the nearest integer index into the loaded time array.
    """

    trip_index_changed = Signal(int)
    fit_end_changed    = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._time_s: np.ndarray | None = None
        self._depth_m: np.ndarray | None = None
        self._trip_line: pg.InfiniteLine | None = None
        self._fit_end_line: pg.InfiniteLine | None = None
        self._model_curve = None

        self._setup_ui()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._glw = pg.GraphicsLayoutWidget()
        self._glw.setBackground('w')
        layout.addWidget(self._glw)

        self._depth_plot = self._glw.addPlot(row=0, col=0)
        self._depth_plot.setLabel('left', 'Depth (m)')
        self._depth_plot.setLabel('bottom', 'Sample index')
        self._depth_plot.invertY(True)
        self._depth_plot.showGrid(x=True, y=True, alpha=0.3)
        self._depth_plot.setDownsampling(auto=True, mode='peak')
        self._depth_plot.setClipToView(True)

        self._glw.ci.layout.setRowStretchFactor(0, 1)

    # ------------------------------------------------------------------
    # Public: depth trace + trip marker
    # ------------------------------------------------------------------

    def plot_depth_trace(
        self,
        time_s: np.ndarray,
        depth_m: np.ndarray,
        trip_idx: int,
        core_name: str = '',
    ):
        """
        Plot the raw depth trace and place a draggable trip marker.

        Parameters
        ----------
        time_s : array of float
            Seconds from first sample.
        depth_m : array of float
            Depth in metres (positive downward).
        trip_idx : int
            Index in the arrays where the trip occurred.
        core_name : str
            Optional title for the plot.
        """
        self._time_s = time_s
        self._depth_m = depth_m
        self._depth_plot.clear()
        self._model_curve = None
        self._trip_line = None

        if core_name:
            self._depth_plot.setTitle(core_name)

        x = np.arange(len(depth_m))
        self._depth_plot.plot(x, depth_m, pen=pg.mkPen(color=_DEPTH_COLOR, width=1.5))

        pos = float(trip_idx) if 0 <= trip_idx < len(depth_m) else 0.0
        self._trip_line = pg.InfiniteLine(
            pos=pos,
            angle=90,
            movable=True,
            pen=_TRIP_PEN,
            label='Trip',
            labelOpts={'color': '#888888', 'position': 0.95},
        )
        self._trip_line.sigPositionChangeFinished.connect(self._on_trip_line_moved)
        self._depth_plot.addItem(self._trip_line)

        # Fit endpoint line — default 10 s after trip
        dt = float(np.median(np.diff(time_s))) if len(time_s) > 1 else 1.0
        default_end = min(trip_idx + max(1, int(10.0 / dt)), len(depth_m) - 1)
        self._fit_end_line = pg.InfiniteLine(
            pos=float(default_end),
            angle=90,
            movable=True,
            pen=_FIT_END_PEN,
            label='Fit end',
            labelOpts={'color': '#2ca02c', 'position': 0.85},
        )
        self._fit_end_line.sigPositionChangeFinished.connect(self._on_fit_end_line_moved)
        self._depth_plot.addItem(self._fit_end_line)

    def update_trip_marker(self, trip_idx: int):
        if self._trip_line is None:
            return
        self._trip_line.blockSignals(True)
        self._trip_line.setPos(float(trip_idx))
        self._trip_line.blockSignals(False)

    def update_fit_end_marker(self, fit_end_idx: int):
        if self._fit_end_line is None:
            return
        self._fit_end_line.blockSignals(True)
        self._fit_end_line.setPos(float(fit_end_idx))
        self._fit_end_line.blockSignals(False)

    # ------------------------------------------------------------------
    # Public: model overlay
    # ------------------------------------------------------------------

    def plot_model_overlay(self, start_idx: int, depth_model_m: np.ndarray, color: str = _MODEL_COLOR):
        """Overlay the forward-model depth curve starting at start_idx."""
        self.clear_overlay()
        x = np.arange(start_idx, start_idx + len(depth_model_m))
        self._model_curve = self._depth_plot.plot(
            x, depth_model_m,
            pen=pg.mkPen(color=color, width=2.5),
        )

    def clear_overlay(self):
        """Remove the model overlay curve if present."""
        if self._model_curve is not None:
            self._depth_plot.removeItem(self._model_curve)
            self._model_curve = None

    # ------------------------------------------------------------------
    # Public: clear all
    # ------------------------------------------------------------------

    def clear(self):
        """Clear the depth plot and reset state."""
        self._depth_plot.clear()
        self._trip_line = None
        self._fit_end_line = None
        self._model_curve = None
        self._time_s = None
        self._depth_m = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_trip_line_moved(self):
        if self._trip_line is None:
            return
        idx = max(0, int(round(self._trip_line.getXPos())))
        # Clamp: trip must stay strictly left of fit end
        if self._fit_end_line is not None:
            fit_end_pos = int(round(self._fit_end_line.getXPos()))
            if idx >= fit_end_pos:
                idx = max(0, fit_end_pos - 1)
                self._trip_line.blockSignals(True)
                self._trip_line.setPos(float(idx))
                self._trip_line.blockSignals(False)
        self.trip_index_changed.emit(idx)

    def _on_fit_end_line_moved(self):
        if self._fit_end_line is None:
            return
        idx = max(0, int(round(self._fit_end_line.getXPos())))
        # Clamp: fit end must stay strictly right of trip
        trip_pos = int(round(self._trip_line.getXPos())) if self._trip_line is not None else 0
        if idx <= trip_pos:
            idx = trip_pos + 1
            self._fit_end_line.blockSignals(True)
            self._fit_end_line.setPos(float(idx))
            self._fit_end_line.blockSignals(False)
        self.fit_end_changed.emit(idx)
