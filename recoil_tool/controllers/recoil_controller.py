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

import numpy as np
from PySide6.QtWidgets import QMessageBox

from ..domain.models.recoil_params import DeploymentParams, ModelResult
from ..domain.processing.recoil_model import (
    forward_model, estimate_v0, _spring_constant,
    fit_empirical_curve, evaluate_empirical_curve,
)
from ..persistence.recoil_loader import RecoilLoader

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

        self._connect_signals()

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self):
        self.deployment_panel.plot_requested.connect(self._on_plot_requested)
        self.plot_view.trip_index_changed.connect(self._on_trip_index_changed)
        self.plot_view.fit_end_changed.connect(self._on_fit_end_changed)

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
                }
                color = _CURVE_COLORS.get(params.curve_type, '#756bb1')

                if params.auto_fit:
                    A, tau, omega, depth_model = fit_empirical_curve(
                        self._time_s, self._depth_m, self._trip_idx, params.curve_type,
                        fit_end_idx=self._fit_end_idx,
                    )
                    self.deployment_panel.set_empirical_params(A, tau, omega)
                else:
                    A, tau, omega = params.A_m, params.tau_s, params.omega_rads
                    depth_model = evaluate_empirical_curve(
                        self._time_s, self._depth_m, self._trip_idx,
                        params.curve_type, A, tau, omega,
                    )

                self.plot_view.plot_model_overlay(
                    self._trip_idx, depth_model, color=color
                )
                msg = f"Empirical curve plotted — A={A:.3f} m, tau={tau:.3f} s"
                if omega is not None:
                    msg += f", \u03c9={omega:.3f} rad/s"
                self._status(msg)
                self.results_panel.show_empirical_result(params.curve_type, A, tau, omega)
            except Exception as exc:
                self._show_error("Fit Error", str(exc))

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
