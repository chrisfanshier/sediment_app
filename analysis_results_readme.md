# Analysis Results Tables — Reference Guide

This document describes the two PostgreSQL tables used to store coring deployment analysis results: **`sensor_analysis_results`** and **`recoil_analysis_results`**. It covers every column, the full structure of the `params` and `deployment_params` JSONB blobs, and how to query and parse them.

---

## Table 1: `sensor_analysis_results`

**What it is:** The primary results table for the sensor tool. Each row represents one analysis run for one core deployment. Flat columns store the key computed measurements; the `params` JSONB blob stores all configuration inputs used to produce those measurements, divided into sections by panel.

**Primary key:** `result_id`

**Plain English:** Each row answers "what happened during core deployment #X?" It records the depths and timing of key events — when the core hit the seafloor, how far it penetrated, how much it rebounded — alongside a complete record of every setting active when the analysis was run.

---

### Flat Column Reference

#### Identity & Timing

| Column | Type | Description |
|---|---|---|
| `result_id` | integer | Auto-incrementing primary key. Returned by `insert_result()`. |
| `core_id` | integer | Which core this result belongs to. Foreign key → `cores.core_id`. |
| `analyzed_at` | timestamp | When the analysis was run. Set automatically to `CURRENT_TIMESTAMP` on insert. |
| `created_at` | timestamp | When this row was first created. Set automatically on insert. |
| `modified_at` | timestamp | When this row was last modified. Updated automatically by a trigger on every `UPDATE`. |

#### Event Positions

These columns identify *where* in the raw sensor time-series each key event occurred.

| Column | Type | Description |
|---|---|---|
| `trip_index` | integer | Array index in the raw sensor data where the trip event (core release) was detected. |
| `trip_datetime` | timestamp | Wall-clock time of the trip event. |
| `start_core_index` | integer | Array index where the core barrel started penetrating the seafloor. Comes shortly after `trip_index`. `NULL` if a Trigger Core/Weight sensor was not available. |
| `start_core_datetime` | timestamp | Wall-clock time corresponding to `start_core_index`. |

#### Computed Results

All `result_*` columns are in **metres (m)**.

| Column | Type | Description |
|---|---|---|
| `result_recoil_max` | float | Maximum upward rebound (recoil) distance of the weight stand after the trip, measured over the recoil window. The primary output of most analyses. |
| `result_fall_dist` | float | Total free-fall distance of the weight stand between release and seafloor impact. |
| `result_suck_in` | float | Piston suck-in distance — how far the piston was drawn into the core liner after penetration stopped. Positive = piston moved upward relative to the core. `NULL` if the release device crossing occurred after pullout (suck-in not measurable). |
| `result_recoil_start` | float | Depth of the weight stand at the moment recoil begins (i.e. at the trip point). |
| `result_freefall_start` | float | Depth of the weight stand at the moment free-fall begins. |
| `result_piston_suck` | float | Depth value associated with the piston suck-in crossing event on the release device sensor. `NULL` when suck-in is not applicable. |
| `result_seafloor` | float | Estimated seafloor depth, derived from the Trigger Core/Weight sensor profile. `NULL` if no Trigger Core/Weight sensor was available. |
| `result_piston_alt` | float | Alternative piston position estimate. `NULL` if not calculable. |
| `result_pen_deficit` | float | Penetration deficit — difference between expected and actual core penetration. Negative = core penetrated less than expected. `NULL` if not calculable. |
| `result_freefall_est` | float | Estimated free-fall distance based on trigger core length and geometry, used as a cross-check against `result_fall_dist`. |
| `trigger_pen_m` | float | User-supplied estimate of how deep the trigger core penetrated, in metres. Used as an input to seafloor and penetration calculations. |

#### Sync & Provenance

| Column | Type | Description |
|---|---|---|
| `created_on_ship` | boolean | `true` if this row was created aboard the ship (the normal case). Defaults to `true`. |
| `sync_status` | varchar(20) | Replication state for shore-side sync. `'pending'` = not yet synced; `'synced'` = successfully replicated. Defaults to `'pending'`. |
| `last_synced_at` | timestamp | When this row was last successfully synced to the central database. `NULL` until first sync. |
| `central_id` | integer | The `result_id` assigned in the central (shore-side) database after sync. `NULL` until synced. |

---

### `params` JSONB Structure

The `params` column stores all configuration and processing inputs used during analysis. It is divided into **sections**, each written by a different analysis panel. Sections are merged independently — saving one panel never overwrites another's data.

