# Dredge App (standalone)

Interactive viewer for dredge deployments: a USBL location map linked to
high-frequency time-series plots (Star-Oddi sensor + winch data), with brush
selection, zone annotation, and CSV / GeoPackage export — plus built-in
metadata entry and file uploads, so it runs entirely on its own.

All metadata lives in a per-project **SQLite** database and all data files are
**copied into the project folder**, so a project is a single portable
directory: zip it, move it, share it, and everything (files, metadata,
annotations) travels together. No PostgreSQL server or other external
infrastructure is required.

## Installation

Requires Python 3.10+.

```bash
pip install -r requirements.txt
```

Optionally, for GeoPackage export:

```bash
pip install geopandas shapely fiona
```

## Running

From the directory *containing* the `dredge_standalone` folder:

```bash
python -m dredge_standalone
```

## Workflow

1. **File ▸ New Project…** — pick an empty folder. The app creates:

   ```
   MyProject/
     dredge_data.sqlite     # metadata + annotations
     sensor_data/<cruise>/  # copied-in Star-Oddi files
     winch_data/<cruise>/   # copied-in winch logs
     usbl_data/<cruise>/    # copied-in USBL files
   ```

   The last project is reopened automatically on the next launch
   (File ▸ Recent Projects lists earlier ones).

2. **Data Manager tab** — enter metadata and register files:
   - **Cruise**: create one per cruise (multiple cruises can coexist in one
     project).
   - **Dredge deployments**: name, start/end datetimes (UTC), optional USBL
     distance and notes. The start/end window is what the viewer uses to
     truncate all data sources.
   - **Sensor (Star-Oddi)**: `.dat` / `.acc` files, assigned to a specific
     dredge, with sensor location and measurement types.
   - **Winch**: any delimited winch log. Pick a ship format preset
     (Sikuliaq, Armstrong, Atlantis, Revelle, Thompson, Kilo Moana, …) or
     configure delimiter / header lines / column names / datetime code by
     hand, preview the raw rows, then **Test Parse** — saving is only enabled
     after a successful test, and the test uses the exact parser the viewer
     uses later. The file's start/end times are stored for overlap matching.
   - **USBL**: `$PSONLLD` files. Start/end times are auto-detected (with
     midnight-rollover handling) and previewed before saving.

   Winch and USBL files are **pooled per cruise** and matched to dredges by
   time overlap at load time — register a day-long file once and every dredge
   whose window overlaps it picks it up. Sensor files belong to one dredge.

3. **Viewer tab** — pick a cruise and a dredge; the app merges the dredge's
   Star-Oddi files with overlapping winch data into the time-series frame,
   loads overlapping USBL fixes, truncates everything to the deployment
   window, and displays the linked map + time-series plots. Brush-select a
   time range, watch the corresponding USBL fixes highlight, and save named
   zone annotations.

   **Annotations are persisted** in the project database per dredge — close
   the app, reopen the project, reselect the dredge, and they're back.

4. **Export** — CSV (annotation metadata + annotated USBL), CSV (merged
   sensor & winch time series), and/or GeoPackage with UTM point geometry.

`File ▸ Load USBL CSV… / Load Sensor CSV…` remain available for viewing
pre-built CSV files without a project (annotations are session-only there).

## Layout

```
dredge_standalone/
  __main__.py                 # python -m dredge_standalone entry point
  formats.py                  # ship winch format presets + form constants
  gui/
    main_window.py            # project handling + tabs
    data_manager.py           # metadata entry & file registration page
    winch_dialog.py           # winch format/preview/test-parse dialog
    viewer.py                 # map + time-series viewer page
  persistence/
    project.py                # ProjectStore: SQLite schema + file copy-in
    loader.py                 # per-dredge dataset assembly pipeline
    file_parsers.py           # USBL / Star-Oddi / winch parsers
  requirements.txt
```

## Data format notes

- All datetimes are treated as **UTC** throughout.
- USBL files must contain the date as `YYYYMMDD` in the filename
  (e.g. `PSONLLD_20251018_000000.txt`); per-row times come from the
  `$PSONLLD` records and midnight rollover within a file is corrected.
- Star-Oddi `.dat` files use comma decimal separators and `DD.MM.YYYY`
  datetimes; `.acc` acceleration files are also supported.
- Winch parsing settings (delimiter, header lines, columns, datetime
  expression, numeric columns) are stored per file in the database, so files
  from different ships can coexist in one cruise.
