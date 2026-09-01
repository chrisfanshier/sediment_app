"""Viewer page — USBL location & time-series viewer.

Adapted from the database-integrated ``dredge_app/gui/main_window.py``:
identical plotting, brush selection, annotation, and export behaviour, but

* it is a ``QWidget`` page embedded in the standalone main window (status
  messages are emitted via the ``statusMessage`` signal);
* the Cruise / Dredge dropdowns are fed by the project's SQLite store via
  :class:`ProjectDataLoader` instead of PostgreSQL;
* annotations are persisted per-dredge in the project database and reloaded
  when the dredge is reselected.

CSV loading remains available (wired to the File menu by the main window) as
a store-free fallback; annotations are session-only in that mode.
"""
import os
from datetime import datetime

import numpy as np
import pandas as pd
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore
from pyproj import Transformer

from ..persistence.loader import ProjectDataLoader


class ViewerPage(QtWidgets.QWidget):
    statusMessage = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Data storage
        self.usbl_df = None
        self.sensor_df = None
        self.utm_transformer = None
        self.utm_zone = None  # String like "10N"
        self.utm_epsg = None  # EPSG code like "EPSG:32610"
        self.core_name = None  # Selected dredge / USBL filename

        # Project store state
        self.store = None
        self.loader = None
        self._cruises = []
        self._dredges = []
        self.current_dredge_id = None  # None => CSV fallback / nothing loaded

        # Annotations storage (persisted via store when a dredge is loaded)
        self.annotations = []
        self.annotation_id_counter = 1

        self.init_ui()

    def _status(self, message):
        self.statusMessage.emit(message)

    # ==================================================================
    # UI construction
    # ==================================================================

    def init_ui(self):
        """Initialize the user interface"""
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)

        # Control panel at top
        control_panel = self.create_control_panel()
        main_layout.addWidget(control_panel)

        # Horizontal splitter for main content and annotations panel
        h_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        h_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #ccc;
                width: 4px;
            }
            QSplitter::handle:hover {
                background-color: #999;
            }
        """)

        # Vertical splitter for location and time series plots (left side)
        v_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        v_splitter.setHandleWidth(6)
        v_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #bbb;
                height: 6px;
            }
            QSplitter::handle:hover {
                background-color: #4CAF50;
            }
        """)

        self.location_plot_widget = self.create_location_plot()
        v_splitter.addWidget(self.location_plot_widget)

        self.timeseries_plot_widget = self.create_timeseries_plot()
        v_splitter.addWidget(self.timeseries_plot_widget)

        v_splitter.setSizes([360, 540])
        h_splitter.addWidget(v_splitter)

        self.annotations_panel = self.create_annotations_panel()
        h_splitter.addWidget(self.annotations_panel)
        h_splitter.setSizes([900, 300])

        main_layout.addWidget(h_splitter)

    def create_control_panel(self):
        """Create the control panel with cruise/dredge selection."""
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(panel)

        # Cruise selection
        layout.addWidget(QtWidgets.QLabel("Cruise:"))
        self.cruise_combo = QtWidgets.QComboBox()
        self.cruise_combo.setMinimumWidth(200)
        self.cruise_combo.currentIndexChanged.connect(self._on_cruise_changed)
        layout.addWidget(self.cruise_combo)

        # Dredge selection
        layout.addWidget(QtWidgets.QLabel("Dredge:"))
        self.dredge_combo = QtWidgets.QComboBox()
        self.dredge_combo.setMinimumWidth(200)
        self.dredge_combo.setEnabled(False)
        self.dredge_combo.currentIndexChanged.connect(self._on_dredge_changed)
        layout.addWidget(self.dredge_combo)

        layout.addSpacing(20)

        # Load status
        self.usbl_label = QtWidgets.QLabel("No USBL data")
        self.usbl_label.setStyleSheet("color: gray;")
        layout.addWidget(self.usbl_label)

        self.sensor_label = QtWidgets.QLabel("No sensor data")
        self.sensor_label.setStyleSheet("color: gray;")
        layout.addWidget(self.sensor_label)

        layout.addSpacing(20)

        # Beacon filter
        layout.addWidget(QtWidgets.QLabel("Beacon:"))
        self.beacon_selector = QtWidgets.QComboBox()
        self.beacon_selector.addItem("All Beacons")
        self.beacon_selector.currentTextChanged.connect(self.update_beacon_filter)
        layout.addWidget(self.beacon_selector)

        layout.addStretch()

        return panel

    # ==================================================================
    # Project store cruise / dredge selection
    # ==================================================================

    def set_store(self, store):
        """Attach a project store (or None) and refresh the dropdowns."""
        self.store = store
        self.loader = ProjectDataLoader(store) if store is not None else None
        self.current_dredge_id = None
        self.refresh_cruises()

    def refresh_cruises(self, keep_selection=False):
        """Reload the cruise list from the project store.

        With ``keep_selection`` the current cruise/dredge selection is
        restored when still present (used after Data Manager edits).
        """
        prev_cruise_id = None
        prev_dredge_id = None
        if keep_selection:
            idx = self.cruise_combo.currentIndex()
            if 0 < idx <= len(self._cruises):
                prev_cruise_id = self._cruises[idx - 1]["cruise_id"]
            d_idx = self.dredge_combo.currentIndex()
            if 0 < d_idx <= len(self._dredges):
                prev_dredge_id = self._dredges[d_idx - 1]["dredge_id"]

        self.cruise_combo.blockSignals(True)
        self.cruise_combo.clear()
        self.cruise_combo.addItem("Select cruise…")
        self._cruises = self.store.fetch_cruises() if self.store is not None else []
        for cr in self._cruises:
            self.cruise_combo.addItem(cr["cruise_name"])
        self.cruise_combo.blockSignals(False)
        self._reset_dredge_combo()

        if prev_cruise_id is not None:
            for i, cr in enumerate(self._cruises):
                if cr["cruise_id"] == prev_cruise_id:
                    self.cruise_combo.setCurrentIndex(i + 1)  # triggers dredge reload
                    break
            if prev_dredge_id is not None:
                for j, d in enumerate(self._dredges):
                    if d["dredge_id"] == prev_dredge_id:
                        self.dredge_combo.blockSignals(True)
                        self.dredge_combo.setCurrentIndex(j + 1)
                        self.dredge_combo.blockSignals(False)
                        break

    def _reset_dredge_combo(self):
        self.dredge_combo.blockSignals(True)
        self.dredge_combo.clear()
        self.dredge_combo.addItem("Select dredge…")
        self.dredge_combo.setEnabled(False)
        self.dredge_combo.blockSignals(False)
        self._dredges = []

    def _on_cruise_changed(self, index):
        """Cruise combo changed — populate the dredge combo."""
        self._reset_dredge_combo()
        if self.store is None or index <= 0 or index > len(self._cruises):
            return

        cruise = self._cruises[index - 1]
        self._dredges = self.store.fetch_dredges(cruise["cruise_id"])
        self.dredge_combo.blockSignals(True)
        for d in self._dredges:
            self.dredge_combo.addItem(d["dredge_name"])
        self.dredge_combo.setEnabled(bool(self._dredges))
        self.dredge_combo.blockSignals(False)
        if not self._dredges:
            self._status(f"No dredges found in {cruise['cruise_name']} — add one on the Data Manager page")

    def _on_dredge_changed(self, index):
        """Dredge combo changed — load its dataset from the project."""
        if index <= 0 or index > len(self._dredges):
            return
        self._load_dredge(self._dredges[index - 1])

    def _load_dredge(self, dredge):
        """Assemble data for a dredge and push it into the viewer."""
        self._status(f"Loading {dredge['dredge_name']}…")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            dataset = self.loader.load_dredge_dataset(dredge)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.critical(
                self, "Load Error", f"Failed to load dredge data:\n{exc}"
            )
            self._status(f"Failed to load {dredge['dredge_name']}")
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        # Load persisted annotations for this dredge
        self.current_dredge_id = dredge["dredge_id"]
        self.annotations = self.store.fetch_annotations(self.current_dredge_id)
        self.refresh_annotations_list()

        self.core_name = dataset.core_name

        if dataset.usbl_df is None or dataset.usbl_df.empty:
            self.usbl_df = None
            self.usbl_label.setText("No USBL data")
            self.usbl_label.setStyleSheet("color: red;")
        else:
            self._apply_usbl_dataframe(dataset.usbl_df, dataset.core_name)

        if dataset.sensor_df is None or dataset.sensor_df.empty:
            self.sensor_df = None
            self.sensor_label.setText("No sensor/winch data")
            self.sensor_label.setStyleSheet("color: red;")
        else:
            self._apply_sensor_dataframe(dataset.sensor_df)

        n_usbl = 0 if self.usbl_df is None else len(self.usbl_df)
        n_sensor = 0 if self.sensor_df is None else len(self.sensor_df)
        self._status(
            f"Loaded {dataset.core_name}: {n_usbl} USBL fixes, {n_sensor} sensor rows, "
            f"{len(self.annotations)} saved annotation(s)"
        )

    # ==================================================================
    # Shared data application (used by store load and CSV fallbacks)
    # ==================================================================

    def _apply_usbl_dataframe(self, df, core_name=None):
        """Populate the viewer from a prepared USBL DataFrame."""
        self.usbl_df = df
        if core_name:
            self.core_name = core_name

        self.convert_to_utm()

        self.usbl_label.setText(f"✓ {len(self.usbl_df)} USBL points")
        self.usbl_label.setStyleSheet("color: green;")

        # Populate beacon selector
        self.beacon_selector.blockSignals(True)
        self.beacon_selector.clear()
        self.beacon_selector.addItem("All Beacons")
        if 'beacon_name' in self.usbl_df.columns:
            for beacon in self.usbl_df['beacon_name'].dropna().unique():
                count = (self.usbl_df['beacon_name'] == beacon).sum()
                self.beacon_selector.addItem(f"{beacon} ({count})")
        self.beacon_selector.blockSignals(False)

        self.plot_location_data()

    def _apply_sensor_dataframe(self, df):
        """Populate the time-series plots from a prepared sensor DataFrame."""
        self.sensor_df = df

        numeric_columns = [
            col for col in self.sensor_df.columns
            if col != 'datetime' and pd.api.types.is_numeric_dtype(self.sensor_df[col])
        ]

        for selector in self.plot_selectors:
            selector.blockSignals(True)
            selector.clear()
            selector.addItems(numeric_columns)

        for i, selector in enumerate(self.plot_selectors):
            if i < len(numeric_columns):
                selector.setCurrentIndex(i)
            selector.blockSignals(False)

        # Clear curves so the next update auto-ranges for the new dataset
        for curve in self.plot_curves:
            curve.setData([], [])

        for i in range(len(self.plot_widgets)):
            self.update_timeseries_plot(i)

        self.sensor_label.setText(
            f"✓ {len(self.sensor_df)} sensor points ({len(numeric_columns)} columns)"
        )
        self.sensor_label.setStyleSheet("color: green;")

    def create_annotations_panel(self):
        """Create the annotations management panel (right side)"""
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)

        header = QtWidgets.QLabel("Saved Annotations")
        header.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(header)

        self.annotations_list = QtWidgets.QListWidget()
        self.annotations_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        layout.addWidget(self.annotations_list)

        btn_layout = QtWidgets.QHBoxLayout()

        self.delete_annotation_btn = QtWidgets.QPushButton("Delete")
        self.delete_annotation_btn.clicked.connect(self.delete_annotation)
        self.delete_annotation_btn.setEnabled(False)
        btn_layout.addWidget(self.delete_annotation_btn)

        self.clear_annotations_btn = QtWidgets.QPushButton("Clear All")
        self.clear_annotations_btn.clicked.connect(self.clear_annotations)
        btn_layout.addWidget(self.clear_annotations_btn)

        layout.addLayout(btn_layout)
        layout.addSpacing(10)

        export_label = QtWidgets.QLabel("Export")
        export_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(export_label)

        format_label = QtWidgets.QLabel("Export Format:")
        format_label.setStyleSheet("font-size: 11px; color: gray;")
        layout.addWidget(format_label)

        self.export_csv_checkbox = QtWidgets.QCheckBox("CSV (metadata + annotated USBL)")
        self.export_csv_checkbox.setChecked(True)
        layout.addWidget(self.export_csv_checkbox)

        self.export_sensor_csv_checkbox = QtWidgets.QCheckBox("CSV (sensor & winch data)")
        self.export_sensor_csv_checkbox.setChecked(False)
        layout.addWidget(self.export_sensor_csv_checkbox)

        self.export_gpkg_checkbox = QtWidgets.QCheckBox("GeoPackage (spatial points)")
        self.export_gpkg_checkbox.setChecked(False)
        self.export_gpkg_checkbox.setToolTip(
            "Export as GeoPackage with UTM point geometry (built-in writer, "
            "no GDAL/geopandas required)"
        )
        layout.addWidget(self.export_gpkg_checkbox)

        layout.addSpacing(5)

        self.export_annotated_btn = QtWidgets.QPushButton("Export Annotated Data")
        self.export_annotated_btn.clicked.connect(self.export_annotated_data)
        self.export_annotated_btn.setEnabled(True)
        layout.addWidget(self.export_annotated_btn)

        self.annotations_list.itemSelectionChanged.connect(self.on_annotation_selected)

        return panel

    def create_location_plot(self):
        """Create the location plot widget (top panel)"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        label = QtWidgets.QLabel("Location Plot (USBL Data)")
        label.setStyleSheet("font-weight: bold;")
        layout.addWidget(label)

        self.location_plot = pg.PlotWidget()
        self.location_plot.setBackground('w')
        self.location_plot.showGrid(x=True, y=True, alpha=0.3)
        self.location_plot.setLabel('left', 'Northing (m)')
        self.location_plot.setLabel('bottom', 'Easting (m)')
        self.location_plot.setAspectLocked(True)

        viewbox = self.location_plot.getViewBox()
        viewbox.setMouseMode(pg.ViewBox.PanMode)
        viewbox.setMenuEnabled(True)

        layout.addWidget(self.location_plot)

        self.location_scatter = pg.ScatterPlotItem(
            size=6,
            pen=pg.mkPen(None),
            brush=pg.mkBrush(0, 100, 200, 120)
        )
        self.location_plot.addItem(self.location_scatter)

        self.location_selection_scatter = pg.ScatterPlotItem(
            size=8,
            pen=pg.mkPen('r', width=2),
            brush=pg.mkBrush(255, 0, 0, 180)
        )
        self.location_plot.addItem(self.location_selection_scatter)

        return widget

    def create_timeseries_plot(self):
        """Create dynamic time series plot widget with add/remove capability"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QtWidgets.QHBoxLayout()

        label = QtWidgets.QLabel("Time Series:")
        label.setStyleSheet("font-weight: bold;")
        header.addWidget(label)

        self.plot_selectors_layout = QtWidgets.QHBoxLayout()
        header.addLayout(self.plot_selectors_layout)

        self.add_plot_btn = QtWidgets.QPushButton("+ Add Plot")
        self.add_plot_btn.clicked.connect(self.add_plot)
        self.add_plot_btn.setStyleSheet("padding: 3px 8px; font-size: 11px;")
        header.addWidget(self.add_plot_btn)

        header.addSpacing(20)

        self.brush_mode_btn = QtWidgets.QPushButton("🖌️ Brush Selection")
        self.brush_mode_btn.setCheckable(True)
        self.brush_mode_btn.setStyleSheet("""
            QPushButton { padding: 5px 10px; }
            QPushButton:checked { 
                background-color: #4CAF50; 
                color: white; 
                font-weight: bold;
            }
        """)
        self.brush_mode_btn.clicked.connect(self.toggle_brush_mode)
        header.addWidget(self.brush_mode_btn)

        self.save_annotation_btn = QtWidgets.QPushButton("💾 Save Annotation")
        self.save_annotation_btn.setEnabled(False)
        self.save_annotation_btn.setStyleSheet("padding: 5px 10px; font-weight: bold;")
        self.save_annotation_btn.clicked.connect(self.save_annotation)
        header.addWidget(self.save_annotation_btn)

        header.addStretch()
        layout.addLayout(header)

        self.plots_container = QtWidgets.QWidget()
        self.plots_layout = QtWidgets.QVBoxLayout(self.plots_container)
        self.plots_layout.setContentsMargins(0, 5, 0, 0)
        self.plots_layout.setSpacing(2)
        layout.addWidget(self.plots_container)

        self.plot_widgets = []
        self.plot_curves = []
        self.plot_selectors = []
        self.plot_regions = []

        self.add_plot()  # Plot 1
        self.add_plot()  # Plot 2

        return widget

    def add_plot(self):
        """Add a new time series plot"""
        plot_num = len(self.plot_widgets) + 1

        if plot_num > 4:
            QtWidgets.QMessageBox.information(
                self, "Maximum Plots",
                "Maximum of 4 time series plots allowed."
            )
            return

        if plot_num >= 4:
            self.add_plot_btn.setEnabled(False)

        selector_container = QtWidgets.QWidget()
        selector_layout = QtWidgets.QHBoxLayout(selector_container)
        selector_layout.setContentsMargins(0, 0, 10, 0)

        selector_label = QtWidgets.QLabel(f"Plot {plot_num}:")
        selector_label.setStyleSheet("font-size: 11px;")
        selector_layout.addWidget(selector_label)

        selector = QtWidgets.QComboBox()
        selector.setMinimumWidth(150)
        selector.currentTextChanged.connect(lambda: self.update_timeseries_plot(plot_num - 1))
        selector_layout.addWidget(selector)

        remove_btn = QtWidgets.QPushButton("×")
        remove_btn.setFixedSize(20, 20)
        remove_btn.setStyleSheet("font-weight: bold; font-size: 14px; padding: 0px;")
        remove_btn.clicked.connect(lambda: self.remove_plot(plot_num - 1))
        if plot_num <= 2:
            remove_btn.setEnabled(False)
            remove_btn.setVisible(False)
        selector_layout.addWidget(remove_btn)

        self.plot_selectors_layout.addWidget(selector_container)
        self.plot_selectors.append(selector)

        is_last_plot = True

        if is_last_plot:
            date_axis = pg.DateAxisItem(orientation='bottom')
            plot_widget = pg.PlotWidget(axisItems={'bottom': date_axis})
            plot_widget.setLabel('bottom', 'Time')

            if len(self.plot_widgets) > 0:
                prev_last = self.plot_widgets[-1]
                prev_last.getAxis('bottom').setStyle(showValues=False)
        else:
            plot_widget = pg.PlotWidget()
            plot_widget.getAxis('bottom').setStyle(showValues=False)

        plot_widget.setBackground('w')
        plot_widget.showGrid(x=True, y=True, alpha=0.3)

        if len(self.plot_widgets) > 0:
            plot_widget.setXLink(self.plot_widgets[0])

        plot_widget.setClipToView(True)
        plot_widget.setDownsampling(auto=True, mode='peak')

        viewbox = plot_widget.getViewBox()
        viewbox.setMouseMode(pg.ViewBox.PanMode)
        viewbox.setMenuEnabled(True)
        viewbox.setAspectLocked(False)

        self.plots_layout.addWidget(plot_widget)
        self.plot_widgets.append(plot_widget)

        colors = [
            (31, 119, 180),   # Blue
            (214, 39, 40),    # Red
            (255, 127, 14),   # Orange
            (148, 103, 189)   # Purple
        ]
        curve = plot_widget.plot(
            pen=pg.mkPen(colors[plot_num - 1], width=1.5),
            connect='finite'
        )
        self.plot_curves.append(curve)

        region = pg.LinearRegionItem(
            brush=pg.mkBrush(100, 150, 255, 80),
            movable=True
        )
        region.setZValue(10)
        region.setVisible(False)
        region.sigRegionChanged.connect(lambda: self._sync_regions(plot_num - 1))
        plot_widget.addItem(region)
        self.plot_regions.append(region)

        if self.sensor_df is not None:
            numeric_columns = [
                col for col in self.sensor_df.columns
                if col != 'datetime' and pd.api.types.is_numeric_dtype(self.sensor_df[col])
            ]
            selector.blockSignals(True)
            selector.clear()
            selector.addItems(numeric_columns)
            if plot_num <= len(numeric_columns):
                selector.setCurrentIndex(plot_num - 1)
            selector.blockSignals(False)
            self.update_timeseries_plot(plot_num - 1)

    def remove_plot(self, plot_idx):
        """Remove a plot (can't remove first 2)"""
        if plot_idx < 2:
            return

        selector_widget = self.plot_selectors_layout.itemAt(plot_idx).widget()
        self.plot_selectors_layout.removeWidget(selector_widget)
        selector_widget.deleteLater()

        plot_widget = self.plot_widgets[plot_idx]
        self.plots_layout.removeWidget(plot_widget)
        plot_widget.deleteLater()

        del self.plot_selectors[plot_idx]
        del self.plot_widgets[plot_idx]
        del self.plot_curves[plot_idx]
        del self.plot_regions[plot_idx]

        self.add_plot_btn.setEnabled(True)

        if len(self.plot_widgets) > 0:
            for pw in self.plot_widgets[:-1]:
                pw.getAxis('bottom').setStyle(showValues=False)
            self.plot_widgets[-1].getAxis('bottom').setStyle(showValues=True)

    def _sync_regions(self, source_idx):
        """Synchronize brush regions between all plots"""
        if not hasattr(self, 'plot_regions') or len(self.plot_regions) == 0:
            return

        source_region = self.plot_regions[source_idx]
        new_range = source_region.getRegion()

        for i, region in enumerate(self.plot_regions):
            if i != source_idx:
                region.blockSignals(True)
                region.setRegion(new_range)
                region.blockSignals(False)

        self.on_region_changed()

    # ==================================================================
    # CSV fallbacks (invoked from the main window's File menu)
    # ==================================================================

    def load_usbl_data(self):
        """Load USBL data from CSV file (fallback)."""
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select USBL Data File", "", "CSV Files (*.csv)"
        )
        if not filename:
            return

        try:
            basename = os.path.basename(filename)
            core_name = basename.replace('.csv', '').replace('_usbl', '').replace('_USBL', '')

            df = pd.read_csv(filename)
            df['datetime'] = pd.to_datetime(df['datetime'], format='mixed', utc=True)

            # CSV mode: annotations are session-only
            self.current_dredge_id = None
            self.annotations = []
            self.refresh_annotations_list()

            self._apply_usbl_dataframe(df, core_name)
            self._status(f"Loaded USBL data: {len(df)} points")
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to load USBL data:\n{str(e)}")

    def load_sensor_data(self):
        """Load sensor data from CSV file (fallback)."""
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Sensor Data File", "", "CSV Files (*.csv)"
        )
        if not filename:
            return

        try:
            with open(filename, 'r') as f:
                lines = f.readlines()
                data_start = 0
                for i, line in enumerate(lines):
                    if not line.startswith('#'):
                        data_start = i
                        break

            df = pd.read_csv(filename, skiprows=data_start)
            df['datetime'] = pd.to_datetime(df['datetime'], format='mixed')
            if df['datetime'].dt.tz is None:
                df['datetime'] = df['datetime'].dt.tz_localize('UTC')

            self._apply_sensor_dataframe(df)
            self._status(f"Loaded sensor data: {len(df)} points")
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to load sensor data:\n{str(e)}")

    # ==================================================================
    # Plotting
    # ==================================================================

    def convert_to_utm(self):
        """Convert lat/lon to UTM coordinates"""
        if self.usbl_df is None:
            return

        lon = self.usbl_df['longitude_deg'].iloc[0]
        lat = self.usbl_df['latitude_deg'].iloc[0]

        utm_zone = int((lon + 180) / 6) + 1
        hemisphere = 'north' if lat >= 0 else 'south'

        self.utm_zone = f"{utm_zone}{hemisphere[0].upper()}"
        self.utm_epsg = f"EPSG:326{utm_zone:02d}" if hemisphere == 'north' else f"EPSG:327{utm_zone:02d}"

        self.utm_transformer = Transformer.from_crs(
            "EPSG:4326",
            self.utm_epsg,
            always_xy=True
        )

        easting, northing = self.utm_transformer.transform(
            self.usbl_df['longitude_deg'].values,
            self.usbl_df['latitude_deg'].values
        )

        self.usbl_df['easting'] = easting
        self.usbl_df['northing'] = northing

    def plot_location_data(self):
        """Plot USBL location data"""
        if self.usbl_df is None:
            return

        df_to_plot = self.usbl_df
        selected_beacon = self.beacon_selector.currentText()
        if selected_beacon != "All Beacons" and 'beacon_name' in self.usbl_df.columns:
            beacon_name = selected_beacon.split(' (')[0]
            df_to_plot = self.usbl_df[self.usbl_df['beacon_name'] == beacon_name]

        spots = [{
            'pos': (row['easting'], row['northing']),
            'data': i
        } for i, row in df_to_plot.iterrows()]

        self.location_scatter.setData(spots=spots)
        self.location_plot.autoRange()

    def update_beacon_filter(self):
        """Update location plot when beacon filter changes"""
        self.plot_location_data()
        if len(self.plot_regions) > 0 and self.plot_regions[0].isVisible():
            self.on_region_changed()

    def update_timeseries_plot(self, plot_idx):
        """Update time series plot with selected column"""
        if self.sensor_df is None:
            return

        if plot_idx >= len(self.plot_widgets):
            return

        column = self.plot_selectors[plot_idx].currentText()
        plot_widget = self.plot_widgets[plot_idx]
        curve = self.plot_curves[plot_idx]

        if not column:
            return

        viewbox = plot_widget.getViewBox()
        had_data = curve.xData is not None and len(curve.xData) > 0
        if had_data:
            x_range, y_range = viewbox.viewRange()
        else:
            x_range = y_range = None

        valid_mask = self.sensor_df[column].notna()
        valid_data = self.sensor_df[valid_mask].reset_index(drop=True)

        if len(valid_data) == 0:
            curve.setData([], [])
            return

        time_values = valid_data['datetime'].values.astype('datetime64[s]').astype(np.float64)
        y_values = valid_data[column].values

        curve.setData(time_values, y_values)
        plot_widget.setLabel('left', column)

        if had_data and x_range is not None:
            viewbox.disableAutoRange()
            viewbox.setXRange(x_range[0], x_range[1], padding=0)
            viewbox.setYRange(y_range[0], y_range[1], padding=0)
        else:
            viewbox.enableAutoRange(axis='x')
            viewbox.enableAutoRange(axis='y')

    def toggle_brush_mode(self, checked):
        """Toggle between pan mode and brush selection mode"""
        if checked:
            self.brush_mode_btn.setText("🖌️ Brush Mode ON")
            self.save_annotation_btn.setEnabled(True)

            for plot_widget in self.plot_widgets:
                viewbox = plot_widget.getViewBox()
                viewbox.setMouseMode(pg.ViewBox.RectMode)

            if self.sensor_df is not None and len(self.sensor_df) > 0 and len(self.plot_widgets) > 0:
                viewbox = self.plot_widgets[0].getViewBox()
                x_range = viewbox.viewRange()[0]
                center = (x_range[0] + x_range[1]) / 2
                width = (x_range[1] - x_range[0]) * 0.2
                region_range = [center - width / 2, center + width / 2]

                for region in self.plot_regions:
                    region.setRegion(region_range)
                    region.setVisible(True)
        else:
            self.brush_mode_btn.setText("🖌️ Brush Selection")
            self.save_annotation_btn.setEnabled(False)

            for plot_widget in self.plot_widgets:
                viewbox = plot_widget.getViewBox()
                viewbox.setMouseMode(pg.ViewBox.PanMode)

            for region in self.plot_regions:
                region.setVisible(False)

            self.location_selection_scatter.setData([])
            self._status("Brush selection disabled")

    def on_region_changed(self):
        """Handle region selection change - update location plot"""
        if self.sensor_df is None or self.usbl_df is None:
            return

        if len(self.plot_regions) == 0:
            return

        min_time, max_time = self.plot_regions[0].getRegion()

        min_dt = pd.Timestamp(min_time, unit='s', tz='UTC')
        max_dt = pd.Timestamp(max_time, unit='s', tz='UTC')

        mask = (self.usbl_df['datetime'] >= min_dt) & (self.usbl_df['datetime'] <= max_dt)
        selected_usbl = self.usbl_df[mask]

        selected_beacon = self.beacon_selector.currentText()
        if selected_beacon != "All Beacons" and 'beacon_name' in selected_usbl.columns:
            beacon_name = selected_beacon.split(' (')[0]
            selected_usbl = selected_usbl[selected_usbl['beacon_name'] == beacon_name]

        if len(selected_usbl) > 0:
            spots = [{
                'pos': (row['easting'], row['northing']),
                'data': i
            } for i, row in selected_usbl.iterrows()]
            self.location_selection_scatter.setData(spots=spots)
        else:
            self.location_selection_scatter.setData([])

        self._status(
            f"Selected: {len(selected_usbl)} USBL points | "
            f"Time range: {min_dt.strftime('%H:%M:%S')} - {max_dt.strftime('%H:%M:%S')}"
        )

    # ==================================================================
    # Annotations
    # ==================================================================

    @staticmethod
    def sanitize_field_name(name):
        """Sanitize annotation name for use as GIS field name"""
        import re
        sanitized = name.replace(' ', '_')
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '', sanitized)
        sanitized = sanitized.lower()
        sanitized = sanitized[:50]
        return sanitized

    def save_annotation(self):
        """Save the current selected region as an annotation with full metadata"""
        if self.usbl_df is None or self.sensor_df is None:
            QtWidgets.QMessageBox.warning(self, "No Data", "Please load both USBL and sensor data first.")
            return

        if len(self.plot_regions) == 0 or not self.plot_regions[0].isVisible():
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please enable brush mode and select a region first.")
            return

        min_time, max_time = self.plot_regions[0].getRegion()
        min_dt = pd.Timestamp(min_time, unit='s', tz='UTC')
        max_dt = pd.Timestamp(max_time, unit='s', tz='UTC')

        mask = (self.usbl_df['datetime'] >= min_dt) & (self.usbl_df['datetime'] <= max_dt)
        selected_usbl = self.usbl_df[mask]

        if len(selected_usbl) == 0:
            QtWidgets.QMessageBox.warning(self, "No Data", "No USBL points found in selected time range.")
            return

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Save Annotation")
        dialog_layout = QtWidgets.QVBoxLayout(dialog)

        dialog_layout.addWidget(QtWidgets.QLabel("Annotation Name:"))
        name_input = QtWidgets.QLineEdit()
        name_input.setPlaceholderText("e.g., effective_dredging, transit, on_bottom")
        dialog_layout.addWidget(name_input)

        dialog_layout.addWidget(QtWidgets.QLabel("Notes (optional):"))
        notes_input = QtWidgets.QTextEdit()
        notes_input.setPlaceholderText("Additional details about this annotation...")
        notes_input.setMaximumHeight(80)
        dialog_layout.addWidget(notes_input)

        preview_label = QtWidgets.QLabel(
            f"Time range: {min_dt.strftime('%Y-%m-%d %H:%M:%S')} to {max_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"USBL points: {len(selected_usbl)}"
        )
        preview_label.setStyleSheet("color: gray; font-size: 10px;")
        dialog_layout.addWidget(preview_label)

        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        dialog_layout.addWidget(btn_box)

        if dialog.exec() == QtWidgets.QDialog.Accepted:
            name = name_input.text().strip()
            if not name:
                QtWidgets.QMessageBox.warning(self, "Invalid Name", "Please enter an annotation name.")
                return

            existing_names = [ann['annotation_name'] for ann in self.annotations]
            if name in existing_names:
                QtWidgets.QMessageBox.warning(
                    self, "Duplicate Name",
                    f"An annotation named '{name}' already exists.\n\n"
                    "Please choose a different name."
                )
                return

            start_point = selected_usbl.iloc[0]
            end_point = selected_usbl.iloc[-1]

            annotation = {
                'annotation_id': self.annotation_id_counter,
                'annotation_name': name,
                'start_datetime': min_dt,
                'end_datetime': max_dt,
                'start_lat': start_point.get('latitude', None),
                'start_lon': start_point.get('longitude', None),
                'end_lat': end_point.get('latitude', None),
                'end_lon': end_point.get('longitude', None),
                'start_easting': start_point['easting'],
                'start_northing': start_point['northing'],
                'end_easting': end_point['easting'],
                'end_northing': end_point['northing'],
                'utm_zone': self.utm_zone,
                'num_usbl_points': len(selected_usbl),
                'notes': notes_input.toPlainText().strip()
            }

            if self.store is not None and self.current_dredge_id is not None:
                # Persist and reload so ids come from the database.
                self.store.add_annotation(self.current_dredge_id, annotation)
                self.annotations = self.store.fetch_annotations(self.current_dredge_id)
            else:
                self.annotations.append(annotation)
                self.annotation_id_counter += 1

            self.refresh_annotations_list()
            self._status(f"Annotation '{name}' saved ({len(selected_usbl)} points)")

    def refresh_annotations_list(self):
        """Refresh the annotations list widget"""
        self.annotations_list.clear()
        for ann in self.annotations:
            item_text = f"[{ann['annotation_id']}] {ann['annotation_name']} ({ann['num_usbl_points']} pts)"
            self.annotations_list.addItem(item_text)

    def on_annotation_selected(self):
        """Handle annotation selection in the list"""
        self.delete_annotation_btn.setEnabled(len(self.annotations_list.selectedItems()) > 0)

    def delete_annotation(self):
        """Delete the selected annotation"""
        selected_items = self.annotations_list.selectedItems()
        if not selected_items:
            return

        selected_index = self.annotations_list.row(selected_items[0])
        ann = self.annotations[selected_index]

        reply = QtWidgets.QMessageBox.question(
            self, "Delete Annotation",
            f"Delete annotation '{ann['annotation_name']}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if reply == QtWidgets.QMessageBox.Yes:
            if self.store is not None and self.current_dredge_id is not None:
                self.store.delete_annotation(ann['annotation_id'])
                self.annotations = self.store.fetch_annotations(self.current_dredge_id)
            else:
                self.annotations.pop(selected_index)
            self.refresh_annotations_list()
            self._status(f"Annotation '{ann['annotation_name']}' deleted")

    def clear_annotations(self):
        """Clear all annotations"""
        if len(self.annotations) == 0:
            return

        reply = QtWidgets.QMessageBox.question(
            self, "Clear All Annotations",
            f"Delete all {len(self.annotations)} annotations?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if reply == QtWidgets.QMessageBox.Yes:
            if self.store is not None and self.current_dredge_id is not None:
                self.store.clear_annotations(self.current_dredge_id)
            self.annotations = []
            self.refresh_annotations_list()
            self._status("All annotations cleared")

    # ==================================================================
    # Export
    # ==================================================================

    def export_annotated_data(self):
        """Export USBL data with annotations in selected format(s)"""
        export_csv = self.export_csv_checkbox.isChecked()
        export_sensor_csv = self.export_sensor_csv_checkbox.isChecked()
        export_gpkg = self.export_gpkg_checkbox.isChecked()

        if not export_csv and not export_sensor_csv and not export_gpkg:
            QtWidgets.QMessageBox.warning(
                self, "No Format Selected",
                "Please select at least one export format."
            )
            return

        if (export_csv or export_gpkg) and self.usbl_df is None:
            QtWidgets.QMessageBox.warning(self, "No Data", "No USBL data loaded.")
            return

        if export_sensor_csv and (self.sensor_df is None or self.sensor_df.empty):
            QtWidgets.QMessageBox.warning(self, "No Data", "No sensor/winch data loaded.")
            return

        output_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if not output_dir:
            return

        try:
            output_dir = os.path.normpath(output_dir)

            if not os.path.isdir(output_dir):
                raise ValueError(f"Selected path is not a directory: {output_dir}")

            test_file = os.path.join(output_dir, ".write_test")
            try:
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
            except (PermissionError, IOError) as e:
                raise PermissionError(f"Cannot write to directory: {output_dir}\n\n{str(e)}")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = f"{self.core_name}_{timestamp}" if self.core_name else f"export_{timestamp}"

            exported_files = []

            # Dredge-level metadata (e.g. USBL distance) included in exports.
            dredge_meta = {}
            if self.store is not None and self.current_dredge_id is not None:
                dredge = self.store.get_dredge(self.current_dredge_id)
                if dredge:
                    dredge_meta = {
                        'dredge_name': dredge['dredge_name'],
                        'usbl_distance_m': dredge['usbl_distance_m'],
                    }

            usbl_export = None
            if export_csv or export_gpkg:
                usbl_export = self.usbl_df.copy()

                for ann in self.annotations:
                    original_name = ann['annotation_name']
                    sanitized_name = self.sanitize_field_name(original_name)

                    mask = (usbl_export['datetime'] >= ann['start_datetime']) & \
                           (usbl_export['datetime'] <= ann['end_datetime'])

                    usbl_export[sanitized_name] = mask

            # === CSV EXPORT (USBL + metadata) ===
            if export_csv:
                if len(self.annotations) > 0:
                    annotations_df = pd.DataFrame(self.annotations)
                    for key, value in dredge_meta.items():
                        annotations_df[key] = value
                    metadata_filename = f"{prefix}_metadata.csv"
                    metadata_path = os.path.normpath(os.path.join(output_dir, metadata_filename))
                    annotations_df.to_csv(metadata_path, index=False)
                    exported_files.append(f"✓ {metadata_filename} ({len(self.annotations)} annotations)")

                usbl_csv_filename = f"{prefix}_usbl_annotated.csv"
                usbl_csv_path = os.path.normpath(os.path.join(output_dir, usbl_csv_filename))
                usbl_export.to_csv(usbl_csv_path, index=False)
                ann_count = len(self.annotations) if self.annotations else 0
                exported_files.append(
                    f"✓ {usbl_csv_filename} ({len(usbl_export)} points, {ann_count} annotation columns)"
                )

            # === CSV EXPORT (sensor + winch time series) ===
            if export_sensor_csv:
                sensor_export = self.sensor_df.copy()
                if pd.api.types.is_datetime64_any_dtype(sensor_export['datetime']):
                    if getattr(sensor_export['datetime'].dt, 'tz', None) is not None:
                        sensor_export['datetime'] = sensor_export['datetime'].dt.tz_localize(None)

                sensor_csv_filename = f"{prefix}_sensor_winch.csv"
                sensor_csv_path = os.path.normpath(os.path.join(output_dir, sensor_csv_filename))
                sensor_export.to_csv(sensor_csv_path, index=False)
                exported_files.append(
                    f"✓ {sensor_csv_filename} ({len(sensor_export)} rows, {len(sensor_export.columns)} columns)"
                )

            # === GEOPACKAGE EXPORT (built-in writer, no GDAL) ===
            if export_gpkg:
                from ..persistence.gpkg import write_gpkg_points

                epsg = 32610
                if self.utm_epsg and ":" in self.utm_epsg:
                    epsg = int(self.utm_epsg.split(":")[1])

                gpkg_filename = f"{prefix}.gpkg"
                gpkg_path = os.path.normpath(os.path.join(output_dir, gpkg_filename))
                n_written = write_gpkg_points(
                    usbl_export, gpkg_path, layer='usbl_points', epsg=epsg,
                    x_col='easting', y_col='northing',
                )

                ann_count = len(self.annotations) if self.annotations else 0
                exported_files.append(
                    f"✓ {gpkg_filename} (Point layer: {n_written} points, {ann_count} annotation columns)"
                )

            files_list = "\n".join(exported_files)
            QtWidgets.QMessageBox.information(
                self, "Export Complete",
                f"Exported to: {output_dir}\n\n{files_list}"
            )

            self._status(f"Export complete: {len(exported_files)} file(s)")

        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "Export Error", f"Failed to export:\n{str(e)}")
