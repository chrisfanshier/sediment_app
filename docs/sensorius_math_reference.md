# Sensorius — Mathematical Reference

> **Word version:** `sensorius_math_reference.docx` in this folder uses native Word equations. Regenerate with `python docs/build_sensorius_math_docx.py`.

This document describes the units, algorithms, and output definitions used in **Sensorius** (the standalone coring sensor analysis application). Each analysis mode is covered with a brief summary, step-by-step procedure, and formulas.

**Scope:** Processing logic as implemented in `sensor_standalone/domain/processing/` and the analysis controller. Persistence refers to the portable SQLite project model.

---

## 1. Units and conventions

| Quantity | Storage in project / UI | Used in calculations |
|----------|-------------------------|----------------------|
| Depths (sensor readings, seafloor, results) | metres (m) | metres |
| Scope | feet (ft) on core record | converted: \(L_\mathrm{m} = L_\mathrm{ft} / 3.28\) |
| Core barrel length | feet (ft) | converted: \(L_\mathrm{m} = L_\mathrm{ft} / 3.28\) |
| Trigger core length | feet (ft) | converted: \(L_\mathrm{m} = L_\mathrm{ft} / 3.28\) |
| Trigger line length (Alter mode) | feet (ft) | converted: \(L_\mathrm{m} = L_\mathrm{ft} / 3.28\) |
| Trigger core penetration (`trigger_pen`) | metres (m) | metres |
| Time offsets | seconds (s) | seconds |
| Sampling rate | hertz (Hz) | \(f_s = 1 / \Delta t_\mathrm{median}\) |
| Frequencies (time-offset filter) | hertz (Hz) | hertz |
| Winch tension / payout | file units (often N, m) | as read; trip detection uses column values directly |
| Fixed weight-stand length | — | **1.5 m** (`WEIGHT_LENGTH`) |
| Piston offset constant | metres (m) | default **1.25 m** (user-adjustable in Piston Position mode) |

**Depth sign:** Increasing depth means deeper below the surface (standard oceanographic convention).

**Feet-to-metres factor:** Throughout the code, `FT_TO_M = 1/3.28` (not 0.3048).

**Array indices:** All event indices (`trip_idx`, `start_core_idx`, etc.) refer to rows in the merged sensor dataframe after preprocessing (outer merge on `datetime`, sorted ascending).

**Missing data:** Depth series are linearly interpolated (with forward/back fill at edges) before filtering or geometry calculations when NaNs are present.

---

## 2. Preprocessing (Data Manager)

Before any analysis mode runs, sensor files for a core are loaded and merged.

### 2.1 Summary

Registered sensor files (RBR `.rsk`, Star-Oddi `.dat`/`.acc`/`.txt`) are parsed to a common `datetime` column plus numeric channels. Columns whose names contain `depth`, `pressure`, `acceleration`, `g`, or `tilt` (case-insensitive) are retained. Each retained column is prefixed as `{sensor_location}_{file_name}_{original_column}` to avoid name collisions.

### 2.2 Merge algorithm

1. Parse each file → dataframe with `datetime` and selected columns.
2. For each column, rename to prefixed form.
3. **Outer merge** all frames on `datetime` (keeps all timestamps from all files).
4. Sort by `datetime`, reset index.
5. Depth columns are those containing `"Depth"` in the column name.

### 2.3 Winch data (for Winch mode)

Winch logs are stored per **cruise** (not per core). When auto-loading for a core:

1. Select winch files whose `[start_time, end_time]` overlaps the core deployment window `[start_datetime, end_datetime]`.
2. Parse and concatenate all overlapping files, sort by `datetime`.
3. **Trim** the combined series to the core deployment window.

Manual winch mode loads selected files in full without deployment-window trimming.

---

## 3. Analysis modes

### 3.1 View Data

**Summary:** Displays merged depth time series. No transformations beyond preprocessing.

**Algorithm:** Plot selected depth columns vs time (epoch or datetime).

**Outputs:** Visual only.

---

### 3.2 Depth Offset

**Summary:** Applies depth-dependent calibration (from a regression file) and/or constant manual offsets to align sensors in depth.

#### 3.2.1 Regression calibration

For each applicable sensor pair, a linear model was fit during **Create Calibration** (see §3.4):

\[
\Delta_{j,i}(d) = \mathrm{slope} \cdot d + \mathrm{intercept}
\]

where \(\Delta_{j,i}\) is the predicted difference \((\text{sensor}_j - \text{sensor}_i)\) at reference depth \(d\).

