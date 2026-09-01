# Dragognosificator

Interactive viewer for dredge deployments: a USBL location map linked to
high-frequency time-series plots (Star-Oddi sensor + winch data), with brush
selection, zone annotation, and CSV / GeoPackage export — plus built-in
metadata entry and file uploads, so it runs entirely on its own.

All metadata lives in a per-project **SQLite** database and all data files are
**copied into the project folder**, so a project is a single portable
directory. No PostgreSQL server or Streamlit apps required.

## What the user needs (uncompiled / launcher version)

| Requirement | Details |
|---|---|
| **Python** | **3.10 or newer** (3.11 / 3.12 recommended) |
| **PATH** | The `python` command must work from a Command Prompt / terminal. On Windows, tick **"Add python.exe to PATH"** during installation from [python.org](https://www.python.org/downloads/). If `python` is not found, the launcher tries `py -3`. |
| **Internet** | Only on **first run** of `run_windows.bat` / `run_mac_linux.sh`, while pip installs the requirements into a dedicated `dredge_standalone/venv/`. After that, offline use is fine. |
| **Linux extra** | On Debian/Ubuntu, install `python3-venv` once if venv creation fails (`sudo apt install python3-venv`). |

The **compiled `.exe`** (`Dragognosificator.exe`) needs **none of the above** on the target machine — it is a self-contained double-clickable file (~100–150 MB). Build it on Windows with `packaging/build_windows.bat`.

### Uncompiled vs compiled — which to share?

**Uncompiled (launcher + source)** is the better choice when you expect to **add winch formats or other tweaks**: ship the `dredge_standalone` folder (or a zip of the public repo). Users double-click `run_windows.bat`; you edit `formats.py` (winch presets) and push an update — they pull / re-download and run again (delete `dredge_standalone/venv` only if dependencies changed).

**Compiled `.exe`** is for recipients who should not install Python. Rebuild and re-share the exe whenever you change the code.

## Installation & running

**Easiest:** double-click `run_windows.bat` (Windows) or run `./run_mac_linux.sh` (macOS/Linux) inside this folder. On first run it creates a dedicated virtual environment *inside this folder* (`venv/`) and installs requirements automatically; after that it launches with no console window. If startup fails, the window stays open and shows the actual error. Runtime crashes are logged to `dragognosificator_error.log` in your temp folder.

**Manual:**

```bash
pip install -r requirements.txt
```

then, from the directory *containing* the `dredge_standalone` folder:

```bash
python -m dredge_standalone
```

GeoPackage export is **built in** (stdlib `sqlite3` + `pyproj`) — no geopandas / GDAL required.

## Building a single-file executable

On **Windows** (produces `dist\Dragognosificator.exe`):

```bat
dredge_standalone\packaging\build_windows.bat
```

On **macOS / Linux**:

```bash
chmod +x dredge_standalone/packaging/build_mac_linux.sh
./dredge_standalone/packaging/build_mac_linux.sh
```

Or manually:

```bash
pip install -r dredge_standalone/requirements.txt pyinstaller
pyinstaller dredge_standalone/packaging/dragognosificator.spec
```

The one-file bundle self-extracts on launch (a few extra seconds at startup); no Python needed on the target machine.

## Workflow

1. **File ▸ New Project…** — pick an empty folder. The app creates:

   ```
   MyProject/
     dredge_data.sqlite
     sensor_data/<cruise>/
     winch_data/<cruise>/
     usbl_data/<cruise>/
   ```

2. **Data Manager tab** — cruises, dredge deployments (name, start/end UTC, USBL distance), sensor / winch / USBL file registration. Winch presets live in **`formats.py`** — add new ships there. Sensor location is a free-text field.

3. **Viewer tab** — cruise + dredge dropdowns, linked map/time-series, brush annotations (persisted per dredge), export.

## Layout

```
dredge_standalone/
  __main__.py
  formats.py                  # winch ship presets — edit this to add formats
  run_windows.bat
  run_mac_linux.sh
  gui/
  persistence/
    gpkg.py                   # built-in GeoPackage writer
  packaging/
    dragognosificator.spec
    build_windows.bat
    build_mac_linux.sh
  requirements.txt
```