The sections present in current data are: `trip`, `piston`, `time_offset`, `depth_offset`, `calc_inputs`, and `calc_notes`.

---

#### Section: `trip`

Controls how the trip event (core release moment) is detected from the raw depth signal.

```json
"trip": {
  "sampling_rate_hz": 32.0,
  "threshold": 0.5,
  "sg_window": 51,
  "sg_poly": 3,
  "derivative_order": 1,
  "edge_buffer": 500
}
```

| Field | Type | Description |
|---|---|---|
| `sampling_rate_hz` | float | Sampling rate of the raw sensor data in Hz. Typical values: `32.0` (RBR .rsk files), `10.0` (older .DAT files). |
| `threshold` | float | Detection threshold applied to the smoothed derivative signal. Higher values require a sharper velocity change to declare a trip. Range in current data: ~0.3–1.0. |
| `sg_window` | integer | Savitzky-Golay smoothing window length in samples. Must be odd. `51` in all current rows. |
| `sg_poly` | integer | Savitzky-Golay polynomial order. `3` in all current rows. |
| `derivative_order` | integer | Order of the derivative computed for trip detection. `1` = velocity. Always `1` in current data. |
| `edge_buffer` | integer | Number of samples ignored at the start and end of the signal to avoid edge artefacts. `500` in all current rows. |

---

#### Section: `piston`

Configuration for the piston/scope geometry used in penetration and suck-in calculations. Only present when a full analysis including piston calculations was run.

```json
"piston": {
  "core_length_ft": 60.0,
  "scope_ft": 22.0,
  "offset_constant_m": 1.25,
  "weight_stand_col": "Weight Stand_230406_20250620_1208_Profile1.rsk_Depth (m)",
  "release_col": "Release Device_236222_20250620_1219_Profile1.rsk_Depth (m)"
}
```

| Field | Type | Description |
|---|---|---|
| `core_length_ft` | float | Length of the core barrel in feet. |
| `scope_ft` | float | Scope (slack) length in feet — the free length of cable between the weight stand and the release device. |
| `offset_constant_m` | float | Fixed vertical offset between the weight stand sensor and the top of the core barrel, in metres. Typical value: `1.25`. Older deployments may use `3.25`–`3.5`. |
| `weight_stand_col` | string | Full column name of the Weight Stand depth sensor from the raw data file. Format: `"Weight Stand_{serial}_{datetime}_Depth (m)"`. |
| `release_col` | string | Full column name of the Release Device depth sensor. Format: `"Release Device_{serial}_{datetime}_Depth (m)"`. |

---

#### Section: `time_offset`

Parameters for cross-correlation alignment of depth sensors that have clock drift relative to each other.