Given a **reference** depth column (unchanged), each **target** column is corrected:

\[
d_\mathrm{target}^\mathrm{corrected} = d_\mathrm{target} + \mathrm{sign} \cdot \Delta_{j,i}(d_\mathrm{ref})
\]

| Reference role | Sign | Meaning |
|----------------|------|---------|
| Reference is `sensor_i` in regression \((j - i)\) | \(+1\) | Add predicted offset to target \(i\) |
| Reference is `sensor_j` in regression \((j - i)\) | \(-1\) | Subtract predicted offset from target \(j\) |

The correction is evaluated at each sample using the reference sensor depth at that sample.

#### 3.2.2 Manual offset

\[
d_\mathrm{col}^\mathrm{corrected} = d_\mathrm{col} + \delta_m
\]

where \(\delta_m\) is a user-entered constant in metres (per column).

#### 3.2.3 Algorithm

1. Optionally load `DepthCalibration` JSON.
2. Map calibration labels (A, B, C, …) to depth column names.
3. For each enabled target, apply regression correction using reference depths.
4. Apply any non-zero manual offsets.

**Outputs:** Corrected depth traces; correction statistics (mean/std/min/max of applied correction per column).

---

### 3.3 Time Offset

**Summary:** Estimates clock lag between sensors by cross-correlating bandpass-filtered “heave” components of depth, then shifts non-reference sensors in time.

#### 3.3.1 Heave extraction

For a depth series \(z[n]\) over sample index \(n\) in the user-selected window:

