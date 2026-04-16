"""
AnalysisController - Central coordinator for the application.

Manages mode switching, data flow between panels/views, and calls
into domain processing logic. This keeps the GUI panels thin and
the business logic testable.

All depth columns keep their ORIGINAL CSV names throughout -- no
A/B/C/D aliasing ever occurs in this layer.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np
from scipy import stats as sp_stats

from PySide6.QtWidgets import QFileDialog, QMessageBox

from ..domain.models.sensor_data import SensorData, CorrectionRecord
from ..domain.models.calibration import DepthCalibration
from ..domain.models.analysis_result import StatisticsResult, TimeOffsetResult
from ..domain.processing.depth_correction import DepthCorrectionProcessor
from ..domain.processing.time_correction import TimeCorrectionProcessor
from ..domain.processing.trip_detection import TripDetectionProcessor
from ..domain.processing.calibration_builder import CalibrationBuilder
from ..domain.processing.statistics import compute_statistics
from ..domain.processing.piston_position import (
    compute_piston_position, detect_start_core,
)
from ..domain.processing.calculations import (
    compute_calculations, format_results, apply_savgol,
)
from ..gui.views.calculation_plot_view import GeometryInput, WEIGHT_LENGTH
from ..persistence.csv_loader import CSVLoader
from ..persistence.calibration_io import CalibrationIO


class AnalysisController:
    """
    Coordinates all application logic.

    Holds references to GUI panels and views, connects signals,
    and delegates to domain processing.
    """

    def __init__(self):
        # State
        self.sensor_data: Optional[SensorData] = None      # Primary data
        self.original_data: Optional[SensorData] = None     # Backup for reset
        self._loaded_file_path: Optional[str] = None        # Full path to loaded file
        self.calibration: Optional[DepthCalibration] = None
        self.generated_calibration: Optional[DepthCalibration] = None
        self.time_offset_results: Optional[list[TimeOffsetResult]] = None
        self.trip_detection_result = None
        self._heave_profiles: Optional[dict[str, np.ndarray]] = None
        self._heave_time_axis: Optional[np.ndarray] = None
        self._heave_fs: Optional[float] = None
        self._heave_sel: Optional[tuple[int, int]] = None
        self.collected_statistics: list[StatisticsResult] = []
        self._piston_start_core_idx: Optional[int] = None
        self._piston_values: Optional[np.ndarray] = None

        # GUI references (set by main_window after construction)
        self.main_window = None
        self.main_plot = None
        self.secondary_view = None  # heave plot or stats table
        self.heave_plot = None
        self.statistics_table = None
        self.trip_plot = None
        self.calculation_plot = None

        # Panels
        self.view_panel = None
        self.depth_panel = None
        self.time_panel = None
        self.calibration_panel = None
        self.trip_panel = None
        self.piston_panel = None
        self.calculate_panel = None

        # Calculate mode state
        self._calc_start_core_idx: Optional[int] = None
        self._end_pen_idx: Optional[int] = None
        self._pullout_idx: Optional[int] = None
        self._last_calc_results = None
        self._last_calc_inputs: Optional[dict] = None

    # ==================================================================
    # Initialization - called by MainWindow
    # ==================================================================

    def connect_signals(self):
        """Wire up all panel signals to controller methods."""
        # View Data panel
        self.view_panel.load_file_requested.connect(self.load_export_csv)
        self.view_panel.plot_depths_requested.connect(self.plot_depths)
        self.view_panel.plot_differences_requested.connect(self.plot_differences)

        # Depth Offset panel
        self.depth_panel.load_file_requested.connect(self.load_export_csv)
        self.depth_panel.load_calibration_requested.connect(self.load_calibration)
        self.depth_panel.ref_sensor_combo.currentTextChanged.connect(
            self._update_depth_correction_plan
        )
        self.depth_panel.apply_corrections_requested.connect(self.apply_depth_corrections)
        self.depth_panel.reset_requested.connect(self.reset_to_original)
        self.depth_panel.export_requested.connect(self.export_corrected_csv)
        self.depth_panel.plot_original_requested.connect(self.plot_depths)

        # Time Offset panel
        self.time_panel.load_file_requested.connect(self.load_export_csv)
        self.time_panel.selection_mode_changed.connect(self._set_selection_mode)
        self.time_panel.clear_selection_requested.connect(self._clear_selection)
        self.time_panel.calculate_offsets_requested.connect(self.calculate_time_offsets)
        self.time_panel.apply_correction_requested.connect(self.apply_time_corrections)
        self.time_panel.reset_requested.connect(self.reset_to_original)
        self.time_panel.export_requested.connect(self.export_corrected_csv)
        self.time_panel.plot_original_requested.connect(self.plot_depths)

        # Create Calibration panel
        self.calibration_panel.load_cast_requested.connect(self._load_cast)
        self.calibration_panel.process_cast_requested.connect(self._process_cast)
        self.calibration_panel.selection_mode_changed.connect(self._set_selection_mode)
        self.calibration_panel.clear_selection_requested.connect(self._clear_selection)
        self.calibration_panel.add_statistics_requested.connect(self._add_statistics)
        self.calibration_panel.generate_calibration_requested.connect(
            self._generate_calibration
        )
        self.calibration_panel.save_calibration_requested.connect(
            self._save_calibration
        )

        # Main plot selection signal
        self.main_plot.selection_changed.connect(self._on_selection_changed)
        self.main_plot.selection_cleared.connect(self._on_selection_cleared)

        # Trip Detector panel
        self.trip_panel.load_file_requested.connect(self.load_export_csv)
        self.trip_panel.detect_trip_requested.connect(self.detect_trip)
        self.trip_panel.plot_original_requested.connect(self.plot_depths)
        self.trip_panel.export_requested.connect(self.export_trip_csv)

        # Piston Position panel
        self.piston_panel.load_file_requested.connect(self.load_export_csv)
        self.piston_panel.calculate_requested.connect(self.calculate_piston)
        self.piston_panel.plot_original_requested.connect(self.plot_depths)

        # Main plot start_core drag signal
        self.main_plot.start_core_changed.connect(self._on_start_core_moved)

        # Main plot trip line drag signal
        self.main_plot.trip_line_changed.connect(self._on_trip_line_moved)

        # Main plot end-of-penetration line drag signal
        self.main_plot.end_pen_changed.connect(self._on_end_pen_moved)

        # Main plot pullout line drag signal
        self.main_plot.pullout_changed.connect(self._on_pullout_moved)

        # Piston export
        self.piston_panel.export_piston_requested.connect(self.export_piston_csv)

        # Calculate panel
        self.calculate_panel.load_file_requested.connect(self.load_export_csv)
        self.calculate_panel.calculate_requested.connect(self.run_calculations)
        self.calculate_panel.plot_original_requested.connect(
            self._plot_calculate_mode
        )
        self.calculate_panel.export_results_requested.connect(
            self.export_calculation_results
        )
        self.calculate_panel.reset_lines_requested.connect(self._reset_lines)
        self.calculate_panel.export_diagram_requested.connect(
            self.export_calculation_diagram
        )

    # ==================================================================
    # Data Loading
    # ==================================================================

    def load_export_csv(self, file_path: str):
        """Load a Sediment App batch-export CSV file."""
        try:
            # Clear previous selection to avoid stale indices
            self.main_plot.clear_selection()

            self.sensor_data = CSVLoader.load_export_csv(file_path)
            self.original_data = self.sensor_data.copy()
            self._loaded_file_path = file_path

            # Clear stale state from previous file
            self.trip_detection_result = None
            self._piston_start_core_idx = None
            self._piston_values = None
            self._calc_start_core_idx = None
            self._end_pen_idx = None
            self._pullout_idx = None
            self._last_calc_results = None
            self._last_calc_inputs = None

            self._update_all_panels_file_info()
            self.main_plot.set_sensor_data(self.sensor_data)
            self.plot_depths()
            self._log_active(
                f"Loaded: {self.sensor_data.source_file} "
                f"({self.sensor_data.row_count:,} rows, "
                f"{self.sensor_data.num_sensors} sensors)"
            )
        except Exception as e:
            self._show_error("Load Error", str(e))
            self._log_active(f"ERROR: {e}")

    def load_calibration(self, file_path: str):
        """Load a JSON calibration file and set up mapping UI."""
        try:
            self.calibration = CalibrationIO.load(file_path)
            filename = Path(file_path).name

            info_lines = [f"Loaded calibration: {filename}"]
            for reg in self.calibration.regressions:
                info_lines.append(
                    f"  {reg.sensor_j} - {reg.sensor_i}: "
                    f"slope={reg.slope:.6f}, intercept={reg.intercept:.6f}, "
                    f"R\u00b2={reg.r_squared:.4f}"
                )

            self.depth_panel.update_calibration_info(filename, info_lines)

            # Set up calibration label -> column mapping UI
            cal_labels = self.calibration.sensor_labels
            if self.sensor_data is not None:
                self.depth_panel.setup_calibration_mapping(
                    cal_labels, self.sensor_data.depth_columns,
                )

            self._update_depth_correction_plan()
            self._log_active(f"Calibration loaded: {filename}")
        except Exception as e:
            self._show_error("Calibration Error", str(e))
            self._log_active(f"ERROR loading calibration: {e}")

    # ==================================================================
    # Plotting
    # ==================================================================

    def plot_depths(self):
        """Plot depth traces on the main plot."""
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return
        title = self.sensor_data.core_title or ''
        self.main_plot.plot_depths(self.sensor_data, title=title)

    def plot_differences(self):
        """Plot pairwise differences on the main plot."""
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return
        self.main_plot.plot_differences(self.sensor_data)

    # ==================================================================
    # Depth Offset Mode
    # ==================================================================

    def apply_depth_corrections(self):
        """
        Apply depth calibration and manual offsets.

        Uses the calibration label -> column mapping from the depth panel
        and delegates to the DepthCorrectionProcessor.
        """
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return

        try:
            # Work on a copy from original
            working = self.original_data.copy()
            panel = self.depth_panel

            panel.log_widget.log(f"\n{'='*50}")
            panel.log_widget.log("APPLYING CORRECTIONS")

            # Get calibration mapping and reference
            cal_mapping = panel.get_calibration_mapping()  # cal_label -> col_name
            ref_label = panel.get_ref_sensor()             # calibration label

            # Find corresponding column for reference
            ref_col = cal_mapping.get(ref_label)
            if ref_col is None:
                self._show_warning(
                    f"Reference sensor '{ref_label}' is not mapped to a column.\n"
                    f"Check the calibration label mapping."
                )
                return

            ref_short = SensorData.get_short_name(ref_col)
            panel.log_widget.log(
                f"Reference: {ref_label} = {ref_short} (will NOT be modified)"
            )
            panel.log_widget.log(f"{'='*50}")

            # Apply regression corrections if calibration loaded
            correction_results = {}
            if self.calibration is not None and panel.correction_checkboxes:
                enabled_targets = panel.get_enabled_calibration_targets()

                panel.log_widget.log("\nApplying depth-dependent corrections...")
                correction_results = DepthCorrectionProcessor.apply_calibration(
                    working,
                    self.calibration,
                    ref_col,
                    cal_mapping,
                    enabled_targets,
                )

                for col, stats in correction_results.items():
                    short = SensorData.get_short_name(col)
                    panel.log_widget.log(
                        f"\n{short}: correction range "
                        f"{stats['min']:+.4f}m to {stats['max']:+.4f}m"
                    )
                    panel.log_widget.log(
                        f"  Mean: {stats['mean']:+.4f}m \u00b1 {stats['std']:.4f}m"
                    )

            # Apply manual offsets
            manual = panel.get_manual_offsets()
            applied_manual = DepthCorrectionProcessor.apply_manual_offsets(
                working, manual,
            )
            if applied_manual:
                panel.log_widget.log("\nManual offsets:")
                for col, offset in applied_manual.items():
                    short = SensorData.get_short_name(col)
                    panel.log_widget.log(f"  {short}: {offset:+.4f}m")

            self.sensor_data = working
            self.main_plot.set_sensor_data(self.sensor_data)

            # Build label suffixes showing applied corrections
            suffixes = {}
            for col in working.depth_columns:
                if col in correction_results or col in applied_manual:
                    short = SensorData.get_short_name(col)
                    suffixes[col] = f" ({short} corrected)"

            self.main_plot.plot_depths_with_labels(
                self.sensor_data, suffixes,
                title=self.sensor_data.core_title or 'Corrected Data',
            )

            panel.log_widget.log("Corrections applied and plotted!")

        except Exception as e:
            self._show_error("Correction Error", str(e))
            self.depth_panel.log_widget.log(f"ERROR: {e}")

    def _update_depth_correction_plan(self, _=None):
        """Update the correction plan display based on current calibration + ref."""
        if self.calibration is None:
            self.depth_panel.update_correction_plan([])
            return

        ref = self.depth_panel.ref_sensor_combo.currentText()
        applicable = self.calibration.get_applicable_corrections(ref)
        self.depth_panel.update_correction_plan(applicable)

    # ==================================================================
    # Time Offset Mode
    # ==================================================================

    def calculate_time_offsets(self):
        """Calculate time offsets using heave cross-correlation method."""
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return

        sel = self.main_plot.selection
        if sel is None:
            self._show_warning("Please select a time range first")
            return

        try:
            start_idx, end_idx = sel
            panel = self.time_panel
            low_freq, high_freq, filter_order = panel.get_filter_params()
            ref_col = panel.get_ref_col()

            if ref_col is None:
                self._show_warning("Select a reference sensor")
                return

            ref_short = SensorData.get_short_name(ref_col)
            panel.log_widget.log(f"\n{'='*50}")
            panel.log_widget.log("CALCULATING TIME OFFSETS (Heave Cross-Correlation)")
            panel.log_widget.log(f"Range: rows {start_idx}-{end_idx}")
            panel.log_widget.log(
                f"Bandpass: {low_freq:.3f}-{high_freq:.3f} Hz, order {filter_order}"
            )
            panel.log_widget.log(f"Reference: {ref_short}")
            panel.log_widget.log(f"{'='*50}")

            # Compute heave profiles for visualization
            heaves, fs = TimeCorrectionProcessor.compute_heave_profiles(
                self.sensor_data, start_idx, end_idx,
                low_freq, high_freq, filter_order,
            )
            self._heave_profiles = heaves
            self._heave_fs = fs
            self._heave_sel = (start_idx, end_idx)

            panel.log_widget.log(
                f"Sampling rate: {fs:.2f} Hz ({1/fs:.4f}s interval)"
            )

            # Build a relative-seconds time axis for the selection
            dt_col = self.sensor_data.datetime_col
            df_sel = self.sensor_data.df.iloc[start_idx:end_idx + 1]
            timestamps = pd.to_datetime(df_sel[dt_col])
            t_sec = (timestamps - timestamps.iloc[0]).dt.total_seconds().values
            self._heave_time_axis = t_sec

            # Calculate offsets
            self.time_offset_results = TimeCorrectionProcessor.calculate_offsets(
                self.sensor_data, start_idx, end_idx,
                ref_col, low_freq, high_freq, filter_order,
            )

            for r in self.time_offset_results:
                short = SensorData.get_short_name(r.sensor_column)
                if r.is_reference:
                    panel.log_widget.log(f"{short}: 0.0000s (reference)")
                else:
                    panel.log_widget.log(
                        f"{short}: {r.offset_seconds:+.4f}s "
                        f"(heave RMS: {r.rms_value:.6f}m)"
                    )

            panel.display_offsets(self.time_offset_results)

            # Show uncorrected heave on secondary plot
            if self.heave_plot is not None:
                self.heave_plot.plot_heave_uncorrected(
                    heaves, ref_col, time_axis=t_sec,
                )
                self.main_window.show_secondary_view('heave')

            panel.log_widget.log("Offset calculation complete!")

        except Exception as e:
            self._show_error("Calculation Error", str(e))
            self.time_panel.log_widget.log(f"ERROR: {e}")

    def apply_time_corrections(self):
        """Apply calculated time offsets."""
        if self.time_offset_results is None:
            self._show_warning("Calculate offsets first")
            return

        try:
            panel = self.time_panel
            panel.log_widget.log(f"\n{'='*50}")
            panel.log_widget.log("APPLYING TIME CORRECTIONS")
            panel.log_widget.log(f"{'='*50}")

            self.sensor_data = TimeCorrectionProcessor.apply_offsets(
                self.sensor_data, self.time_offset_results
            )
            self.main_plot.set_sensor_data(self.sensor_data)

            # Build label suffixes keyed by column name
            suffixes = {}
            for r in self.time_offset_results:
                if not r.is_reference:
                    suffixes[r.sensor_column] = f" ({r.offset_seconds:+.4f}s)"
                else:
                    suffixes[r.sensor_column] = " (ref)"

            self.main_plot.plot_depths_with_labels(
                self.sensor_data, suffixes,
                title=self.sensor_data.core_title or 'Time-Corrected',
            )

            # Update heave plot to show corrected alignment
            if (self.heave_plot is not None
                    and self._heave_profiles is not None
                    and self._heave_sel is not None):
                ref_col = panel.get_ref_col()
                low_freq, high_freq, filter_order = panel.get_filter_params()
                start_idx, end_idx = self._heave_sel

                # Recompute heave on the corrected data for the same range
                heaves_corrected, _ = TimeCorrectionProcessor.compute_heave_profiles(
                    self.sensor_data, start_idx, end_idx,
                    low_freq, high_freq, filter_order,
                )

                offsets_dict = {
                    r.sensor_column: r.offset_seconds
                    for r in self.time_offset_results
                    if not r.is_reference
                }

                self.heave_plot.plot_heave_corrected(
                    heaves_original=self._heave_profiles,
                    heaves_corrected=heaves_corrected,
                    ref_col=ref_col,
                    offsets=offsets_dict,
                    time_axis=self._heave_time_axis,
                )

            for r in self.time_offset_results:
                if not r.is_reference:
                    short = SensorData.get_short_name(r.sensor_column)
                    panel.log_widget.log(
                        f"Applied {r.offset_seconds:+.4f}s shift to {short}"
                    )
            panel.log_widget.log("Time corrections applied!")

        except Exception as e:
            self._show_error("Correction Error", str(e))
            self.time_panel.log_widget.log(f"ERROR: {e}")

    # ==================================================================
    # Create Calibration Mode
    # ==================================================================

    def _load_cast(self, file_path: str):
        """Load a cast file for calibration creation."""
        try:
            panel = self.calibration_panel
            panel.cast_label.setText(
                f"File: {Path(file_path).name}\nReady to process."
            )
            self._cast_file_path = file_path
            panel.log_widget.log(f"Cast selected: {Path(file_path).name}")
        except Exception as e:
            self._show_error("Load Error", str(e))

    def _process_cast(self):
        """Process the loaded cast with given parameters."""
        if not hasattr(self, '_cast_file_path'):
            self._show_warning("Load a cast file first")
            return

        try:
            panel = self.calibration_panel
            params = panel.get_processing_params()
            patterns = panel.get_sensor_patterns()

            panel.log_widget.log(f"\nProcessing with patterns: {patterns}")

            data = CSVLoader.load_sensor_csv(
                self._cast_file_path,
                sensor_patterns=patterns,
                datetime_col=params['datetime_col'],
                skip_rows=params['skip_rows'],
            )

            panel.log_widget.log(
                f"Loaded {data.row_count} rows, {data.num_sensors} sensors"
            )

            # Filter by depth
            df = data.df
            depth_cols = data.depth_columns
            existing = [c for c in depth_cols if c in df.columns]

            filter_depth = df[existing[0]].copy()
            for col in existing[1:]:
                filter_depth = filter_depth.fillna(df[col])

            mask = (
                (filter_depth >= params['min_depth'])
                & (filter_depth <= params['max_depth'])
            )
            df = df[mask].copy()
            panel.log_widget.log(f"After depth filter: {len(df)} rows")

            # Trim
            trim = params['trim_rows']
            if len(df) > trim * 2:
                df = df.iloc[trim:-trim].copy()
                panel.log_widget.log(f"After trim: {len(df)} rows")

            # Smooth
            smooth = params['smooth_window']
            for col in existing:
                df[col] = df[col].rolling(window=smooth, min_periods=1).mean()

            df = df.reset_index(drop=True)
            data.update_dataframe(df)

            self.sensor_data = data
            self.original_data = data.copy()
            self.main_plot.set_sensor_data(self.sensor_data)
            self.main_plot.plot_depths(self.sensor_data)

            panel.update_cast_info(
                data.source_file, data.num_sensors, data.row_count,
            )
            self._update_all_panels_file_info()
            panel.log_widget.log("Cast processed and plotted!")

        except Exception as e:
            self._show_error("Processing Error", str(e))
            self.calibration_panel.log_widget.log(f"ERROR: {e}")

    def _add_statistics(self):
        """Add statistics from current selection to the collection."""
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return

        sel = self.main_plot.selection
        if sel is None:
            self._show_warning("Select a range first")
            return

        try:
            start_idx, end_idx = sel

            stats = compute_statistics(self.sensor_data, start_idx, end_idx)
            self.collected_statistics.append(stats)

            # Update stats table
            if self.statistics_table is not None:
                if self.statistics_table.count == 0:
                    self.statistics_table.set_columns(
                        self.sensor_data.depth_columns,
                    )
                self.statistics_table.add_statistics(stats)

            self.calibration_panel.update_stats_count(
                len(self.collected_statistics),
            )
            self.calibration_panel.log_widget.log(
                f"Added stats: depth={stats.mean_depth_all_sensors:.1f}m, "
                f"n={stats.n_points}"
            )

        except Exception as e:
            self._show_error("Statistics Error", str(e))
            self.calibration_panel.log_widget.log(f"ERROR: {e}")

    def _generate_calibration(self):
        """Generate a calibration from collected statistics."""
        if len(self.collected_statistics) < 2:
            self._show_warning("Need at least 2 statistics entries")
            return

        try:
            panel = self.calibration_panel
            n = panel.num_sensors_spin.value()

            # Build col_to_label mapping from column position
            # The calibration file uses A, B, C ... labels
            from ..domain.processing.calibration_builder import DEFAULT_CAL_LABELS
            labels = DEFAULT_CAL_LABELS[:n]
            col_to_label = None
            if self.sensor_data is not None:
                cols = self.sensor_data.depth_columns[:n]
                col_to_label = {col: label for col, label in zip(cols, labels)}

            self.generated_calibration = CalibrationBuilder.build(
                self.collected_statistics, n, labels,
                col_to_label=col_to_label,
            )

            # Build summary
            summary_lines = ["Calibration generated:"]
            for reg in self.generated_calibration.regressions:
                summary_lines.append(
                    f"  {reg.sensor_j}-{reg.sensor_i}: "
                    f"y={reg.slope:.6f}x + {reg.intercept:.6f} "
                    f"(R\u00b2={reg.r_squared:.4f})"
                )
            summary = "\n".join(summary_lines)

            panel.update_calibration_summary(summary)
            panel.log_widget.log(summary)

        except Exception as e:
            self._show_error("Generation Error", str(e))
            self.calibration_panel.log_widget.log(f"ERROR: {e}")

    def _save_calibration(self, file_path: str):
        """Save generated calibration to file."""
        if self.generated_calibration is None:
            self._show_warning("Generate a calibration first")
            return

        try:
            CalibrationIO.save(self.generated_calibration, file_path)
            self.calibration_panel.log_widget.log(
                f"Saved calibration to {Path(file_path).name}"
            )
        except Exception as e:
            self._show_error("Save Error", str(e))

    # ==================================================================
    # Trip Detector Mode
    # ==================================================================

    def detect_trip(self):
        """Detect sensor trip point using Savitzky-Golay divergence."""
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return

        try:
            panel = self.trip_panel
            sg_window, sg_poly = panel.get_sg_params()
            deriv_order = panel.get_derivative_order()
            threshold = panel.get_threshold()
            sampling_rate = panel.get_sampling_rate()
            edge_buffer = panel.get_edge_buffer()

            panel.log_widget.log(f"\n{'='*50}")
            panel.log_widget.log("TRIP DETECTION")
            panel.log_widget.log(f"SG window={sg_window}, poly={sg_poly}")
            panel.log_widget.log(f"Derivative order={deriv_order}")
            panel.log_widget.log(f"Threshold={threshold}, Rate={sampling_rate} Hz")
            panel.log_widget.log(f"Edge buffer={edge_buffer} samples")
            panel.log_widget.log(f"{'='*50}")

            # Build depth arrays keyed by column name (interpolated)
            depths = {}
            for col in self.sensor_data.depth_columns:
                if col in self.sensor_data.df.columns:
                    vals = (
                        self.sensor_data.df[col]
                        .interpolate().ffill().bfill().values
                    )
                    depths[col] = vals

            if len(depths) < 2:
                self._show_warning("Need at least 2 sensors for trip detection")
                return

            timestamps = self.sensor_data.get_timestamps()

            result = TripDetectionProcessor.detect_trip(
                depths, timestamps,
                sg_window=sg_window,
                sg_poly=sg_poly,
                derivative_order=deriv_order,
                std_threshold=threshold,
                sampling_rate=sampling_rate,
                edge_buffer=edge_buffer,
            )

            # Log results
            panel.log_widget.log(f"\n{result.summary}")
            panel.display_result(result.summary)

            self.trip_detection_result = result

            # Auto-fill trip time on piston panel
            if self.piston_panel is not None and result.trip_datetime is not None:
                self.piston_panel.set_trip_time(
                    str(result.trip_datetime), source='trip detector',
                )

            # Auto-fill trip time on calculate panel
            if self.calculate_panel is not None and result.trip_datetime is not None:
                self.calculate_panel.set_trip_time(
                    str(result.trip_datetime), source='trip detector',
                )

            # Show trip line on the main depth plot
            self.plot_depths()
            self.main_plot.add_trip_line(result.trip_index)

            # Show derivative plots on secondary view
            if self.trip_plot is not None:
                self.trip_plot.plot_trip_result(result)
                self.main_window.show_secondary_view('trip')

            panel.log_widget.log("Trip detection complete!")

        except Exception as e:
            self._show_error("Trip Detection Error", str(e))
            self.trip_panel.log_widget.log(f"ERROR: {e}")

    # ==================================================================
    # Piston Position Mode
    # ==================================================================

    def calculate_piston(self):
        """Calculate and plot the piston position estimate."""
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return

        panel = self.piston_panel
        ws_col = panel.get_weight_stand_col()
        rel_col = panel.get_release_col()
        scope_ft = panel.get_scope()
        core_ft = panel.get_core_length()
        offset_constant = panel.get_offset_constant()

        if ws_col is None or rel_col is None:
            self._show_warning("Select both Weight Stand and Release Device sensors")
            return
        if scope_ft <= 0 or core_ft <= 0:
            self._show_warning("Scope and Core Length must be > 0")
            return

        try:
            if ws_col not in self.sensor_data.df.columns:
                self._show_warning(
                    f"Weight Stand column not found: "
                    f"{SensorData.get_short_name(ws_col)}"
                )
                return
            if rel_col not in self.sensor_data.df.columns:
                self._show_warning(
                    f"Release Device column not found: "
                    f"{SensorData.get_short_name(rel_col)}"
                )
                return

            ws_vals = (
                self.sensor_data.df[ws_col]
                .interpolate().ffill().bfill().values
            )
            rel_vals = (
                self.sensor_data.df[rel_col]
                .interpolate().ffill().bfill().values
            )

            # Determine trip index for gating start_core detection
            trip_idx = self._resolve_trip_index()

            # Detect start_core (only searches AFTER trip_idx)
            start_idx = detect_start_core(
                ws_vals, rel_vals, scope_ft, trip_idx=trip_idx,
            )
            self._piston_start_core_idx = start_idx

            n_total = len(ws_vals)
            if start_idx >= n_total - 1:
                panel.log_widget.log(
                    "Warning: start_core not detected – the "
                    "|release − weight_stand| separation never "
                    "exceeded scope after the trip point.  "
                    "You can drag the red start-core line to "
                    "set it manually."
                )

            self._plot_piston(
                ws_vals, rel_vals, scope_ft, core_ft, start_idx,
                offset_constant,
            )

            # Update panel info
            dt_col = self.sensor_data.datetime_col
            ts_str = ''
            if (dt_col in self.sensor_data.df.columns
                    and 0 <= start_idx < len(self.sensor_data.df)):
                ts = self.sensor_data.df[dt_col].iloc[start_idx]
                if pd.notna(ts):
                    ts_str = str(ts)
            panel.update_start_core_info(start_idx, ts_str)

            ws_short = SensorData.get_short_name(ws_col)
            rel_short = SensorData.get_short_name(rel_col)
            panel.log_widget.log(
                f"Weight Stand: {ws_short}, Release: {rel_short}"
            )
            panel.log_widget.log(
                f"Scope: {scope_ft} ft, Core length: {core_ft} ft"
            )
            panel.log_widget.log(f"Offset constant: {offset_constant} m")
            panel.log_widget.log(f"Trip index (gate): {trip_idx}")
            panel.log_widget.log(f"Start core detected at index {start_idx}")
            if ts_str:
                panel.log_widget.log(f"  Time: {ts_str}")
            panel.log_widget.log("Piston position plotted!")

        except Exception as e:
            self._show_error("Piston Calculation Error", str(e))
            panel.log_widget.log(f"ERROR: {e}")

    def _plot_piston(self, ws_vals, rel_vals, scope_ft, core_ft, start_idx,
                     offset_constant: float = 1.25):
        """Compute piston position and overlay on the depth plot."""
        piston = compute_piston_position(
            ws_vals, rel_vals, scope_ft, core_ft, start_idx,
            offset_constant=offset_constant,
        )
        x = self.sensor_data.get_timestamps_epoch()

        # Plot base depth traces first
        self.plot_depths()

        # Re-add trip line if we have a result (plot_depths clears it)
        if (hasattr(self, 'trip_detection_result')
                and self.trip_detection_result is not None):
            self.main_plot.add_trip_line(
                self.trip_detection_result.trip_index,
            )

        # Store piston values for export
        self._piston_values = piston

        # Add piston trace
        self.main_plot.add_piston_trace(x, piston)

        # Add draggable start_core line
        if 0 <= start_idx < len(x):
            self.main_plot.add_start_core_line(float(x[start_idx]))

    def _resolve_trip_index(self) -> int:
        """Determine the trip gate index for start_core detection.

        Priority:
        1. Trip time entered / selected on the piston panel (epoch).
        2. Trip detection result stored from the trip-detector mode.
        3. Fallback: 0 (search from beginning).
        """
        if self.sensor_data is None:
            return 0

        panel = self.piston_panel
        trip_epoch = panel.get_trip_time_epoch()

        # Check if the panel has a meaningful trip time set
        # (QDateTimeEdit defaults to 2000-01-01 -> epoch ~946684800)
        if trip_epoch > 946684800:
            x = self.sensor_data.get_timestamps_epoch()
            if len(x) > 0:
                idx = int(np.searchsorted(x, trip_epoch))
                return min(idx, len(x) - 1)

        # No panel trip time -- try stored detection result
        if (hasattr(self, 'trip_detection_result')
                and self.trip_detection_result is not None):
            return self.trip_detection_result.trip_index

        return 0

    def _on_start_core_moved(self, new_idx: int):
        """Handle the user dragging the start_core line to a new position."""
        if self.sensor_data is None:
            return
        mode = (
            self.main_window.get_current_mode() if self.main_window else None
        )

        # Handle Calculate mode: just update the stored index and panel label
        if mode == 'Calculate':
            self._calc_start_core_idx = new_idx
            dt_col = self.sensor_data.datetime_col
            ts_str = ''
            if (dt_col in self.sensor_data.df.columns
                    and 0 <= new_idx < len(self.sensor_data.df)):
                ts = self.sensor_data.df[dt_col].iloc[new_idx]
                if pd.notna(ts):
                    ts_str = str(ts)
            self.calculate_panel.update_start_core_info(new_idx, ts_str)
            self.calculate_panel.log_widget.log(
                f"Start core moved to index {new_idx}"
            )
            return

        if mode != 'Piston Position':
            return

        panel = self.piston_panel
        ws_col = panel.get_weight_stand_col()
        rel_col = panel.get_release_col()
        scope_ft = panel.get_scope()
        core_ft = panel.get_core_length()
        offset_constant = panel.get_offset_constant()

        if ws_col is None or rel_col is None:
            return

        try:
            ws_vals = (
                self.sensor_data.df[ws_col]
                .interpolate().ffill().bfill().values
            )
            rel_vals = (
                self.sensor_data.df[rel_col]
                .interpolate().ffill().bfill().values
            )

            self._piston_start_core_idx = new_idx

            # Recompute piston with new start_core and update trace in-place
            piston = compute_piston_position(
                ws_vals, rel_vals, scope_ft, core_ft, new_idx,
                offset_constant=offset_constant,
            )
            self._piston_values = piston
            self.main_plot.update_piston_trace(piston)

            # Update panel info
            dt_col = self.sensor_data.datetime_col
            ts_str = ''
            if (dt_col in self.sensor_data.df.columns
                    and 0 <= new_idx < len(self.sensor_data.df)):
                ts = self.sensor_data.df[dt_col].iloc[new_idx]
                if pd.notna(ts):
                    ts_str = str(ts)
            panel.update_start_core_info(new_idx, ts_str)
            panel.log_widget.log(f"Start core moved to index {new_idx}")

        except Exception as e:
            panel.log_widget.log(f"ERROR updating piston: {e}")

    def _on_trip_line_moved(self, new_idx: int):
        """Handle the user dragging the trip line to a new position."""
        if self.sensor_data is None:
            return

        # Update stored trip index in detection result (if available)
        if self.trip_detection_result is not None:
            self.trip_detection_result.trip_index = new_idx

        # Update the trip time widget on the piston panel
        if self.piston_panel is not None:
            dt_col = self.sensor_data.datetime_col
            if (dt_col in self.sensor_data.df.columns
                    and 0 <= new_idx < len(self.sensor_data.df)):
                ts = self.sensor_data.df[dt_col].iloc[new_idx]
                if pd.notna(ts):
                    self.piston_panel.set_trip_time(str(ts), source='plot drag')

        # Update the trip time widget on the calculate panel
        if self.calculate_panel is not None:
            dt_col = self.sensor_data.datetime_col
            if (dt_col in self.sensor_data.df.columns
                    and 0 <= new_idx < len(self.sensor_data.df)):
                ts = self.sensor_data.df[dt_col].iloc[new_idx]
                if pd.notna(ts):
                    self.calculate_panel.set_trip_time(
                        str(ts), source='plot drag',
                    )

        mode = (
            self.main_window.get_current_mode() if self.main_window else None
        )

        # Handle Calculate mode – just log the move
        if mode == 'Calculate':
            self.calculate_panel.log_widget.log(
                f"Trip line moved to index {new_idx}"
            )
            return

        # If piston has already been calculated, recalculate with new trip gate
        if mode != 'Piston Position' or self._piston_start_core_idx is None:
            return

        panel = self.piston_panel
        ws_col = panel.get_weight_stand_col()
        rel_col = panel.get_release_col()
        scope_ft = panel.get_scope()
        core_ft = panel.get_core_length()
        offset_constant = panel.get_offset_constant()

        if ws_col is None or rel_col is None or scope_ft <= 0 or core_ft <= 0:
            return

        try:
            ws_vals = (
                self.sensor_data.df[ws_col]
                .interpolate().ffill().bfill().values
            )
            rel_vals = (
                self.sensor_data.df[rel_col]
                .interpolate().ffill().bfill().values
            )

            start_idx = self._piston_start_core_idx

            # If start_core would now be before the new trip gate, re-detect it
            if start_idx < new_idx:
                start_idx = detect_start_core(
                    ws_vals, rel_vals, scope_ft, trip_idx=new_idx,
                )
                self._piston_start_core_idx = start_idx

                # Move the start_core line to the new position
                x_all = self.sensor_data.get_timestamps_epoch()
                if 0 <= start_idx < len(x_all):
                    self.main_plot.remove_start_core_line()
                    self.main_plot.add_start_core_line(float(x_all[start_idx]))

                # Update start_core info in panel
                dt_col = self.sensor_data.datetime_col
                ts_str = ''
                if (dt_col in self.sensor_data.df.columns
                        and 0 <= start_idx < len(self.sensor_data.df)):
                    ts = self.sensor_data.df[dt_col].iloc[start_idx]
                    if pd.notna(ts):
                        ts_str = str(ts)
                panel.update_start_core_info(start_idx, ts_str)

            piston = compute_piston_position(
                ws_vals, rel_vals, scope_ft, core_ft, start_idx,
                offset_constant=offset_constant,
            )
            self._piston_values = piston
            self.main_plot.update_piston_trace(piston)
            panel.log_widget.log(
                f"Trip line moved to index {new_idx}, piston recalculated"
            )

        except Exception as e:
            panel.log_widget.log(f"ERROR updating piston after trip move: {e}")

    def _on_end_pen_moved(self, new_idx: int):
        """Handle the user dragging the end-of-penetration line."""
        if self.sensor_data is None:
            return

        self._end_pen_idx = new_idx

        # Update the panel label
        dt_col = self.sensor_data.datetime_col
        ts_str = ''
        if (dt_col in self.sensor_data.df.columns
                and 0 <= new_idx < len(self.sensor_data.df)):
            ts = self.sensor_data.df[dt_col].iloc[new_idx]
            if pd.notna(ts):
                ts_str = str(ts)
        self.calculate_panel.update_end_pen_info(new_idx, ts_str)
        self.calculate_panel.log_widget.log(
            f"End-of-penetration line moved to index {new_idx}"
        )

    def _on_pullout_moved(self, new_idx: int):
        """Handle the user dragging the pullout line."""
        if self.sensor_data is None:
            return

        self._pullout_idx = new_idx

        dt_col = self.sensor_data.datetime_col
        ts_str = ''
        if (dt_col in self.sensor_data.df.columns
                and 0 <= new_idx < len(self.sensor_data.df)):
            ts = self.sensor_data.df[dt_col].iloc[new_idx]
            if pd.notna(ts):
                ts_str = str(ts)
        self.calculate_panel.update_pullout_info(new_idx, ts_str)
        self.calculate_panel.log_widget.log(
            f"Pullout line moved to index {new_idx}"
        )

    def _reset_lines(self):
        """Reset end-of-penetration and pullout lines to auto-calculated positions."""
        self._end_pen_idx = None
        self._pullout_idx = None
        self.calculate_panel.end_pen_label.setText("Not set")
        self.calculate_panel.pullout_label.setText("Not set")
        self._plot_calculate_mode()
        self.calculate_panel.log_widget.log(
            "End-of-penetration and pullout lines reset to auto"
        )

    # ==================================================================
    # Calculate Mode
    # ==================================================================

    def run_calculations(self):
        """Run coring analysis calculations and display results in the log."""
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return

        panel = self.calculate_panel
        ws_col = panel.get_weight_stand_col()
        rel_col = panel.get_release_col()
        trig_col = panel.get_trigger_col()  # May be None

        if ws_col is None or rel_col is None:
            self._show_warning(
                "Select both Weight Stand and Release Device sensors"
            )
            return

        try:
            # Retrieve depth arrays (interpolated)
            ws_vals = (
                self.sensor_data.df[ws_col]
                .interpolate().ffill().bfill().values
            )
            rel_vals = (
                self.sensor_data.df[rel_col]
                .interpolate().ffill().bfill().values
            )

            trig_vals = None
            if (trig_col is not None
                    and trig_col in self.sensor_data.df.columns):
                trig_vals = (
                    self.sensor_data.df[trig_col]
                    .interpolate().ffill().bfill().values
                )

            # Optional Savitzky-Golay smoothing
            if panel.get_smoothing_enabled():
                sg_win, sg_poly = panel.get_sg_params()
                panel.log_widget.log(
                    f"Applying Savitzky-Golay smoothing "
                    f"(window={sg_win}, poly={sg_poly})"
                )
                ws_vals = apply_savgol(ws_vals, sg_win, sg_poly)
                rel_vals = apply_savgol(rel_vals, sg_win, sg_poly)
                if trig_vals is not None:
                    trig_vals = apply_savgol(trig_vals, sg_win, sg_poly)

            timestamps_epoch = self.sensor_data.get_timestamps_epoch()

            # Resolve trip index from the calculate panel
            trip_idx = self._resolve_calc_trip_index()

            # Resolve start_core index
            start_core_idx = self._calc_start_core_idx

            # Piston values (from a previous Piston Position calculation)
            piston = self._piston_values

            # If smoothing is enabled and piston exists, we should
            # also smooth piston for consistency
            if piston is not None and panel.get_smoothing_enabled():
                sg_win, sg_poly = panel.get_sg_params()
                piston = apply_savgol(piston, sg_win, sg_poly)

            # Metadata from CSV header
            md = self.sensor_data.metadata
            trigger_core_length_ft = md.get('trigger_core_length')
            core_length_ft = md.get('core_length')
            trigger_pen = panel.get_trigger_pen()

            panel.log_widget.log("")

            # Log what data is available
            ws_short = SensorData.get_short_name(ws_col)
            rel_short = SensorData.get_short_name(rel_col)
            panel.log_widget.log(f"Weight Stand: {ws_short}")
            panel.log_widget.log(f"Release Device: {rel_short}")
            if trig_vals is not None:
                panel.log_widget.log(
                    f"Trigger Core/Weight: "
                    f"{SensorData.get_short_name(trig_col)}"
                )
            else:
                panel.log_widget.log(
                    "Trigger Core/Weight: not available"
                )

            if trip_idx is not None:
                panel.log_widget.log(f"Trip index: {trip_idx}")
            else:
                panel.log_widget.log("Trip time: not set")

            if start_core_idx is not None:
                panel.log_widget.log(
                    f"Start core index: {start_core_idx}"
                )
            else:
                panel.log_widget.log("Start core: not available")

            if piston is not None:
                panel.log_widget.log("Piston position: available")
            else:
                panel.log_widget.log("Piston position: not computed")

            if trigger_core_length_ft is not None:
                panel.log_widget.log(
                    f"Trigger core length: {trigger_core_length_ft} ft"
                )
            if core_length_ft is not None:
                panel.log_widget.log(
                    f"Core length: {core_length_ft} ft"
                )
            if trigger_pen > 0:
                panel.log_widget.log(
                    f"Trigger penetration: {trigger_pen} m"
                )

            end_pen_idx = self._end_pen_idx
            if end_pen_idx is not None:
                panel.log_widget.log(
                    f"End of initial penetration index: {end_pen_idx}"
                )
            else:
                panel.log_widget.log(
                    "End of initial penetration: not set (using trip+5s)"
                )

            pullout_idx = self._pullout_idx
            if pullout_idx is not None:
                panel.log_widget.log(
                    f"Pullout index: {pullout_idx}"
                )
            else:
                panel.log_widget.log(
                    "Pullout: not set (using ws_max)"
                )

            # Run calculations
            results = compute_calculations(
                weight_stand=ws_vals,
                release=rel_vals,
                timestamps_epoch=timestamps_epoch,
                trip_idx=trip_idx,
                start_core_idx=start_core_idx,
                piston=piston,
                trigger_core=trig_vals,
                trigger_core_length_ft=trigger_core_length_ft,
                trigger_pen=trigger_pen,
                core_length_ft=core_length_ft,
                end_pen_idx=end_pen_idx,
                pullout_idx=pullout_idx,
            )

            # Store results & inputs for export
            self._last_calc_results = results
            self._last_calc_inputs = {
                'weight_stand_col': ws_col,
                'release_col': rel_col,
                'trigger_col': trig_col,
                'smoothing_enabled': panel.get_smoothing_enabled(),
                'sg_window': panel.get_sg_params()[0] if panel.get_smoothing_enabled() else None,
                'sg_poly': panel.get_sg_params()[1] if panel.get_smoothing_enabled() else None,
                'trip_idx': trip_idx,
                'start_core_idx': start_core_idx,
                'piston_available': piston is not None,
                'trigger_core_length_ft': trigger_core_length_ft,
                'core_length_ft': core_length_ft,
                'trigger_pen': trigger_pen,
            }

            panel.log_widget.log(format_results(results))

            # Show smoothed traces on the plot if smoothing is enabled
            if panel.get_smoothing_enabled():
                smoothed_data = {}
                smoothed_data[ws_col] = ws_vals
                smoothed_data[rel_col] = rel_vals
                if trig_vals is not None and trig_col is not None:
                    smoothed_data[trig_col] = trig_vals
                self.main_plot.add_smoothed_traces(
                    smoothed_data,
                    self.sensor_data.depth_columns,
                )
            else:
                self.main_plot.remove_smoothed_traces()

            # Update piston trace on the plot with the (possibly smoothed) values
            if piston is not None:
                self.main_plot.update_piston_trace(piston)

            # Update the geometry diagram in the secondary view
            self._update_calculation_plot(
                results, ws_vals, piston, trip_idx,
                start_core_idx, core_length_ft,
                end_pen_idx, pullout_idx,
            )

            # Refresh start_pen line on upper plot with current seafloor
            self._update_start_pen_line(trip_idx)

        except Exception as e:
            self._show_error("Calculation Error", str(e))
            panel.log_widget.log(f"ERROR: {e}")

    def _update_calculation_plot(
        self,
        results,
        ws_vals: np.ndarray,
        piston: Optional[np.ndarray],
        trip_idx: Optional[int],
        start_core_idx: Optional[int],
        core_length_ft: Optional[float],
        end_pen_idx: Optional[int] = None,
        pullout_idx: Optional[int] = None,
    ):
        """Build a GeometryInput and update the secondary diagram."""
        if self.calculation_plot is None:
            return
        if trip_idx is None or results.seafloor is None:
            self.calculation_plot.clear()
            return
        if core_length_ft is None or core_length_ft <= 0:
            self.calculation_plot.clear()
            return

        FT_TO_M = 1.0 / 3.28
        core_length_m = core_length_ft * FT_TO_M
        n = len(ws_vals)
        freefall_est = results.freefall_est if results.freefall_est is not None else 0.0

        # -- Start Core values --
        ws_at_sc = None
        piston_at_sc = None
        piston_alt_sc = None
        if start_core_idx is not None and 0 <= start_core_idx < n:
            ws_at_sc = float(ws_vals[start_core_idx])
            if piston is not None and start_core_idx < len(piston):
                piston_at_sc = float(piston[start_core_idx])
                piston_alt_sc = results.piston_alt  # seafloor - piston[start_core]

        # -- Start Penetration values --
        # start_pen = first index >= start_core where core_tip >= seafloor
        ws_at_sp = None
        piston_at_sp = None
        piston_alt_sp = None
        core_tip_series = ws_vals + WEIGHT_LENGTH + core_length_m
        search_from = start_core_idx if (start_core_idx is not None
                                         and 0 <= start_core_idx < n) else trip_idx
        after_search = core_tip_series[search_from:]
        pen_candidates = np.where(after_search >= results.seafloor)[0]
        if len(pen_candidates) > 0:
            sp_idx = search_from + int(pen_candidates[0])
            if 0 <= sp_idx < n:
                ws_at_sp = float(ws_vals[sp_idx])
                if piston is not None and sp_idx < len(piston):
                    piston_at_sp = float(piston[sp_idx])
                    piston_alt_sp = results.seafloor - piston_at_sp

        # -- End-of-penetration values --
        ws_at_ep = None
        if end_pen_idx is not None and 0 <= end_pen_idx < n:
            ws_at_ep = float(ws_vals[end_pen_idx])

        # -- Pullout values --
        ws_at_po = None
        piston_at_po = None
        if pullout_idx is not None and 0 <= pullout_idx < n:
            ws_at_po = float(ws_vals[pullout_idx])
            if piston is not None and pullout_idx < len(piston):
                piston_at_po = float(piston[pullout_idx])

        geo = GeometryInput(
            ws_at_trip=float(ws_vals[trip_idx]),
            seafloor=results.seafloor,
            core_length_m=core_length_m,
            freefall_est=freefall_est,
            ws_at_start_core=ws_at_sc,
            piston_at_start_core=piston_at_sc,
            piston_alt_at_start_core=piston_alt_sc,
            ws_at_start_pen=ws_at_sp,
            piston_at_start_pen=piston_at_sp,
            piston_alt_at_start_pen=piston_alt_sp,
            ws_at_end_pen=ws_at_ep,
            ws_at_pullout=ws_at_po,
            piston_at_pullout=piston_at_po,
        )
        self.calculation_plot.plot_geometry(geo)

    def _resolve_calc_trip_index(self) -> Optional[int]:
        """Determine the trip index for the calculate panel.

        Priority:
        1. Trip time entered / selected on the calculate panel (epoch).
        2. Trip detection result stored from the trip-detector mode.
        3. None (calculations that need trip_idx will be skipped).
        """
        if self.sensor_data is None:
            return None

        panel = self.calculate_panel
        trip_epoch = panel.get_trip_time_epoch()

        if trip_epoch > 946684800:
            x = self.sensor_data.get_timestamps_epoch()
            if len(x) > 0:
                idx = int(np.searchsorted(x, trip_epoch))
                return min(idx, len(x) - 1)

        if (hasattr(self, 'trip_detection_result')
                and self.trip_detection_result is not None):
            return self.trip_detection_result.trip_index

        return None

    def _sync_trip_to_calculate_panel(self):
        """Push the best-known trip time into the calculate panel.

        Sources (in priority order):
        1. Trip detection result (most accurate).
        2. Piston panel trip time (user may have edited it).
        3. CSV header metadata (already set during file load).
        """
        if self.trip_detection_result is not None:
            dt = self.trip_detection_result.trip_datetime
            if dt is not None:
                self.calculate_panel.set_trip_time(
                    str(dt), source='trip detector'
                )
                return
        # Fall back to piston panel value
        if self.piston_panel is not None:
            epoch = self.piston_panel.get_trip_time_epoch()
            if epoch > 946684800:
                qdt = self.piston_panel.trip_time_edit.dateTime()
                dt_str = qdt.toString('yyyy-MM-dd HH:mm:ss.zzz')
                self.calculate_panel.set_trip_time(
                    dt_str, source='piston panel'
                )

    def _plot_calculate_mode(self):
        """Plot depth traces with trip and start_core lines for calculate mode."""
        if self.sensor_data is None:
            return

        self.plot_depths()

        # Re-add trip line if available
        trip_idx = self._resolve_calc_trip_index()
        if trip_idx is not None:
            self.main_plot.add_trip_line(trip_idx)

        # Re-add start_core line if available
        if self._calc_start_core_idx is not None:
            x = self.sensor_data.get_timestamps_epoch()
            idx = self._calc_start_core_idx
            if 0 <= idx < len(x):
                self.main_plot.add_start_core_line(float(x[idx]))

        # Add start_pen line (non-draggable, auto-computed)
        self._update_start_pen_line(trip_idx)

        # Add end-of-penetration line
        x = self.sensor_data.get_timestamps_epoch()
        if self._end_pen_idx is not None and 0 <= self._end_pen_idx < len(x):
            self.main_plot.add_end_pen_line(float(x[self._end_pen_idx]))
        elif trip_idx is not None:
            # Auto-initialize to trip + 5s
            target = x[trip_idx] + 5.0
            ep_idx = int(np.argmin(np.abs(x - target)))
            self._end_pen_idx = ep_idx
            self.main_plot.add_end_pen_line(float(x[ep_idx]))
            # Update panel label
            dt_col = self.sensor_data.datetime_col
            ts_str = ''
            if (dt_col in self.sensor_data.df.columns
                    and 0 <= ep_idx < len(self.sensor_data.df)):
                ts = self.sensor_data.df[dt_col].iloc[ep_idx]
                if pd.notna(ts):
                    ts_str = str(ts)
            self.calculate_panel.update_end_pen_info(ep_idx, ts_str)

        # Add pullout line
        if self._pullout_idx is not None and 0 <= self._pullout_idx < len(x):
            self.main_plot.add_pullout_line(float(x[self._pullout_idx]))
        elif self._end_pen_idx is not None:
            # Auto-initialize to ws_max after end_pen
            ep = self._end_pen_idx
            panel = self.calculate_panel
            ws_col = panel.get_weight_stand_col()
            if ws_col is not None and ws_col in self.sensor_data.df.columns:
                ws_vals = (
                    self.sensor_data.df[ws_col]
                    .interpolate().ffill().bfill().values
                )
                # Look for max WS in a 10-min window after end_pen
                window_10min = int(np.argmin(np.abs(x - (x[ep] + 600.0))))
                window_10min = min(window_10min, len(ws_vals) - 1)
                search_slice = ws_vals[ep:window_10min + 1]
                if len(search_slice) > 0:
                    po_idx = ep + int(np.nanargmax(search_slice))
                else:
                    po_idx = ep
                self._pullout_idx = po_idx
                self.main_plot.add_pullout_line(float(x[po_idx]))
                dt_col = self.sensor_data.datetime_col
                ts_str = ''
                if (dt_col in self.sensor_data.df.columns
                        and 0 <= po_idx < len(self.sensor_data.df)):
                    ts = self.sensor_data.df[dt_col].iloc[po_idx]
                    if pd.notna(ts):
                        ts_str = str(ts)
                self.calculate_panel.update_pullout_info(po_idx, ts_str)

        # Also show piston trace if available
        if self._piston_values is not None:
            x = self.sensor_data.get_timestamps_epoch()
            self.main_plot.add_piston_trace(x, self._piston_values)

    def _update_start_pen_line(self, trip_idx: Optional[int] = None):
        """Recompute and display the start-penetration and seafloor lines."""
        self.main_plot.remove_start_pen_line()
        self.main_plot.remove_seafloor_line()
        if self.sensor_data is None or trip_idx is None:
            return
        x = self.sensor_data.get_timestamps_epoch()
        md = self.sensor_data.metadata
        core_length_ft = md.get('core_length')
        if not core_length_ft or core_length_ft <= 0:
            return
        FT_TO_M_local = 1.0 / 3.28
        core_length_m = core_length_ft * FT_TO_M_local
        panel = self.calculate_panel
        ws_col = panel.get_weight_stand_col()
        trig_col = panel.get_trigger_col()
        if not ws_col or ws_col not in self.sensor_data.df.columns:
            return
        ws_vals = (
            self.sensor_data.df[ws_col]
            .interpolate().ffill().bfill().values
        )
        sf = None
        if trig_col and trig_col in self.sensor_data.df.columns:
            trig_vals = (
                self.sensor_data.df[trig_col]
                .interpolate().ffill().bfill().values
            )
            tc_len_ft = md.get('trigger_core_length')
            trigger_pen = panel.get_trigger_pen()
            if tc_len_ft and tc_len_ft > 0:
                sf = (float(trig_vals[trip_idx])
                      + tc_len_ft * FT_TO_M_local
                      - trigger_pen)
        if sf is None:
            return
        # Add seafloor line
        self.main_plot.add_seafloor_line(sf)
        # Add start_pen line
        core_tip = ws_vals + WEIGHT_LENGTH + core_length_m
        search_from = (self._calc_start_core_idx
                       if self._calc_start_core_idx is not None
                       else trip_idx)
        after = core_tip[search_from:]
        candidates = np.where(after >= sf)[0]
        if len(candidates) > 0:
            sp_idx = search_from + int(candidates[0])
            if 0 <= sp_idx < len(x):
                self.main_plot.add_start_pen_line(float(x[sp_idx]))

    def export_calculation_results(self):
        """Export the last calculation results, inputs, and corrections to a text file."""
        if self._last_calc_results is None or self._last_calc_inputs is None:
            self._show_warning(
                "No calculation results to export.\n"
                "Click 'Calculate' first."
            )
            return

        core_name = (
            self.sensor_data.core_title.replace(' ', '_')
            if self.sensor_data and self.sensor_data.core_title
            else 'data'
        )
        timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
        default_name = f"{core_name}_calculations_{timestamp}.txt"

        file_path, _ = QFileDialog.getSaveFileName(
            self.main_window, "Export Calculation Results", default_name,
            "Text Files (*.txt);;All Files (*)"
        )
        if not file_path:
            return

        try:
            self._write_calculation_export(file_path)
            self._log_active(f"Results exported to {Path(file_path).name}")
            QMessageBox.information(
                self.main_window, "Success",
                "Calculation results exported successfully!"
            )
        except Exception as e:
            self._show_error("Export Error", str(e))

    def export_calculation_diagram(self):
        """Export the geometry diagram to an image file."""
        if self.calculation_plot is None:
            self._show_warning("No diagram to export.")
            return

        import pyqtgraph.exporters as exporters

        core_name = (
            self.sensor_data.core_title.replace(' ', '_')
            if self.sensor_data and self.sensor_data.core_title
            else 'diagram'
        )
        timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
        default_name = f"{core_name}_geometry_{timestamp}.png"

        file_path, selected_filter = QFileDialog.getSaveFileName(
            self.main_window, "Export Geometry Diagram", default_name,
            "PNG Image (*.png);;SVG Image (*.svg);;All Files (*)"
        )
        if not file_path:
            return

        try:
            plot_item = self.calculation_plot.plot_widget.plotItem
            if file_path.lower().endswith('.svg'):
                exporter = exporters.SVGExporter(plot_item)
            else:
                exporter = exporters.ImageExporter(plot_item)
                exporter.parameters()['width'] = 1600
            exporter.export(file_path)
            self._log_active(f"Diagram exported to {Path(file_path).name}")
            QMessageBox.information(
                self.main_window, "Success",
                "Geometry diagram exported successfully!"
            )
        except Exception as e:
            self._show_error("Export Error", str(e))

    def _write_calculation_export(self, file_path: str):
        """Write calculation results with full context to a text file."""
        from datetime import datetime
        from ..domain.processing.calculations import FT_TO_M

        res = self._last_calc_results
        inp = self._last_calc_inputs
        sd = self.sensor_data
        panel = self.calculate_panel

        lines = []
        lines.append("=" * 60)
        lines.append("CORING ANALYSIS CALCULATION REPORT")
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 60)

        # Source data
        lines.append("")
        lines.append("--- Source Data ---")
        if sd is not None:
            lines.append(f"  File:        {sd.source_file}")
            lines.append(f"  Core:        {sd.core_title}")
            lines.append(f"  Rows:        {sd.row_count:,}")
            lines.append(f"  Sensors:     {sd.num_sensors}")
            tr = sd.time_range
            if tr:
                lines.append(f"  Time range:  {tr[0]} to {tr[1]}")

        # Corrections applied
        lines.append("")
        lines.append("--- Corrections Applied ---")
        if sd is not None and sd.corrections:
            time_corrections = [
                c for c in sd.corrections
                if c.correction_type == 'time_shift'
            ]
            depth_corrections = [
                c for c in sd.corrections
                if c.correction_type in ('depth_calibration', 'depth_manual')
            ]
            if time_corrections:
                lines.append("  Time corrections:")
                for corr in time_corrections:
                    shift = corr.parameters.get('shift_seconds', 0)
                    sign = '+' if shift >= 0 else ''
                    short = SensorData.get_short_name(corr.sensor_column)
                    lines.append(f"    {short}: {sign}{shift:.4f}s")
            if depth_corrections:
                lines.append("  Depth corrections:")
                for corr in depth_corrections:
                    offset = corr.parameters.get('offset', 0)
                    sign = '+' if offset >= 0 else ''
                    short = SensorData.get_short_name(corr.sensor_column)
                    lines.append(f"    {short}: {sign}{offset:.4f}m")
        else:
            lines.append("  None")

        # Inputs / configuration
        lines.append("")
        lines.append("--- Calculation Inputs ---")
        ws_col = inp['weight_stand_col']
        rel_col = inp['release_col']
        trig_col = inp['trigger_col']
        lines.append(
            f"  Weight Stand:         "
            f"{SensorData.get_short_name(ws_col)}"
        )
        lines.append(
            f"  Release Device:       "
            f"{SensorData.get_short_name(rel_col)}"
        )
        if trig_col:
            lines.append(
                f"  Trigger Core/Weight:  "
                f"{SensorData.get_short_name(trig_col)}"
            )
        else:
            lines.append("  Trigger Core/Weight:  not available")

        if inp['smoothing_enabled']:
            lines.append(
                f"  Savitzky-Golay:       enabled "
                f"(window={inp['sg_window']}, poly={inp['sg_poly']})"
            )
        else:
            lines.append("  Savitzky-Golay:       disabled")

        if inp['trip_idx'] is not None:
            lines.append(f"  Trip index:           {inp['trip_idx']}")
            # Also show the trip datetime
            if sd is not None:
                dt_col = sd.datetime_col
                if (dt_col in sd.df.columns
                        and 0 <= inp['trip_idx'] < len(sd.df)):
                    ts = sd.df[dt_col].iloc[inp['trip_idx']]
                    if pd.notna(ts):
                        lines.append(f"  Trip time:            {ts}")
        else:
            lines.append("  Trip index:           not set")

        if inp['start_core_idx'] is not None:
            lines.append(
                f"  Start core index:     {inp['start_core_idx']}"
            )
            if sd is not None:
                dt_col = sd.datetime_col
                if (dt_col in sd.df.columns
                        and 0 <= inp['start_core_idx'] < len(sd.df)):
                    ts = sd.df[dt_col].iloc[inp['start_core_idx']]
                    if pd.notna(ts):
                        lines.append(
                            f"  Start core time:      {ts}"
                        )
        else:
            lines.append("  Start core index:     not available")

        lines.append(
            f"  Piston position:      "
            f"{'available' if inp['piston_available'] else 'not computed'}"
        )

        tc_len = inp['trigger_core_length_ft']
        if tc_len is not None:
            lines.append(
                f"  Trigger core length:  {tc_len} ft "
                f"({tc_len * FT_TO_M:.3f} m)"
            )
        else:
            lines.append("  Trigger core length:  not available")

        cl = inp['core_length_ft']
        if cl is not None:
            lines.append(
                f"  Core length:          {cl} ft "
                f"({cl * FT_TO_M:.3f} m)"
            )
        else:
            lines.append("  Core length:          not available")

        lines.append(
            f"  Trigger penetration:  {inp['trigger_pen']:.2f} m"
        )

        # Results
        lines.append("")
        lines.append("--- Calculated Values ---")

        def _fmt(label: str, val, unit: str = "m") -> str:
            if val is None:
                return f"  {label:<30s}  N/A"
            return f"  {label:<30s}  {val:>10.4f} {unit}"

        lines.append(_fmt("Recoil Max:", res.recoil_max))
        lines.append(_fmt("Fall Distance:", res.fall_dist))
        lines.append(_fmt("Suck-in:", res.suck_in))
        lines.append(_fmt("Recoil at Start Core:", res.recoil_start))
        lines.append(_fmt("Freefall at Start Core:", res.freefall_start))
        lines.append(_fmt("Piston Suck:", res.piston_suck))

        if res.seafloor is not None:
            lines.append(
                f"  {'Seafloor Depth:':<30s}  {res.seafloor:>10.4f} m"
            )
        else:
            lines.append(f"  {'Seafloor Depth:':<30s}  N/A")

        lines.append(_fmt("Piston Altitude:", res.piston_alt))
        lines.append(_fmt("Penetration Deficit:", res.pen_deficit))
        lines.append(_fmt("Freefall Estimate:", res.freefall_est))

        if res.notes:
            lines.append("")
            lines.append("--- Notes ---")
            for note in res.notes:
                lines.append(f"  {note}")

        lines.append("")
        lines.append("=" * 60)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

    # ==================================================================
    # Common Operations
    # ==================================================================

    def reset_to_original(self):
        """Reset data to the original loaded state."""
        if self.original_data is None:
            self._show_warning("No original data to reset to")
            return

        self.sensor_data = self.original_data.copy()
        self.main_plot.set_sensor_data(self.sensor_data)
        self.plot_depths()
        self.time_offset_results = None
        self._log_active("Data reset to original")

    def export_corrected_csv(self):
        """Export the current sensor data to CSV."""
        if self.sensor_data is None:
            self._show_warning("No data to export")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self.main_window, "Export Data", "",
            "CSV Files (*.csv);;All Files (*)"
        )
        if not file_path:
            return

        try:
            self.sensor_data.df.to_csv(file_path, index=False)
            self._log_active(f"Exported to {Path(file_path).name}")
            QMessageBox.information(
                self.main_window, "Success", "Data exported successfully!"
            )
        except Exception as e:
            self._show_error("Export Error", str(e))

    def export_trip_csv(self):
        """Export the current sensor data with trip detection metadata."""
        if self.sensor_data is None:
            self._show_warning("No data to export")
            return

        if self.trip_detection_result is None:
            self._show_warning("No trip detection has been performed yet")
            return

        # Generate default filename
        core_name = (
            self.sensor_data.core_title.replace(' ', '_')
            if self.sensor_data.core_title else 'data'
        )
        timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
        default_name = f"{core_name}_corrected_{timestamp}.csv"

        file_path, _ = QFileDialog.getSaveFileName(
            self.main_window, "Export Trip Data", default_name,
            "CSV Files (*.csv);;All Files (*)"
        )
        if not file_path:
            return

        try:
            self._write_trip_csv(file_path)
            self._log_active(f"Exported to {Path(file_path).name}")
            QMessageBox.information(
                self.main_window, "Success",
                f"Data exported with trip metadata!\n\n"
                f"Trip detected at: {self.trip_detection_result.trip_datetime}"
            )
        except Exception as e:
            self._show_error("Export Error", str(e))

    def _write_trip_csv(self, file_path: str):
        """Write CSV with full metadata header including trip and corrections."""
        from datetime import datetime

        header_lines = []

        # Try to read original header from source file
        if self._loaded_file_path and Path(self._loaded_file_path).exists():
            try:
                with open(self._loaded_file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith('#') and not line.strip() == '#':
                            header_lines.append(line.rstrip())
                        elif line.strip().startswith('datetime'):
                            break
            except Exception:
                pass

        # If we couldn't read the original, create basic header
        if not header_lines:
            header_lines = [
                "# Export from Sediment App - Sensor Alignment Tool",
                f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ]
            if self.sensor_data.core_title:
                header_lines.append(f"# Core: {self.sensor_data.core_title}")
            header_lines.append(
                f"# Data shape: {self.sensor_data.row_count:,} rows "
                f"\u00d7 {len(self.sensor_data.df.columns)} columns"
            )
            time_range = self.sensor_data.time_range
            if time_range:
                header_lines.append(
                    f"# Time range: {time_range[0]} to {time_range[1]}"
                )

        # Add trip detection info
        trip = self.trip_detection_result
        header_lines.append("#")
        header_lines.append(
            f"# Trip detected at: {trip.trip_datetime} "
            f"(index: {trip.trip_index})"
        )

        # Add correction information
        if self.sensor_data.corrections:
            header_lines.append("#")
            time_corrections = [
                c for c in self.sensor_data.corrections
                if c.correction_type == 'time_shift'
            ]
            depth_corrections = [
                c for c in self.sensor_data.corrections
                if c.correction_type in ('depth_calibration', 'depth_manual')
            ]

            if time_corrections:
                header_lines.append("# Time corrections applied:")
                for corr in time_corrections:
                    shift = corr.parameters.get('shift_seconds', 0)
                    sign = '+' if shift >= 0 else ''
                    short = SensorData.get_short_name(corr.sensor_column)
                    header_lines.append(
                        f"#   {short}: {sign}{shift:.2f}s"
                    )

            if depth_corrections:
                header_lines.append("# Depth corrections applied:")
                for corr in depth_corrections:
                    offset = corr.parameters.get('offset', 0)
                    sign = '+' if offset >= 0 else ''
                    short = SensorData.get_short_name(corr.sensor_column)
                    header_lines.append(
                        f"#   {short}: {sign}{offset:.3f}m"
                    )
        else:
            header_lines.append("#")
            header_lines.append("# No corrections applied")

        header_lines.append("#")

        # Write file
        with open(file_path, 'w', encoding='utf-8', newline='') as f:
            for line in header_lines:
                f.write(line + '\n')
            self.sensor_data.df.to_csv(f, index=False)

    def export_piston_csv(self):
        """Export sensor data with a piston_position column and piston metadata."""
        if self.sensor_data is None:
            self._show_warning("No data to export")
            return

        if self._piston_values is None:
            self._show_warning(
                "No piston position calculated yet.\n"
                "Click 'Calculate & Plot Piston' first."
            )
            return

        core_name = (
            self.sensor_data.core_title.replace(' ', '_')
            if self.sensor_data.core_title else 'data'
        )
        timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
        default_name = f"{core_name}_piston_{timestamp}.csv"

        file_path, _ = QFileDialog.getSaveFileName(
            self.main_window, "Export Piston Data", default_name,
            "CSV Files (*.csv);;All Files (*)"
        )
        if not file_path:
            return

        try:
            self._write_piston_csv(file_path)
            self._log_active(f"Exported to {Path(file_path).name}")
            QMessageBox.information(
                self.main_window, "Success",
                "Piston data exported successfully!"
            )
        except Exception as e:
            self._show_error("Export Error", str(e))

    def _write_piston_csv(self, file_path: str):
        """Write CSV with piston_position column and full metadata header."""
        from datetime import datetime

        header_lines = []

        # Try to read original header from source file
        if self._loaded_file_path and Path(self._loaded_file_path).exists():
            try:
                with open(self._loaded_file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith('#') and not line.strip() == '#':
                            header_lines.append(line.rstrip())
                        elif line.strip().startswith('datetime'):
                            break
            except Exception:
                pass

        if not header_lines:
            header_lines = [
                "# Export from Sediment App - Sensor Alignment Tool",
                f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ]
            if self.sensor_data.core_title:
                header_lines.append(f"# Core: {self.sensor_data.core_title}")
            header_lines.append(
                f"# Data shape: {self.sensor_data.row_count:,} rows "
                f"\u00d7 {len(self.sensor_data.df.columns)} columns"
            )
            time_range = self.sensor_data.time_range
            if time_range:
                header_lines.append(
                    f"# Time range: {time_range[0]} to {time_range[1]}"
                )

        # Trip time metadata
        panel = self.piston_panel
        header_lines.append("#")
        qdt = panel.trip_time_edit.dateTime()
        d, t = qdt.date(), qdt.time()
        trip_str = (
            f"{d.year()}-{d.month():02d}-{d.day():02d} "
            f"{t.hour():02d}:{t.minute():02d}:{t.second():02d}"
            f".{t.msec():03d}"
        )
        header_lines.append(f"# trip_time: {trip_str}")

        # Start core metadata
        start_idx = self._piston_start_core_idx
        if start_idx is not None:
            header_lines.append(f"# start_core_index: {start_idx}")
            dt_col = self.sensor_data.datetime_col
            if (dt_col in self.sensor_data.df.columns
                    and 0 <= start_idx < len(self.sensor_data.df)):
                ts = self.sensor_data.df[dt_col].iloc[start_idx]
                if pd.notna(ts):
                    header_lines.append(f"# start_core_time: {ts}")

        # Offsets from corrections
        if self.sensor_data.corrections:
            time_corrections = [
                c for c in self.sensor_data.corrections
                if c.correction_type == 'time_shift'
            ]
            depth_corrections = [
                c for c in self.sensor_data.corrections
                if c.correction_type in ('depth_calibration', 'depth_manual')
            ]

            if time_corrections:
                header_lines.append("#")
                header_lines.append("# Time corrections applied:")
                for corr in time_corrections:
                    shift = corr.parameters.get('shift_seconds', 0)
                    sign = '+' if shift >= 0 else ''
                    short = SensorData.get_short_name(corr.sensor_column)
                    header_lines.append(f"#   {short}: {sign}{shift:.4f}s")

            if depth_corrections:
                header_lines.append("#")
                header_lines.append("# Depth corrections applied:")
                for corr in depth_corrections:
                    offset = corr.parameters.get('offset', 0)
                    sign = '+' if offset >= 0 else ''
                    short = SensorData.get_short_name(corr.sensor_column)
                    header_lines.append(f"#   {short}: {sign}{offset:.4f}m")
        else:
            header_lines.append("#")
            header_lines.append("# No depth/time corrections applied")

        header_lines.append("#")

        # Build dataframe with piston_position column added
        df_out = self.sensor_data.df.copy()
        piston_col = np.full(len(df_out), np.nan)
        n = min(len(self._piston_values), len(df_out))
        piston_col[:n] = self._piston_values[:n]
        df_out.insert(len(df_out.columns), 'piston_position', piston_col)

        # Write file
        with open(file_path, 'w', encoding='utf-8', newline='') as f:
            for line in header_lines:
                f.write(line + '\n')
            df_out.to_csv(f, index=False)

    # ==================================================================
    # Selection handling
    # ==================================================================

    def _set_selection_mode(self, enabled: bool):
        self.main_plot.selection_mode = enabled

    def _clear_selection(self):
        self.main_plot.clear_selection()
        mode = (
            self.main_window.get_current_mode() if self.main_window else None
        )
        if mode == 'Time Offset':
            self.time_panel.selection_controls.clear_info()
        elif mode == 'Create Calibration':
            self.calibration_panel.selection_controls.clear_info()

    def _on_selection_changed(self, start_idx: int, end_idx: int):
        """Called when user completes a selection on the main plot."""
        mode = (
            self.main_window.get_current_mode() if self.main_window else None
        )

        n = end_idx - start_idx + 1
        extra = ''
        if self.sensor_data is not None:
            dt_col = self.sensor_data.datetime_col
            if dt_col in self.sensor_data.df.columns:
                t_start = self.sensor_data.df[dt_col].iloc[start_idx]
                t_end = self.sensor_data.df[dt_col].iloc[end_idx]
                extra = f"{t_start} to {t_end}"

        if mode == 'Time Offset':
            self.time_panel.selection_controls.update_selection_info(
                start_idx, end_idx, extra,
            )
        elif mode == 'Create Calibration':
            self.calibration_panel.selection_controls.update_selection_info(
                start_idx, end_idx, extra,
            )

    def _on_selection_cleared(self):
        pass  # Already handled by _clear_selection

    # ==================================================================
    # Mode switching
    # ==================================================================

    def on_mode_changed(self, mode_name: str):
        """Called by MainWindow when mode changes."""
        if self.main_window is None:
            return

        # Disable selection mode when leaving a selection-enabled mode
        self.main_plot.selection_mode = False
        # Reset toggle buttons on panels that have selection controls
        if self.time_panel is not None:
            self.time_panel.selection_controls.toggle_btn.setChecked(False)
            self.time_panel.selection_controls._on_toggled()
        if self.calibration_panel is not None:
            self.calibration_panel.selection_controls.toggle_btn.setChecked(False)
            self.calibration_panel.selection_controls._on_toggled()

        # Clear selection region when entering non-selection modes
        if mode_name not in ('Time Offset', 'Create Calibration'):
            self.main_plot.clear_selection()

        # Show/hide secondary view
        if mode_name == 'Time Offset':
            self.main_window.show_secondary_view('heave')
        elif mode_name == 'Create Calibration':
            self.main_window.show_secondary_view('statistics')
        elif mode_name == 'Trip Detector':
            self.main_window.show_secondary_view('trip')
        elif mode_name == 'Calculate':
            self.main_window.show_secondary_view('calculation')
        else:
            self.main_window.hide_secondary_view()

        # Clean up piston overlays when leaving Piston Position mode
        if mode_name not in ('Piston Position', 'Calculate'):
            self.main_plot.remove_piston_trace()
            self.main_plot.remove_start_core_line()
            self.main_plot.remove_end_pen_line()
            self.main_plot.remove_pullout_line()

        # When entering Calculate mode, restore trip / start_core / piston lines
        if mode_name == 'Calculate':
            self.main_plot.remove_piston_trace()
            self.main_plot.remove_start_core_line()
            self.main_plot.remove_smoothed_traces()
            if self.sensor_data is not None:
                # Sync start_core from piston mode BEFORE plotting
                # (always refresh – piston mode may have updated it)
                if self._piston_start_core_idx is not None:
                    self._calc_start_core_idx = self._piston_start_core_idx
                    dt_col = self.sensor_data.datetime_col
                    ts_str = ''
                    idx = self._calc_start_core_idx
                    if (dt_col in self.sensor_data.df.columns
                            and 0 <= idx < len(self.sensor_data.df)):
                        ts = self.sensor_data.df[dt_col].iloc[idx]
                        if pd.notna(ts):
                            ts_str = str(ts)
                    self.calculate_panel.update_start_core_info(idx, ts_str)

                # Sync trip time from trip detector / piston panel
                self._sync_trip_to_calculate_panel()

                self._plot_calculate_mode()
                return  # _plot_calculate_mode already sets sensor data

        # Re-plot current data if available
        if self.sensor_data is not None:
            self.main_plot.set_sensor_data(self.sensor_data)

    # ==================================================================
    # Helpers
    # ==================================================================

    def _update_all_panels_file_info(self):
        """Update file info on all panels after data load."""
        if self.sensor_data is None:
            return

        sd = self.sensor_data
        tr = sd.time_range
        dr = sd.depth_range
        time_str = f"{tr[0]} to {tr[1]}" if tr else ''
        depth_str = f"{dr[0]:.1f}m to {dr[1]:.1f}m" if dr else ''

        self.view_panel.update_file_info(
            sd.source_file, sd.num_sensors, sd.row_count,
            time_str, depth_str, sd.core_title,
        )
        self.depth_panel.update_file_info(
            sd.source_file, sd.num_sensors, sd.row_count, sd.core_title,
        )
        self.time_panel.update_file_info(
            sd.source_file, sd.num_sensors, sd.row_count,
        )
        if self.trip_panel is not None:
            self.trip_panel.update_file_info(
                sd.source_file, sd.num_sensors, sd.row_count,
            )

        # Set up manual offsets on the depth panel
        self.depth_panel.setup_manual_offsets(sd.depth_columns)
        self.depth_panel.log_widget.log(
            f"Found {len(sd.depth_columns)} depth columns:"
        )
        for col in sd.depth_columns:
            short = SensorData.get_short_name(col)
            self.depth_panel.log_widget.log(f"  {short}")

        # Populate calibration mapping if calibration already loaded
        if self.calibration is not None:
            self.depth_panel.setup_calibration_mapping(
                self.calibration.sensor_labels, sd.depth_columns,
            )

        # Populate time offset ref sensor combo
        self.time_panel.populate_ref_sensor_combo(sd.depth_columns)

        # Update piston panel
        if self.piston_panel is not None:
            self.piston_panel.update_file_info(
                sd.source_file, sd.num_sensors, sd.row_count,
                sd.core_title,
            )
            # Populate sensor combos with (column, display_name) tuples
            columns_and_names = [
                (col, SensorData.get_location_name(col))
                for col in sd.depth_columns
            ]
            ws_col = sd.find_column_by_location('Weight Stand')
            rel_col = sd.find_column_by_location('Release')
            self.piston_panel.populate_sensor_combos(
                columns_and_names, ws_col, rel_col,
            )
            # Pre-fill parameters from metadata
            self.piston_panel.set_parameters_from_metadata(sd.metadata)

        # Update calculate panel
        if self.calculate_panel is not None:
            self.calculate_panel.update_file_info(
                sd.source_file, sd.num_sensors, sd.row_count,
                sd.core_title,
            )
            columns_and_names = [
                (col, SensorData.get_location_name(col))
                for col in sd.depth_columns
            ]
            ws_col = sd.find_column_by_location('Weight Stand')
            rel_col = sd.find_column_by_location('Release')
            trig_col = sd.find_column_by_location('Trigger')
            self.calculate_panel.populate_sensor_combos(
                columns_and_names, ws_col, rel_col, trig_col,
            )
            self.calculate_panel.set_parameters_from_metadata(sd.metadata)

    def _log_active(self, msg: str):
        """Log to the currently active panel."""
        mode = (
            self.main_window.get_current_mode() if self.main_window else None
        )
        if mode == 'View Data':
            self.view_panel.log_widget.log(msg)
        elif mode == 'Depth Offset':
            self.depth_panel.log_widget.log(msg)
        elif mode == 'Time Offset':
            self.time_panel.log_widget.log(msg)
        elif mode == 'Create Calibration':
            self.calibration_panel.log_widget.log(msg)
        elif mode == 'Trip Detector':
            self.trip_panel.log_widget.log(msg)
        elif mode == 'Piston Position':
            self.piston_panel.log_widget.log(msg)
        elif mode == 'Calculate':
            self.calculate_panel.log_widget.log(msg)

    def _show_error(self, title: str, msg: str):
        if self.main_window:
            QMessageBox.critical(self.main_window, title, msg)

    def _show_warning(self, msg: str):
        if self.main_window:
            QMessageBox.warning(self.main_window, "Warning", msg)