```json
"time_offset": {
  "reference_col": "Weight Stand_230406_20250620_1208_Profile1.rsk_Depth (m)",
  "filter_low_hz": 0.05,
  "filter_high_hz": 0.5,
  "filter_order": 4,
  "manual_offsets": {
    "Weight Stand_230406_20250620_1208_Profile1.rsk_Depth (m)": 0.0,
    "Release Device_236222_20250620_1219_Profile1.rsk_Depth (m)": 0.0
  },
  "offsets": [
    {
      "sensor_col": "Release Device_..._Depth (m)",
      "offset_seconds": 0.0,
      "rms_value": 0.0,
      "is_reference": true
    },
    {
      "sensor_col": "Weight Stand_..._Depth (m)",
      "offset_seconds": -3.909,
      "rms_value": 0.112,
      "is_reference": false
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `reference_col` | string | The sensor column used as the time reference. All other sensors are shifted to align with this one. |
| `filter_low_hz` | float | Low-frequency cutoff of the bandpass filter applied before cross-correlation, in Hz. |
| `filter_high_hz` | float | High-frequency cutoff of the bandpass filter, in Hz. |
| `filter_order` | integer | Order of the Butterworth bandpass filter. `4` or `5` in current data. |
| `manual_offsets` | object | User-supplied time offsets in seconds, keyed by sensor column name, applied on top of any auto-detected offset. `0.0` means no manual correction. Non-zero values (e.g. `-0.4`) indicate a user-applied shift. |
| `offsets` | array | Auto-detected time offset results, one object per sensor. Empty array `[]` when auto-alignment was not run. Each object contains: `sensor_col` (full sensor name), `offset_seconds` (shift applied to align this sensor), `rms_value` (residual RMS error after alignment — lower is better), `is_reference` (true for the reference sensor, which always has offset 0). |

---

#### Section: `depth_offset`

Parameters for correcting systematic depth offsets between sensors caused by physical height differences in the deployment rig, using linear regression calibration from a static soak.

```json
"depth_offset": {
  "reference_sensor": "B",
  "calib_json": {
    "num_sensors": 3,
    "sensor_labels": ["A", "B", "C"],
    "regressions": [
      {
        "sensor_i": "A",
        "sensor_j": "B",
        "slope": -0.000336,
        "intercept": -0.124,
        "r_squared": 0.9887,
        "p_value": 4.5e-11
      }
    ]
  },
  "label_mapping": {
    "A": "Trigger Core/Weight_230405_20250620_1213_Profile1.rsk_Depth (m)",
    "B": "Weight Stand_230406_20250620_1208_Profile1.rsk_Depth (m)",
    "C": "Release Device_236222_20250620_1219_Profile1.rsk_Depth (m)"
  },
  "manual_offsets": {
    "Weight Stand_230406_20250620_1208_Profile1.rsk_Depth (m)": 0.0,
    "Release Device_236222_20250620_1219_Profile1.rsk_Depth (m)": -15.0
  }
}
```

| Field | Type | Description |
|---|---|---|
| `reference_sensor` | string | Short label (`"A"`, `"B"`, or `"C"`) of the sensor all others are corrected relative to. Typically `"B"` (Weight Stand). Empty string `""` when depth offset calibration was not applied. |
| `calib_json` | object or null | Calibration data from a pre-deployment static soak. `null` when no calibration was run. |
| `calib_json.num_sensors` | integer | Number of sensors in the calibration (2 or 3 in current data). |
| `calib_json.sensor_labels` | array | Short labels assigned to each sensor, e.g. `["A", "B", "C"]`. |
| `calib_json.regressions` | array | One object per sensor pair. Each contains: `sensor_i` and `sensor_j` (the two labels), `slope` and `intercept` (linear regression coefficients used to correct one sensor relative to the other), `r_squared` (goodness of fit — values near `1.0` indicate a reliable calibration), and `p_value` (statistical significance of the regression). |
| `label_mapping` | object | Maps short sensor labels (`"A"`, `"B"`, `"C"`) to their full column names in the raw data. May be empty `{}` when calibration is not configured. Not all labels need to be present — rows with only 2 sensors will only have 2 entries. |
| `manual_offsets` | object | User-supplied static depth corrections in metres, keyed by full sensor column name. Non-zero values (e.g. `-15.0`, `-0.4`, `2.0`) indicate the sensor required a manual depth correction, typically because it was physically mounted at a significantly different height. `0.0` means no manual correction. |

---

#### Section: `calc_inputs` and `calc_notes`

Written when a full calculation is run. `calc_inputs` records every index and parameter used; `calc_notes` provides human-readable annotations explaining how key indices were found or why certain calculations were skipped.

```json
"calc_inputs": {
  "trip_idx": 353240,
  "start_core_idx": 353285,
  "end_pen_idx": 353400,
  "pullout_idx": 355581,
  "trigger_col": "Trigger Core/Weight_230405_20250620_1213_Profile1.rsk_Depth (m)",
  "weight_stand_col": "Weight Stand_230406_20250620_1208_Profile1.rsk_Depth (m)",
  "release_col": "Release Device_236222_20250620_1219_Profile1.rsk_Depth (m)",
  "trigger_pen_m": 3.0,
  "core_length_ft": 60.0,
  "trigger_core_length_ft": 10.0,
  "seafloor_manual": null,
  "smoothing_enabled": false,
  "sg_window": null,
  "sg_poly": null
},
"calc_notes": [
  "recoil_max window: idx 353240..353400",
  "piston_suck: ws_max_idx=355581, cross_idx=354362"
]
```

| Field | Type | Description |
|---|---|---|
| `trip_idx` | integer | Array index used as the trip point for this calculation. |
| `start_core_idx` | integer or null | Array index used as the core-start point. `null` when not determinable. |
| `end_pen_idx` | integer | Array index marking the end of the penetration window and the end of the recoil_max measurement window. |
| `pullout_idx` | integer | Array index where the weight stand reached its maximum depth post-trip (i.e. pullout point). |
| `trigger_col` | string or null | Full column name of the Trigger Core/Weight sensor. `null` when not available — seafloor calculations are skipped in this case. |
| `weight_stand_col` | string | Full column name of the Weight Stand sensor used. |
| `release_col` | string | Full column name of the Release Device sensor used. |
| `trigger_pen_m` | float | Trigger penetration depth in metres as used in this calculation. |
| `core_length_ft` | float or null | Core barrel length in feet. `null` for some legacy deployments. |
| `trigger_core_length_ft` | float or null | Trigger core length in feet. |
| `seafloor_manual` | float or null | Manually specified seafloor depth override in metres. `null` when not used. |
| `smoothing_enabled` | boolean | Whether Savitzky-Golay smoothing was applied to the signal. `false` in all current rows. |
| `sg_window` / `sg_poly` | integer or null | Smoothing parameters; `null` when smoothing was disabled. |
| `calc_notes` | array of strings | Human-readable audit notes. Common patterns seen in current data: `"recoil_max window: idx X..Y"` — the index range used to measure recoil; `"piston_suck: ws_max_idx=X, cross_idx=Y"` — indices used for piston suck-in calculation; `"piston_suck: N/A (release crossing at X is after pullout at Y)"` — suck-in was not measurable; `"Seafloor calcs skipped: no Trigger Core/Weight sensor"` — seafloor depth could not be computed. |

---

### Reading `params` in Python

```python
from db_util import get_connection
from sqlalchemy import text

