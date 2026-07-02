"""
WinchPlotView - Secondary plot for Winch mode.

One or two stacked winch time-series subplots. X-axis is linked to the main
sensor plot so pan/zoom on time is shared; Y-axis zooms independently.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import pyqtgraph as pg

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QStackedWidget

from ...persistence.winch_loader import datetime_to_epoch


class WinchPlotView(QWidget):
    """Secondary view showing one or two winch parameter traces vs time."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._winch_df: Optional[pd.DataFrame] = None
        self._x_link_target: Optional[pg.PlotItem] = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.info_label = QLabel('No winch data loaded.')
        self.info_label.setStyleSheet(
            'QLabel { background-color: white; padding: 5px; '
            'border: 1px solid gray; }'
        )
        layout.addWidget(self.info_label)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        self._single_graphics = self._make_graphics(num_plots=1)
        self._dual_graphics = self._make_graphics(num_plots=2)

        self._stack.addWidget(self._single_graphics['widget'])
        self._stack.addWidget(self._dual_graphics['widget'])

        self._single_plot = self._single_graphics['plots'][0]
        self._dual_plot_1 = self._dual_graphics['plots'][0]
        self._dual_plot_2 = self._dual_graphics['plots'][1]

    def _make_graphics(self, num_plots: int) -> dict:
        widget = pg.GraphicsLayoutWidget()
        widget.setBackground('w')
        plots: list[pg.PlotItem] = []
        date_axis = pg.graphicsItems.DateAxisItem.DateAxisItem(orientation='bottom')

        for row in range(num_plots):
            if row == num_plots - 1:
                plot = widget.addPlot(row=row, col=0, axisItems={'bottom': date_axis})
            else:
                plot = widget.addPlot(row=row, col=0)
            plot.setLabel('left', 'Winch')
            plot.showGrid(x=True, y=True, alpha=0.3)
            plot.setDownsampling(auto=True, mode='peak')
            plot.setClipToView(True)
            plot.addLegend()
            if row > 0:
                plot.setXLink(plots[0])
            plots.append(plot)

        if num_plots == 1:
            plots[0].setLabel('bottom', 'Time')

        return {'widget': widget, 'plots': plots}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_x_link(self, plot_item: Optional[pg.PlotItem]) -> None:
        """Link winch plot X-axes to the main sensor plot."""
        self._x_link_target = plot_item
        for plot in (self._single_plot, self._dual_plot_1, self._dual_plot_2):
            if plot_item is not None:
                plot.setXLink(plot_item)
            else:
                plot.setXLink(None)

    def plot(
        self,
        df: Optional[pd.DataFrame],
        column_1: Optional[str],
        column_2: Optional[str] = None,
        show_second: bool = False,
        source_label: str = '',
    ) -> None:
        """Render winch data in one or two windows."""
        self._winch_df = df

        if df is None or df.empty or not column_1:
            self._clear_all_plots()
            self.info_label.setText(
                source_label or 'No winch data loaded.'
            )
            return

        x = datetime_to_epoch(df).to_numpy()
        dual = show_second and column_2 and column_2 in df.columns

        if dual:
            self._stack.setCurrentIndex(1)
            self._plot_trace(self._dual_plot_1, x, df[column_1].to_numpy(), column_1)
            self._plot_trace(self._dual_plot_2, x, df[column_2].to_numpy(), column_2)
            self._dual_plot_1.setLabel('bottom', '')
            self._dual_plot_2.setLabel('bottom', 'Time')
        else:
            self._stack.setCurrentIndex(0)
            col = column_1 if column_1 in df.columns else None
            if col:
                self._plot_trace(self._single_plot, x, df[col].to_numpy(), col)
            self._single_plot.setLabel('bottom', 'Time')

        rows = len(df)
        label = source_label or f'{rows:,} winch samples'
        self.info_label.setText(label)

        if self._x_link_target is None:
            self._auto_range_x(x)

    def clear(self) -> None:
        self._winch_df = None
        self._clear_all_plots()
        self.info_label.setText('No winch data loaded.')

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _plot_trace(
        self,
        plot: pg.PlotItem,
        x: np.ndarray,
        y: np.ndarray,
        name: str,
    ) -> None:
        plot.clearPlots()
        plot.plot(
            x, y,
            pen=pg.mkPen('#d62728', width=1.5),
            name=name,
        )
        plot.setLabel('left', name)
        plot.enableAutoRange(axis='y')

    def _clear_all_plots(self) -> None:
        for plot in (self._single_plot, self._dual_plot_1, self._dual_plot_2):
            plot.clearPlots()

    def _auto_range_x(self, x: np.ndarray) -> None:
        if len(x) == 0:
            return
        x_min, x_max = float(np.min(x)), float(np.max(x))
        pad = max((x_max - x_min) * 0.02, 1.0)
        for plot in (self._single_plot, self._dual_plot_1):
            plot.setXRange(x_min - pad, x_max + pad, padding=0)