1. **Detrend:** Fit a 2nd-order polynomial \(p(n)\) and subtract: \(z'[n] = z[n] - p(n)\).
2. **Bandpass:** 4th-order Butterworth, default passband **0.05–0.5 Hz**, sampling rate \(f_s = 1/\mathrm{median}(\Delta t)\).
3. Result \(h[n]\) is the heave signal used for correlation.

Default UI parameters: low = 0.05 Hz, high = 0.5 Hz, order = 4.

#### 3.3.2 Cross-correlation offset

For reference heave \(h_\mathrm{ref}\) and moving sensor heave \(h_\mathrm{mov}\):

\[
c[k] = \sum_n h_\mathrm{ref}[n] \cdot h_\mathrm{mov}[n - k]
\]

(Full mode correlation via `scipy.signal.correlate`.)

1. Find \(k^* = \arg\max |c[k]|\).
2. **Parabolic sub-sample refinement** on \((c[k^*-1], c[k^*], c[k^*+1])\):

\[
\delta = \frac{1}{2} \cdot \frac{c[k^*-1] - c[k^*+1]}{c[k^*-1] - 2c[k^*] + c[k^*+1]}
\]

3. Time offset in seconds:

\[
\Delta t = \frac{k^* + \delta}{f_s}
\]

Positive \(\Delta t\) means the moving sensor should be shifted forward in time to align with the reference.

#### 3.3.3 Applying the offset

For each non-reference sensor, depth values are resampled onto shifted time:

\[
z_\mathrm{corrected}(t) = \mathrm{interp}\bigl(t,\; t + \Delta t,\; z\bigr)
\]

(linear interpolation over elapsed seconds from file start).

Manual time offsets add a constant \(\Delta t\) per column by the same interpolation method.

#### 3.3.4 Algorithm

1. User selects a time range on the main plot.
2. Compute heave for reference and each other depth column.
3. Cross-correlate each sensor against reference → \(\Delta t\).
4. Compute RMS residual of aligned heave (quality metric).
5. Apply offsets to full record (or manual offsets).

**Outputs:** `offset_seconds` and `rms_value` per sensor; time-corrected depth traces.

---

### 3.4 Create Calibration

**Summary:** Builds a depth-dependent calibration file by collecting mean depth statistics from multiple casts at different depths, then fitting linear regressions of pairwise sensor differences vs mean depth.

#### 3.4.1 Per-cast statistics

For a selection (or full file) with depth columns \(\{c_1,\ldots,c_N\}\):

\[
\bar{d}_\mathrm{all} = \mathrm{mean}_n\Bigl(\mathrm{mean}_i\, d_i[n]\Bigr)
\]

\[
\bar{d}_i = \mathrm{mean}_n\, d_i[n]
\]

\[
\overline{\Delta}_{j,i} = \mathrm{mean}_n \bigl(d_j[n] - d_i[n]\bigr)
\]

Each cast contributes one point \((\bar{d}_\mathrm{all},\, \overline{\Delta}_{j,i})\) per sensor pair \((j,i)\).

#### 3.4.2 Regression

Requires **≥ 2 casts**. For each pair \((i,j)\):

\[
\overline{\Delta}_{j,i} = \mathrm{slope} \cdot \bar{d}_\mathrm{all} + \mathrm{intercept}
\]

Ordinary least squares (`scipy.stats.linregress`). Stored: slope, intercept, \(R^2\), p-value.

Calibration labels default to A, B, C, D mapped to sensors.

#### 3.4.3 Algorithm

1. Load calibration casts from project cores.
2. For each cast, compute `StatisticsResult` over user selection.
3. Pool points across casts; fit one regression per sensor pair.
4. Save JSON calibration file for use in Depth Offset mode.

**Outputs:** `DepthCalibration` JSON (regressions per sensor pair).

---

### 3.5 Trip Detector

**Summary:** Finds the **trip** instant — when sensors begin to diverge after release — using cross-sensor spread of Savitzky–Golay derivatives.

#### 3.5.1 Savitzky–Golay derivative

For each depth column \(d_i[n]\), with window length \(W\) (odd, default **51**), polynomial order \(P\) (default **3**), and sample interval \(\Delta t = 1/f_s\):

\[
\hat{d}_i^{(k)}[n] = \mathrm{Savgol}\bigl(d_i,\; W,\; P,\; \mathrm{deriv}=k,\; \Delta t\bigr)
\]

\(k =\) derivative order (UI: 0 = smoothed depth, 1 = velocity, 2 = acceleration, 3 = jerk). Default \(k=1\), default \(f_s=32\) Hz.

#### 3.5.2 Divergence

\[
\sigma[n] = \mathrm{std}_i\bigl(\hat{d}_i^{(k)}[n]\bigr)
\]

#### 3.5.3 Trip index

1. Zero out \(\sigma[n]\) for first and last `edge_buffer` samples (default **500**).
2. If any \(\sigma[n] > \tau\) (threshold \(\tau\), default **0.5**):  
   \(\texttt{trip\_idx} =\) first such \(n\) (confidence 0.8).
3. Else: \(\texttt{trip\_idx} = \arg\max \sigma[n]\) (confidence 0.5).

**Outputs:**

| Output | Definition |
|--------|------------|
| `trip_index` | Sample index of trip |
| `trip_datetime` | Timestamp at `trip_index` |
| `confidence` | 0.8 if threshold crossed, else 0.5 |
| `divergence` | \(\sigma[n]\) series for plotting |

The trip index propagates to Piston Position, Calculate, Winch alignment, and persistence.

---

### 3.6 Piston Position

**Summary:** Estimates the piston depth trace from weight-stand and release-device depths, scope, and core geometry.

#### 3.6.1 Start-core detection

Search begins at `trip_idx`. Scope threshold in metres: \(S_\mathrm{m} = \mathrm{scope\_ft} / 3.28\).

\[
\texttt{start\_core\_idx} = \min\{ n \ge \texttt{trip\_idx} : |d_\mathrm{release}[n] - d_\mathrm{WS}[n]| > S_\mathrm{m} \}
\]

If none found, index defaults to last sample.

Interpretation: coring/freefall begins when release device separates from weight stand by more than scope.

#### 3.6.2 Piston depth trace

Let \(B_\mathrm{m} = \mathrm{core\_length\_ft}/3.28\), \(O =\) offset constant (default 1.25 m).

**Before `start_core_idx`:**

\[
d_\mathrm{piston}[n] = d_\mathrm{WS}[n] + O + B_\mathrm{m}
\]

**From `start_core_idx` onward:**

\[
d_\mathrm{piston}[n] = d_\mathrm{release}[n] + S_\mathrm{m} + B_\mathrm{m} + O
\]

#### 3.6.3 Algorithm

1. Require trip index (from Trip Detector or manual trip time).
2. Detect `start_core_idx` from scope crossing.
3. Evaluate piecewise formula over full record.
4. Plot piston trace on main depth plot.

**Outputs:** `start_core_idx`, piston depth array (m).

---

### 3.7 Winch

**Summary:** Detects a rapid drop in winch telemetry (typically tension), then time-shifts winch data so that winch trip aligns with the sensor trip.

#### 3.7.1 Winch trip detection

For winch column values \(w[n]\) and optional search window \([T_\mathrm{start}, T_\mathrm{end}]\):

1. Exclude first/last `edge_buffer` samples (default **500**).
2. Find smallest \(n\) in window where:

\[
w[n-1] - w[n] \ge \tau_\mathrm{drop}
\]

Default \(\tau_\mathrm{drop} = 1000\) (same units as column, e.g. tension).

#### 3.7.2 Alignment

Let \(t_\mathrm{sensor}\) = epoch time at sensor trip index, \(t_\mathrm{winch}^\mathrm{orig}\) = epoch at winch trip on **unshifted** data.

\[
\Delta t_\mathrm{winch} = t_\mathrm{sensor} - t_\mathrm{winch}^\mathrm{orig}
\]

Apply to all winch timestamps:

\[
T_\mathrm{winch}^\mathrm{aligned}[n] = T_\mathrm{winch}^\mathrm{orig}[n] + \Delta t_\mathrm{winch}
\]

Sensor trip is resolved from Calculate panel trip time first, else `trip_detection_result`.

**Outputs:** `winch_trip_index`, `winch_time_offset_sec`, aligned winch plots (visual comparison with sensor depths).

---

### 3.8 Calculate

**Summary:** Computes coring deployment metrics from weight-stand, release, trigger, and piston traces around key event indices.

#### 3.8.1 Prerequisites and event indices

| Index | Source |
|-------|--------|
| `trip_idx` | Trip Detector or Calculate panel trip time |
| `start_core_idx` | Piston Position detection (or user drag) |
| `end_pen_idx` | User drag, or default: sample closest to `trip_time + 5 s` |
| `pullout_idx` | User drag, or default: index of global max weight-stand depth |
| `start_pen_idx` | First \(n \ge \texttt{trip\_idx}\) where core tip ≥ seafloor (see below) |

Optional **Savitzky–Golay smoothing** (default window 51, order 3) applied to WS/release/trigger before metrics.

#### 3.8.2 Seafloor depth

**From trigger core** (when trigger sensor and `trigger_core_length_ft` available):

\[
d_\mathrm{seafloor} = d_\mathrm{trigger}[\texttt{trip\_idx}] + L_{\mathrm{TC,m}} - p_\mathrm{trigger}
\]

where \(L_{\mathrm{TC,m}} = \mathrm{trigger\_core\_length\_ft}/3.28\) and \(p_\mathrm{trigger}\) = user trigger penetration (m).

**Manual override:** User-entered seafloor depth replaces the formula.

#### 3.8.3 Start of penetration (`start_pen`)

Core tip depth:

\[
d_\mathrm{tip}[n] = d_\mathrm{WS}[n] + 1.5 + L_{\mathrm{core,m}}
\]

\[
\texttt{start\_pen\_idx} = \min\{ n \ge \texttt{trip\_idx} : d_\mathrm{tip}[n] \ge d_\mathrm{seafloor} \}
\]

#### 3.8.4 Metric definitions

All depths in **metres** unless noted.

| Output | Formula | Requires |
|--------|---------|----------|
| **recoil_max** | \(\|d_\mathrm{release}[\texttt{trip}] - \min_{n \in [\texttt{trip},\texttt{end\_pen}]} d_\mathrm{release}[n]\|\) | `trip_idx` |
| **recoil_time_s** | \((n_\mathrm{peak} - \texttt{trip\_idx}) \cdot \mathrm{median}(\Delta t)\) where \(n_\mathrm{peak}\) is index of min release in window | `trip_idx` |
| **fall_dist** | \(\|d_\mathrm{WS}[\texttt{trip}] - d_\mathrm{WS}[\texttt{end\_pen}]\|\) | `trip_idx` |
| **suck_in** | \(\|d_\mathrm{WS}[\texttt{end\_pen}] - \max_n d_\mathrm{WS}[n]\|\) | `trip_idx` |
| **recoil_start** | \(\|d_\mathrm{release}[\texttt{trip}] - d_\mathrm{release}[\texttt{start\_core}]\|\) | trip + start_core |
| **freefall_start** | \(\|d_\mathrm{WS}[\texttt{trip}] - d_\mathrm{WS}[\texttt{start\_core}]\|\) | trip + start_core |
| **piston_suck** | \(d_\mathrm{piston}[n_\mathrm{pullout}] - d_\mathrm{piston}[n_\mathrm{cross}]\) | piston, start_core, trip |

**Piston suck crossing** \(n_\mathrm{cross}\): After `end_pen`, first index where release depth returns within 0.05 m of release at trip (search capped at trip + 600 s). If crossing is after pullout index, piston_suck is N/A.

| Output | Formula | Requires |
|--------|---------|----------|
| **pen_deficit** | \(d_\mathrm{seafloor} - \max_n d_\mathrm{WS}[n]\) | seafloor |
| **piston_alt** | \(d_\mathrm{seafloor} - d_\mathrm{piston}[\texttt{start\_core}]\) | seafloor + piston + start_core |
| **freefall_est** | \(\|d_\mathrm{WS}[\texttt{trip}] + 1.5 + L_{\mathrm{core,m}} - d_\mathrm{seafloor}\|\) | seafloor + core length |

The constant **1.5 m** is the fixed weight-stand length (`WEIGHT_LENGTH`).

#### 3.8.5 Algorithm

1. Resolve columns (weight stand, release, optional trigger).
2. Interpolate NaNs; optional SG smooth.
3. Resolve event indices.
4. Compute seafloor (formula or manual).
5. Compute `start_pen_idx`.
6. Call `compute_calculations()` with all inputs.
7. Display results table and geometry diagram.

---

### 3.9 Alter

**Summary:** Sensitivity analysis — re-runs piston position and Calculate metrics with **modified rig parameters** without changing stored core metadata. Trip time and user-placed indices (`end_pen`, `pullout`) are held fixed.

#### 3.9.1 Parameter shifts

User edits scope, trigger line length, core length, and/or trigger core length relative to database values. Changes are applied as **depth shifts** to sensor traces:

\[
\Delta_\mathrm{trig,m} = (\mathrm{trigger\_line\_ft}^\mathrm{new} - \mathrm{trigger\_line\_ft}^\mathrm{db}) / 3.28
\]

\[
\Delta_{\mathrm{TC,m}} = (\mathrm{trigger\_core\_length\_ft}^\mathrm{new} - \mathrm{trigger\_core\_length\_ft}^\mathrm{db}) / 3.28
\]

\[
d_\mathrm{WS}^\mathrm{mod} = d_\mathrm{WS} - \Delta_\mathrm{trig,m} - \Delta_{\mathrm{TC,m}}
\]
\[
d_\mathrm{release}^\mathrm{mod} = d_\mathrm{release} - \Delta_\mathrm{trig,m} - \Delta_{\mathrm{TC,m}}
\]
\[
d_\mathrm{trigger}^\mathrm{mod} = d_\mathrm{trigger} - \Delta_{\mathrm{TC,m}}
\]

Rationale (as implemented): longer trigger line shifts WS/release shallower; longer trigger core shifts all three traces shallower by \(\Delta_{\mathrm{TC,m}}\) while seafloor formula terms cancel.

#### 3.9.2 Re-analysis steps

1. Require prior **Calculate** results on the loaded core.
2. Apply shifts above (optional SG smooth, same as Calculate).
3. Re-detect `start_core_idx` with **new scope** on modified WS/release.
4. Recompute piston position with new scope, core length, and new `start_core_idx`.
5. Re-run `compute_calculations()` with modified arrays and metadata lengths.
6. Refresh geometry plot and start-penetration line.

**Not implemented:** Changing number of pig weights is logged and ignored.

**Outputs:** Same metrics as Calculate, under altered parameters; overlay of shifted traces on main plot.

---

### 3.10 Piston Analysis

**Summary:** Plots piston and weight-stand behaviour vs **core depth** (metres penetrated relative to start of penetration) over the interval from start of core opening through pullout, with SG-estimated velocities.

#### 3.10.1 Core depth axis

Window: samples from `start_core_idx` (or `start_pen_idx` if start_core unset) through `pullout_idx` inclusive.

\[
x_\mathrm{core}[n] = d_\mathrm{WS}[n] - d_\mathrm{WS}[\texttt{start\_pen\_idx}]
\]

\(x_\mathrm{core} = 0\) at first sediment penetration. Samples before `start_pen` within the window have \(x_\mathrm{core} < 0\).

#### 3.10.2 Velocity

Savitzky–Golay first derivative with \(\Delta t = \mathrm{median}(\Delta t_\mathrm{epoch})\):

\[
v[n] = \mathrm{Savgol}(d,\; W,\; P,\; \mathrm{deriv}=1,\; \Delta t)
\]

Default \(W=51\), \(P=3\). Units: **m/s**.

Computed separately for weight-stand and piston depth segments.

#### 3.10.3 Prerequisites

- `start_pen_idx` and `pullout_idx` from Calculate mode (or user-dragged lines)
- Piston trace from Piston Position mode
- Optional seafloor from Calculate results or manual override

**Outputs:** `core_depth`, `piston_depth`, `ws_depth`, `ws_velocity`, `piston_velocity` over the analysis window; seafloor reference line if available.

---

## 4. Save, restore, and project persistence

### 4.1 Summary

Analysis state is stored in the project SQLite database (`sensorius_data.sqlite`). Each **core** can have **multiple** `analysis_results` rows (one per save session). **Save All to Project** upserts a single row per analysis session (insert on first save after load, update thereafter). **Restore Results** reloads a chosen row and replays corrections in order.

### 4.2 Project folder layout

```
MyProject/
  sensorius_data.sqlite
  sensor_data/<cruise>/     # copied sensor files
  winch_data/<cruise>/      # copied winch files
```

### 4.3 Database tables (persistence)

**`cruises`** — cruise name, vessel, notes.

**`cores`** — per deployment: name, type, `core_length` (ft), `scope` (ft), deployment `start_datetime` / `end_datetime`, `trigger_line_length` (ft), `trigger_core_length` (ft), `trigger_core_penetration` (m), recovery fields, pig weights, wire type, notes.

**`sensor_files`** — file copy location, `sensor_location`, `sensor_type` (parser key).

**`winch_files`** — cruise-level winch logs with `start_time`, `end_time`, JSON `settings` (delimiter, columns, datetime parsing).

**`analysis_results`** — one analysis run per row:

| Column | Type | Meaning |
|--------|------|---------|
| `result_id` | integer | Primary key |
| `core_id` | integer | Parent core |
| `analyzed_at` | timestamp | Save time |
| `trip_index`, `trip_datetime` | int, time | Sensor trip event |
| `start_core_index`, `start_core_datetime` | int, time | Start of coring |
| `result_recoil_max` … `result_freefall_est` | float | Calculate outputs (m; `recoil_time_s` in s) |
| `trigger_pen_m` | float | Trigger penetration input (m) |
| `winch_trip_index`, `winch_trip_datetime`, `winch_time_offset_sec` | int, time, float | Winch alignment |
| `params` | JSON text | Panel settings (see §4.4) |

### 4.4 `params` JSON sections

Sections are merged independently; partial saves update only their section.

| Section | Contents |
|---------|----------|
| `depth_offset` | `calib_json`, `label_mapping`, `reference_sensor`, `manual_offsets` (m) |
| `time_offset` | `reference_col`, filter freqs/order, `manual_offsets` (s), per-sensor `offsets` list |
| `trip` | SG window/poly, derivative order, threshold, sampling rate, edge buffer |
| `piston` | column names, `scope_ft`, `core_length_ft`, `offset_constant_m` |
| `calc_inputs` | column picks, SG settings, indices (`trip`, `start_core`, `end_pen`, `pullout`), `trigger_pen_m`, lengths, `seafloor_manual` |
| `calc_notes` | Text notes from calculation run |
| `winch` | `aligned`, `winch_file_ids`, `load_mode`, `detection` params, `time_offset_sec`, sensor trip at align, `display` columns |

### 4.5 Restore order

When restoring result `#N`:

1. **Depth corrections** — replay regression + manual offsets onto a fresh copy of original sensor data.
2. **Time corrections** — replay cross-correlation or manual time shifts.
3. **Trip** — set `trip_detection_result` and trip line from flat columns.
4. **Winch** — if `params.winch.aligned`: reload winch files by ID, reapply `winch_time_offset_sec`, restore panel/plot settings; switch to Winch mode.
5. **Piston** — recompute piston trace from saved piston params + `start_core_index`.
6. **Calculate** — restore indices, manual seafloor, re-run calculations.

Skipped sections are reported in the status summary (e.g. “winch alignment (not saved)”).

### 4.6 Core metadata write-back

On save, `trigger_core_penetration` on the **core** row is updated from the Calculate panel trigger penetration value (when > 0).

---

## 5. Shared signal processing

### Savitzky–Golay filter

Used in Trip Detector, Calculate (optional smooth), Piston Analysis, and winch plotting contexts.

For window length \(W\) (odd), polynomial order \(P\), optional derivative order \(k\) and spacing \(\Delta t\):

\[
\hat{x}[n] = \sum_{j=-(W-1)/2}^{(W-1)/2} c_j\, x[n+j]
\]

Coefficients \(c_j\) come from local polynomial least-squares (SciPy `savgol_filter`). NaNs are linearly interpolated before filtering when needed.

---

## 6. Document history

| Version | Notes |
|---------|-------|
| 1.0 | Initial reference aligned with `sensor_standalone` processing modules |