with get_connection() as conn:
    row = conn.execute(
        text("SELECT * FROM sensor_analysis_results WHERE result_id = :rid"),
        {"rid": 2}
    ).fetchone()

params = row.params  # SQLAlchemy auto-decodes JSONB to dict

# Read trip detection threshold
threshold = params.get("trip", {}).get("threshold")

# Read depth calibration regressions
regressions = params.get("depth_offset", {}).get("calib_json", {}).get("regressions", [])
for reg in regressions:
    print(f"{reg['sensor_i']}→{reg['sensor_j']}: R²={reg['r_squared']:.4f}")

# Read calc notes
for note in params.get("calc_notes", []):
    print(note)
```

### Reading `params` in SQL

```sql
-- Trip detection threshold for each result
SELECT result_id, (params->'trip'->>'threshold')::float AS threshold
FROM sensor_analysis_results;

-- Depth calibration R² for the A→B sensor pair
SELECT result_id, reg->>'r_squared' AS r_squared
FROM sensor_analysis_results,
     jsonb_array_elements(params->'depth_offset'->'calib_json'->'regressions') AS reg
WHERE reg->>'sensor_i' = 'A' AND reg->>'sensor_j' = 'B';

-- Rows where seafloor calcs were skipped
SELECT result_id
FROM sensor_analysis_results
WHERE params->'calc_notes' @> '["Seafloor calcs skipped: no Trigger Core/Weight sensor"]';

-- All manual depth offsets for a specific result
SELECT key, value
FROM sensor_analysis_results,
     jsonb_each(params->'depth_offset'->'manual_offsets')
