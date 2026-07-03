# Dredge App (database-integrated)

Interactive viewer for dredge deployments: a USBL location map linked to
high-frequency time-series plots (Star-Oddi sensor + winch data), with brush
selection, zone annotation, and CSV / GeoPackage export.

This is the "full" dredge app (formerly `dredge_app_geo.py` in the standalone
`dredge_data` repo) adapted to pull its data **directly from the sediment_app
PostgreSQL database** instead of loading pre-built CSV files. It replicates the
CSV-building pipeline of `usbl_sensor_winch_export.py` in memory.

## Running

From the repository root (so `db_util` and `config` are importable):

```bash
python -m dredge_app
```

## Workflow

1. Pick a **Cruise** — only cruises that have a dredge *and* USBL data are listed.
2. Pick a **Dredge** — the app then:
   - computes the deployment window from `cores.date` + `time_launched` /
     `time_recovered` (with midnight-rollover handling);
   - loads and merges the dredge's Star-Oddi sensor files;
   - loads the cruise's USBL files that overlap the window;
   - loads the cruise's winch files that overlap the window;
   - outer-merges sensor + winch into the time-series frame and truncates both
     the USBL and sensor frames to the deployment window.
3. Use the map + time-series exactly as before: brush-select a time range,
   watch the corresponding USBL fixes highlight, save named zone annotations,
   and export to CSV and/or GeoPackage.

`File ▸ Load USBL CSV… / Load Sensor CSV…` remain available as a fallback for
working from CSV files without a database connection.

## Data source

- **Database connection** is reused from `sediment_app/db_util.py`
  (`get_connection`).
- **File paths** are resolved via `sediment_app/config.py` (`get_full_path`,
  rooted at `FILE_STORAGE_ROOT` / `ROOT_DIRECTORY`).
- File parsing (USBL, Star-Oddi `.dat`/`.acc`, winch) is reimplemented
  Streamlit-free in `dredge_app/persistence/file_parsers.py`, mirroring
  `sediment_app/utils.py`.

## Layout

```
dredge_app/
  __main__.py                     # python -m dredge_app entry point
  gui/main_window.py              # DredgeApp window (viewer + dropdowns)
  persistence/
    database_loader.py            # DredgeDatabaseLoader (cruise/dredge queries + pipeline)
    file_parsers.py               # st-free USBL / Star-Oddi / winch parsers
  requirements.txt
```

## Dependencies

See `requirements.txt`. GeoPackage export requires the optional `geopandas` /
`shapely` extras; without them the app runs with CSV export only (the
GeoPackage checkbox is disabled).
