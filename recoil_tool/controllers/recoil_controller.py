"""
RecoilController — coordinator for the recoil overlay tool.

Responsibilities:
  - Load cruise/core lists from DB
  - Load Release Device RSK data + analysis result metadata
  - Coordinate forward model execution (user-supplied parameters)
  - Update GUI panels and plot view
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import dataclasses

import numpy as np
from PySide6.QtWidgets import QMessageBox

from ..domain.models.recoil_params import DeploymentParams, ModelResult
from ..domain.processing.recoil_model import (
    forward_model, estimate_v0, _spring_constant,
    fit_empirical_curve, evaluate_empirical_curve, compute_model_peak,
)
from ..persistence.recoil_loader import RecoilLoader
from ..persistence.recoil_results_io import upsert_result, load_results_for_core

if TYPE_CHECKING:
    from ..gui.main_window import MainWindow
    from ..gui.panels.deployment_panel import DeploymentPanel
    from ..gui.panels.results_panel import ResultsPanel
    from ..gui.views.recoil_plot_view import RecoilPlotView


class RecoilController:
    """
    Coordinator between DB, domain processing, and GUI widgets.

    Parameters
    ----------
    deployment_panel : DeploymentPanel
    results_panel    : ResultsPanel
    plot_view        : RecoilPlotView
    main_window      : MainWindow (optional, for status bar / dialogs)
    """

    def __init__(
        self,
        deployment_panel: 'DeploymentPanel',
        results_panel: 'ResultsPanel',
        plot_view: 'RecoilPlotView',
        main_window: 'Optional[MainWindow]' = None,
    ):
        self.deployment_panel = deployment_panel
        self.results_panel = results_panel
        self.plot_view = plot_view
        self.main_window = main_window

        # Working state
        self._time_s: Optional[np.ndarray] = None
        self._depth_m: Optional[np.ndarray] = None
        self._trip_idx: Optional[int] = None
        self._fit_end_idx: Optional[int] = None
        self._analysis_result: Optional[dict] = None
        self._loaded_core_id: Optional[int] = None

        # Last-plotted result (for Save)
        self._last_result_type: Optional[str] = None
        self._last_params: Optional[DeploymentParams] = None
        self._last_model_result: Optional[ModelResult] = None
        self._last_empirical_params: Optional[tuple] = None

        # Last smoothing result (for Save) — None until user applies the filter
        self._last_smooth_peak_m: Optional[float] = None
        self._last_smooth_elapsed_s: Optional[float] = None
        self._last_smooth_window: Optional[int] = None
        self._last_smooth_poly: Optional[int] = None

        # Saved results loaded from DB when a core is opened
        self._saved_results: dict = {}

        self._connect_signals()

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self):
        self.deployment_panel.plot_requested.connect(self._on_plot_requested)
        self.deployment_panel.curve_type_changed.connect(self._on_curve_type_selected)
        self.deployment_panel.smoothing_requested.connect(self._on_smoothing_requested)
        self.deployment_panel.smoothing_cleared.connect(self._on_smoothing_cleared)
        self.plot_view.trip_index_changed.connect(self._on_trip_index_changed)
        self.plot_view.fit_end_changed.connect(self._on_fit_end_changed)
        self.results_panel.save_requested.connect(self._on_save_requested)

    # ------------------------------------------------------------------
    # DB: dropdown population (called by MainWindow)
    # ------------------------------------------------------------------

    def fetch_cruises(self) -> list[dict]:
        return RecoilLoader.fetch_cruises()

    def fetch_cores(self, cruise_id: int) -> list[dict]:
        return RecoilLoader.fetch_cores_with_results(cruise_id)

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_core(self, core_id: int, core_info: dict):
        """
        Load the Release Device RSK and analysis result for a core.
        Pre-populates the deployment panel and places the trip marker.
        """
        try:
            # Load analysis result metadata
            result = RecoilLoader.load_analysis_result(core_id)
            if result is None:
                self._show_error(
                    "No Analysis Result",
                    f"No saved analysis result with a trip_index found for core "
                    f"{core_info.get('core_name', core_id)}.",
                )
                return

            self._analysis_result = result
            self._loaded_core_id = core_id

            # Load raw RSK data
            time_s, depth_m = RecoilLoader.load_release_device_data(core_id)
            if time_s is None:
                self._show_error(
                    "No Sensor Data",
                    f"Could not load Release Device RSK for core "
                    f"{core_info.get('core_name', core_id)}.",
                )
                return

            self._time_s = time_s
            self._depth_m = depth_m
            self._last_fit = None
            self._last_smooth_peak_m = None
            self._last_smooth_elapsed_s = None
            self._last_smooth_window = None
            self._last_smooth_poly = None

            # Resolve trip index from the stored trip_datetime (preferred) so
            # that the index is correct for the Release Device RSK alone.
            # trip_index in the DB is an index into the merged multi-sensor
            # DataFrame (which starts at an earlier sensor's first sample),
            # not the Release Device RSK, so using it directly causes an offset.
            #
            # Additionally, if a time correction was applied to the Release
            # Device before trip detection, trip_datetime reflects the
            # corrected timeline.  We subtract the stored offset so that
            # searchsorted lands on the correct raw RSK timestamp.
            import pandas as pd
            trip_datetime = result.get('trip_datetime')
            if trip_datetime is not None:
                trip_epoch = pd.Timestamp(trip_datetime).value / 1e9

                # Look up Release Device time offset (if any was applied)
                params = result.get('params') or {}
                release_col = params.get('piston', {}).get('release_col', '')
                time_offsets = params.get('time_offset', {}).get('offsets', [])
                release_time_offset = next(
                    (
                        o['offset_seconds']
                        for o in time_offsets
                        if o.get('sensor_col') == release_col
                        and not o.get('is_reference', False)
                    ),
                    0.0,
                )
                # Undo the correction: raw trip is offset_seconds earlier than
                # the corrected trip_datetime
                adjusted_epoch = trip_epoch - release_time_offset

                trip_idx = int(np.searchsorted(time_s, adjusted_epoch))
                trip_idx = min(trip_idx, len(time_s) - 1)
            else:
                # Fallback: use stored index (may be offset if from merged DF)
                raw_idx = result.get('trip_index', 0) or 0
                trip_idx = int(raw_idx) if 0 <= raw_idx < len(time_s) else 0
            self._trip_idx = trip_idx

            # Default fit window: trip + 10 s (same formula used by plot_view)
            dt = float(np.median(np.diff(time_s))) if len(time_s) > 1 else 1.0
            self._fit_end_idx = min(
                trip_idx + max(1, int(10.0 / dt)), len(time_s) - 1
            )

            # Update GUI
            self.plot_view.clear()
            self.plot_view.plot_depth_trace(
                time_s, depth_m,
                trip_idx=self._trip_idx,
                core_name=core_info.get('core_name', ''),
            )
            # Augment core_info with depth at trip so pre_populate can use it
            # as deployment depth (more accurate than result_seafloor estimate)
            augmented = dict(core_info)
            augmented['depth_at_trip'] = float(self._depth_m[self._trip_idx])
            self.deployment_panel.pre_populate(augmented)
            self.results_panel.clear()

            # Restore any previously saved results for this core (physics by default)
            self._saved_results = load_results_for_core(core_id)
            self._restore_saved_result('physics')

            self._status(
                f"Loaded {core_info.get('core_name', core_id)} — "
                f"{len(time_s):,} samples, trip at index {self._trip_idx}"
            )

        except Exception as exc:
            self._show_error("Load Error", str(exc))

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_trip_index_changed(self, idx: int):
        """User dragged the trip marker to a new position."""
        self._trip_idx = idx
        self._status(f"Trip index updated to {idx}")

    def _on_fit_end_changed(self, idx: int):
        """User dragged the fit endpoint marker to a new position."""
        self._fit_end_idx = idx
        self._status(f"Fit end index updated to {idx}")

    def _on_curve_type_selected(self, curve_type: str):
        """User changed the curve type combobox — restore any saved result."""
        self._restore_saved_result(curve_type)

    def _on_save_requested(self):
        """Save the last-plotted result to recoil_analysis_results."""
        if self._last_result_type is None:
            self._show_warning("Nothing to save", "Run the model or fit a curve first.")
            return
        if self._loaded_core_id is None:
            self._show_warning("No core loaded", "Load a core first.")
            return
        if self._time_s is None or self._depth_m is None or self._trip_idx is None:
            return

        trip_epoch  = float(self._time_s[self._trip_idx])
        fit_end_idx = self._fit_end_idx if self._fit_end_idx is not None else self._trip_idx
        fit_end_epoch = float(self._time_s[min(fit_end_idx, len(self._time_s) - 1)])

        # Observed raw-signal peak over the current fit window [trip, fit_end].
        observed_peak_displacement_m: Optional[float] = None
        observed_peak_time_s: Optional[float] = None
        fit_end_idx = min(max(fit_end_idx, self._trip_idx), len(self._depth_m) - 1)
        post_trip_depth = self._depth_m[self._trip_idx: fit_end_idx + 1]
        if len(post_trip_depth) > 0 and np.any(np.isfinite(post_trip_depth)):
            raw_peak_rel = int(np.nanargmin(post_trip_depth))
            observed_peak_displacement_m = abs(
                float(self._depth_m[self._trip_idx]) - float(post_trip_depth[raw_peak_rel])
            )
            peak_abs_idx = self._trip_idx + raw_peak_rel
            observed_peak_time_s = float(self._time_s[peak_abs_idx] - self._time_s[self._trip_idx])

        dep_dict = dataclasses.asdict(self._last_params) if self._last_params else {}

        # Pack savgol parameters into the JSONB snapshot when a filter has been applied
        if self._last_smooth_window is not None:
            dep_dict['smoothing'] = {
                'window_length': self._last_smooth_window,
                'poly_order':    self._last_smooth_poly,
            }

        curve_type = self._last_result_type
        model_peak_displacement_m: Optional[float] = None
        model_peak_time_s: Optional[float] = None

        kwargs: dict = {}
        if curve_type == 'physics' and self._last_model_result is not None:
            r = self._last_model_result
            model_peak_displacement_m = r.peak_displacement_m
            model_peak_time_s = r.peak_time_s
            kwargs = dict(
                E_gpa=r.deployment.E_gpa,
                C_drag=r.deployment.C_drag,
                v0_ms=r.v0_ms,
                k_nm=r.k_nm,
            )
        elif self._last_empirical_params is not None:
            A, tau, omega = self._last_empirical_params
            if curve_type == 'single_lobe_damped':
                # A = H, tau = t_p, omega = None
                model_peak_displacement_m, model_peak_time_s = compute_model_peak(
                    curve_type=curve_type,
                    H_m=A,
                    t_p_s=tau,
                    alpha=self._last_params.alpha,
                )
                kwargs = dict(H_m=A, t_p_s=tau, alpha=self._last_params.alpha)
            else:
                model_peak_displacement_m, model_peak_time_s = compute_model_peak(
                    curve_type=curve_type,
                    A_m=A,
                    tau_s=tau,
                    omega_rads=omega,
                )
                kwargs = dict(A_m=A, tau_s=tau, omega_rads=omega)

        try:
            upsert_result(
                self._loaded_core_id, curve_type,
                trip_epoch, fit_end_epoch, dep_dict,
                model_peak_displacement_m=model_peak_displacement_m,
                model_peak_time_s=model_peak_time_s,
                observed_peak_displacement_m=observed_peak_displacement_m,
                observed_peak_time_s=observed_peak_time_s,
                observed_smooth_peak_displacement_m=self._last_smooth_peak_m,
                observed_smooth_peak_time_s=self._last_smooth_elapsed_s,
                **kwargs,
            )
            # Update local cache so switching curve types immediately sees it
            self._saved_results[curve_type] = {
                'curve_type':                  curve_type,
                'trip_time_epoch':             trip_epoch,
                'fit_end_epoch':               fit_end_epoch,
                'deployment_params':           dep_dict,
                'model_peak_displacement_m':   model_peak_displacement_m,
                'model_peak_time_s':           model_peak_time_s,
                'observed_peak_displacement_m': observed_peak_displacement_m,
                'observed_peak_time_s':         observed_peak_time_s,
                'observed_smooth_peak_displacement_m': self._last_smooth_peak_m,
                'observed_smooth_peak_time_s':         self._last_smooth_elapsed_s,
                **kwargs,
            }
            self._status(f"Saved {curve_type} result for core {self._loaded_core_id}")
        except Exception as exc:
            self._show_error("Save Error", str(exc))

    def _restore_saved_result(self, curve_type: str):
        """Restore a previously saved result for this core + curve_type."""
        if not self._saved_results or self._time_s is None:
            return
        saved = self._saved_results.get(curve_type)
        if saved is None:
            return

        # Restore trip position
        if saved.get('trip_time_epoch') is not None:
            new_trip = int(np.searchsorted(self._time_s, saved['trip_time_epoch']))
            new_trip = min(new_trip, len(self._time_s) - 1)
            self._trip_idx = new_trip
            self.plot_view.update_trip_marker(new_trip)

        # Restore fit-end position
        if saved.get('fit_end_epoch') is not None:
            new_end = int(np.searchsorted(self._time_s, saved['fit_end_epoch']))
            new_end = min(new_end, len(self._time_s) - 1)
            self._fit_end_idx = new_end
            self.plot_view.update_fit_end_marker(new_end)

        # Build DeploymentParams from saved columns
        dp = saved.get('deployment_params') or {}
        
        # Build base DeploymentParams (physics + shared fields)
        params = DeploymentParams(
            depth_m=float(dp.get('depth_m') or 0.0),
            corer_lbs=float(dp.get('corer_lbs') or 0.0),
            instrument_lbs=float(dp.get('instrument_lbs') or 0.0),
            rope_type=dp.get('rope_type') or 'hmpe',
            rope_dia_mm=float(dp.get('rope_dia_mm') or 14.3),
            E_gpa=float(saved.get('E_gpa') or dp.get('E_gpa') or 45.0),
            C_drag=float(saved.get('C_drag') or dp.get('C_drag') or 0.01),
            curve_type=curve_type,
            auto_fit=False,
        )
        # Restore empirical parameters depending on curve type
        if curve_type == 'single_lobe_damped':
            params.H_m = float(saved.get('H_m') or dp.get('H_m') or 1.0)
            params.t_p_s = float(saved.get('t_p_s') or dp.get('t_p_s') or 1.0)
            params.alpha = float(saved.get('alpha') or dp.get('alpha') or 0.25)
        else:
            params.A_m = float(saved.get('A_m') or dp.get('A_m') or 2.0)
            params.tau_s = float(saved.get('tau_s') or dp.get('tau_s') or 1.0)
            params.omega_rads = float(saved.get('omega_rads') or dp.get('omega_rads') or 1.0)

        self.deployment_panel.restore_params(params)
        self._on_plot_requested(params)

        # Restore smoothing results if they were saved with this result
        smooth_peak = saved.get('observed_smooth_peak_displacement_m')
        smooth_time = saved.get('observed_smooth_peak_time_s')
        if smooth_peak is not None and smooth_time is not None:
            self._last_smooth_peak_m = float(smooth_peak)
            self._last_smooth_elapsed_s = float(smooth_time)
            self.results_panel.show_smooth_result(self._last_smooth_peak_m, self._last_smooth_elapsed_s)

            # Restore savgol spinboxes from the JSONB smoothing sub-dict
            smoothing_cfg = (saved.get('deployment_params') or {}).get('smoothing') or {}
            win = smoothing_cfg.get('window_length')
            poly = smoothing_cfg.get('poly_order')
            if win is not None and poly is not None:
                self._last_smooth_window = int(win)
                self._last_smooth_poly = int(poly)
                self.deployment_panel.restore_smooth_params(int(win), int(poly))

    def _on_plot_requested(self, params: DeploymentParams):
        """Run the model or empirical fit and overlay on the plot."""
        if self._time_s is None or self._depth_m is None:
            self._show_warning("No data loaded", "Load a core first.")
            return
        if self._trip_idx is None:
            self._show_warning("No trip index", "Place a trip marker first.")
            return
        if params.depth_m <= 0:
            self._show_warning("Invalid input", "Deployment depth must be > 0.")
            return

        if params.curve_type == 'physics':
            if params.corer_lbs <= 0:
                self._show_warning("Invalid input", "Corer weight must be > 0.")
                return

            self._status("Running forward model…")
            try:
                v0 = estimate_v0(self._time_s, self._depth_m, self._trip_idx)

                t_post = self._time_s[self._trip_idx:]
                d_post = self._depth_m[self._trip_idx:]
                t_rel = t_post - t_post[0]

                x_model = forward_model(
                    t_rel, params, params.E_gpa, params.C_drag, v0
                )

                # Convert upward displacement to absolute depth
                depth_model = d_post[0] - x_model

                self.plot_view.plot_model_overlay(self._trip_idx, depth_model)

                # Build summary result
                k = _spring_constant(params.E_gpa, params.rope_dia_mm, params.depth_m)
                peak_idx = int(np.argmax(x_model))
                result = ModelResult(
                    v0_ms=v0,
                    peak_displacement_m=float(x_model[peak_idx]),
                    peak_time_s=float(t_rel[peak_idx]),
                    k_nm=float(k),
                    deployment=params,
                )
                self.results_panel.show_result(result)

                self._last_result_type = 'physics'
                self._last_params = params
                self._last_model_result = result

                self._status(
                    f"Model plotted — E={params.E_gpa:.1f} GPa, "
                    f"k={k:,.0f} N/m, "
                    f"peak={result.peak_displacement_m:.3f} m at {result.peak_time_s:.1f} s"
                )
            except Exception as exc:
                self._show_error("Model Error", str(exc))

        else:  # empirical curve
            self._status("Fitting empirical curve…")
            try:
                _CURVE_COLORS = {
                    'exponential':       '#756bb1',
                    'critically_damped': '#31a354',
                    'gamma_pulse':       '#e6550d',
                    'damped_sine':       '#de2d26',
                    'single_lobe_damped': '#3182bd', # new
                }
                color = _CURVE_COLORS.get(params.curve_type, '#756bb1')

                if params.auto_fit:
                    A, tau, omega, depth_model = fit_empirical_curve(
                        self._time_s, self._depth_m, self._trip_idx, params.curve_type,
                        fit_end_idx=self._fit_end_idx,
                    )
                    if params.curve_type == 'single_lobe_damped':
                        params.alpha = float(omega) if omega is not None else params.alpha
                        self.deployment_panel.set_empirical_params(A, tau, None, params.alpha)
                    else:
                        self.deployment_panel.set_empirical_params(A, tau, omega)
                else:
                    if params.curve_type == 'single_lobe_damped':
                        A, tau, omega = params.H_m or 0.0, params.t_p_s or 1.0, None
                        depth_model = evaluate_empirical_curve(
                            self._time_s, self._depth_m, self._trip_idx,
                            params.curve_type, A, tau, alpha=params.alpha,
                        )
                    else:
                        A, tau, omega = params.A_m, params.tau_s, params.omega_rads
                        depth_model = evaluate_empirical_curve(
                            self._time_s, self._depth_m, self._trip_idx,
                            params.curve_type, A, tau, omega,
                        )

                # Keep the params snapshot aligned with fitted/manual values for Save.
                if params.curve_type == 'single_lobe_damped':
                    params.H_m = A
                    params.t_p_s = tau
                    if omega is not None:
                        params.alpha = float(omega)
                else:
                    params.A_m = A
                    params.tau_s = tau
                    if omega is not None:
                        params.omega_rads = omega

                self.plot_view.plot_model_overlay(
                    self._trip_idx, depth_model, color=color
                )
                if params.curve_type == 'single_lobe_damped':
                    # A = H, tau = t_p
                    msg = f"Empirical curve plotted — H={A:.3f} m, t_p={tau:.3f} s, alpha={params.alpha:.2f}"
                    self._status(msg)
                    self.results_panel.show_empirical_result(params.curve_type, A, tau, params.alpha)
                else:
                    msg = f"Empirical curve plotted — A={A:.3f} m, tau={tau:.3f} s"
                    if omega is not None:
                        msg += f", \u03c9={omega:.3f} rad/s"
                    self._status(msg)
                    self.results_panel.show_empirical_result(params.curve_type, A, tau, omega)

                self._last_result_type = params.curve_type
                self._last_params = params
                self._last_empirical_params = (A, tau, omega)
            except Exception as exc:
                self._show_error("Fit Error", str(exc))

    def _on_smoothing_requested(self, window_length: int, poly_order: int):
        """Apply a Savitzky-Golay filter to the full depth trace and display the overlay."""
        if self._time_s is None or self._depth_m is None:
            self._show_warning("No data loaded", "Load a core first.")
            return
        if self._trip_idx is None:
            self._show_warning("No trip index", "Place a trip marker first.")
            return

        from scipy.signal import savgol_filter

        # Enforce odd window length (scipy requirement)
        if window_length % 2 == 0:
            window_length += 1

        if window_length <= poly_order:
            self._show_warning(
                "Invalid smoothing params",
                f"Window length ({window_length}) must be greater than poly order ({poly_order}).",
            )
            return

        try:
            depth_smooth = savgol_filter(self._depth_m, window_length, poly_order)
            self.plot_view.plot_smooth_overlay(depth_smooth)

            # Max recoil = depth_at_trip - min_depth in [trip_idx, fit_end_idx]
            # (positive upward displacement, since depth is positive downward)
            end = self._fit_end_idx if self._fit_end_idx is not None else len(self._depth_m) - 1
            end = min(end, len(depth_smooth) - 1)
            depth_at_trip = float(depth_smooth[self._trip_idx])
            segment = depth_smooth[self._trip_idx : end + 1]
            local_idx = int(np.argmin(segment))
            min_depth = float(segment[local_idx])
            max_recoil = abs(depth_at_trip - min_depth)
            elapsed_s = float(
                self._time_s[self._trip_idx + local_idx] - self._time_s[self._trip_idx]
            )

            self._last_smooth_peak_m = max_recoil
            self._last_smooth_elapsed_s = elapsed_s
            self._last_smooth_window = window_length
            self._last_smooth_poly = poly_order

            self.results_panel.show_smooth_result(max_recoil, elapsed_s)
            self._status(
                f"Smoothed (win={window_length}, poly={poly_order}) — "
                f"max recoil: {max_recoil:.3f} m at {elapsed_s:.2f} s after trip"
            )
        except Exception as exc:
            self._show_error("Smoothing Error", str(exc))

    def _on_smoothing_cleared(self):
        """Remove the smoothed trace overlay and reset smoothing result labels."""
        self.plot_view.clear_smooth_overlay()
        self.results_panel.clear_smooth_result()
        self._last_smooth_peak_m = None
        self._last_smooth_elapsed_s = None
        self._last_smooth_window = None
        self._last_smooth_poly = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _status(self, msg: str):
        if self.main_window is not None:
            self.main_window.statusBar().showMessage(msg)
        else:
            print(msg)

    def _show_error(self, title: str, msg: str):
        self._status(f"ERROR: {msg}")
        if self.main_window is not None:
            QMessageBox.critical(self.main_window, title, msg)
        else:
            print(f"ERROR: {title}: {msg}")

    def _show_warning(self, title: str, msg: str):
        self._status(msg)
        if self.main_window is not None:
            QMessageBox.warning(self.main_window, title, msg)