WHERE result_id = 2;
```

---

---

## Table 2: `recoil_analysis_results`

**What it is:** One row per `(core_id, curve_type)` combination. Stores the results of fitting a recoil curve to sensor data using either a **physics-based** model or an **empirical** (curve-fit) model. Re-saving overwrites the existing row for that pair (upsert). The `deployment_params` JSONB stores a full snapshot of deployment configuration at the time of analysis.

**Unique key:** `(core_id, curve_type)`

**Plain English:** Each row answers "what mathematical model best describes how core #X rebounded?" It stores either the physics parameters governing the motion (stiffness, drag, initial velocity) or the shape parameters of a fitted damped oscillation curve — never both at once. The `curve_type` column tells you which set to look at.

---

### Column Reference

| Column | Type | Description |
|---|---|---|
| `id` | integer | Auto-incrementing primary key. |
| `core_id` | integer | Which core this result belongs to. Foreign key → `cores.core_id`. |
| `curve_type` | varchar(32) | Which model was used. Determines which output columns are populated. Typically `"physics"` or `"empirical"`. |
| `deployment_params` | JSONB | Full snapshot of `DeploymentParams` at analysis time. See below. |
| `trip_time_epoch` | float | Unix timestamp (seconds since 1970-01-01 UTC) of the trip event. |
| `fit_end_epoch` | float | Unix timestamp of the end of the fitting window. |
| `saved_at` | timestamptz | When this row was last written. Set to `now()` on every save. |

#### Physics Model Columns
*Populated only for physics model rows. `NULL` for empirical rows.*

| Column | Type | Description |
|---|---|---|
| `e_gpa` | float | Elastic modulus tuning parameter in gigapascals (GPa). Controls simulated sediment stiffness. |
| `c_drag` | float | Drag coefficient (dimensionless). Controls how quickly oscillation is damped by fluid resistance. |
| `v0_ms` | float | Initial velocity of the core at the trip moment, in metres per second (m/s). |
| `peak_displacement_m` | float | Maximum displacement predicted by the model, in metres (m). |
| `peak_time_s` | float | Time after the trip event at which peak displacement occurs, in seconds (s). |
| `k_nm` | float | Spring stiffness parameter in newtons per metre (N/m). |

#### Empirical Model Columns
*Populated only for empirical model rows. `NULL` for physics rows.*

| Column | Type | Description |
|---|---|---|
| `a_m` | float | Amplitude of the fitted damped oscillation, in metres (m). |
| `tau_s` | float | Decay time constant of the fitted envelope, in seconds (s). Larger = slower decay / less damping. |
| `omega_rads` | float | Angular frequency of the fitted oscillation in radians per second (rad/s). Divide by 2π to convert to Hz. |

---

### `deployment_params` JSONB Structure

This column stores a complete serialisation of the `DeploymentParams` dataclass (via `dataclasses.asdict()`) as it existed when the analysis was run. It is a **point-in-time snapshot** and does not update if deployment configuration changes later.

Non-finite float values (`NaN`, `Inf`, `-Inf`) are stored as JSON `null`.

#### Reading in Python

```python
from recoil_results_io import load_results_for_core

results = load_results_for_core(core_id=181)
# Returns a dict keyed by curve_type:
# {
#   "physics":   {"core_id": 181, "e_gpa": 70.1, "v0_ms": 2.3, ..., "deployment_params": {...}},
#   "empirical": {"core_id": 181, "a_m": 0.05, "tau_s": 1.2, ..., "deployment_params": {...}}
# }

physics = results.get("physics")
if physics:
    print(f"Peak displacement: {physics['peak_displacement_m']} m")
    print(f"Deployment params: {physics['deployment_params']}")
```

#### Reading in SQL

```sql
-- Access a deployment parameter field
SELECT core_id, deployment_params->>'sampling_rate_hz' AS sampling_rate
FROM recoil_analysis_results
WHERE curve_type = 'physics';

-- Compare physics vs empirical results for the same core
SELECT
    MAX(CASE WHEN curve_type = 'physics'   THEN peak_displacement_m END) AS physics_peak_m,
    MAX(CASE WHEN curve_type = 'empirical' THEN a_m                 END) AS empirical_amplitude_m
FROM recoil_analysis_results
WHERE core_id = 181;
```

---

---

## Common Gotchas

**`NaN` and `Inf` become `null` in JSON.** Both tables use a custom encoder that converts non-finite floats to JSON `null` before saving. A `null` in a numeric field may mean a failed or undefined computation, not an intentionally missing value.

**`deployment_params` is a point-in-time snapshot.** The blob reflects the `DeploymentParams` as they were when the analysis ran. If configuration changes later, the stored blob will not match. Do not join it against live configuration tables expecting them to agree.

**`params` merges at the top level only.** The `||` PostgreSQL merge operator used by `update_result()` is shallow: it replaces top-level keys wholesale. Passing `{"trip": {"threshold": 0.6}}` replaces the *entire* existing `trip` object, not just the threshold field. Always reconstruct the full section when updating.

**Sensor column names encode metadata.** The strings stored in `weight_stand_col`, `release_col`, `trigger_col`, `label_mapping`, `manual_offsets`, etc. follow the pattern `"{Role}_{SerialOrFilename}_{DateTime}_Depth (m)"`. The same physical sensor will appear under a different column name in each deployment file.

**`calc_notes` is the audit trail for skipped calculations.** If a result column is `NULL`, the corresponding `calc_notes` entry will usually explain why (e.g. `"piston_suck: N/A"`, `"Seafloor calcs skipped: no Trigger Core/Weight sensor"`). Always check `calc_notes` before assuming a calculation failed silently.

**`sync_status = 'pending'` is the default.** All rows created on the ship start as `'pending'`. The `central_id` column will be `NULL` until the row is synced to the shore-side database.