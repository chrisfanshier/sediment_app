"""
File parsers for the standalone dredge app.

These mirror the parsing logic in the sediment_app ``utils.py`` but are fully
self-contained (no Streamlit, no database).  Diagnostics are surfaced via the
``logging`` module.

Three source formats are handled:
    * USBL  ``$PSONLLD``-derived CSV files  -> :func:`load_usbl_file`
    * Star-Oddi ``.dat`` / ``.acc`` files   -> :func:`process_star_oddi_data`
    * Winch ``.dat`` files (custom formats)  -> :func:`parse_winch_dat`

:func:`parse_usbl_first_last` additionally extracts the first/last timestamps
from a USBL file (with midnight-rollover handling) for registration metadata.
"""
from __future__ import annotations

import io
import logging
import os
import re
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# USBL
# ---------------------------------------------------------------------------

# Column layout of the raw USBL CSV (no header row).
_USBL_COLUMNS = [
    "ID", "utc_time", "beacon_name", "fix_status", "latitude_deg", "longitude_deg",
    "depth_m", "hor_err_major", "hor_err_minor", "hor_err_dir",
    "depth_error", "reserved_1", "reserved_2", "reserved_3", "checksum",
]

# Columns kept on the returned frame (datetime first, as a column not an index).
_USBL_KEEP = [
    "datetime", "latitude_deg", "longitude_deg", "depth_m", "beacon_name",
    "fix_status", "hor_err_major", "hor_err_minor", "hor_err_dir", "depth_error",
]


def load_usbl_file(file_path: str) -> Optional[pd.DataFrame]:
    """Load a single USBL file and return a DataFrame with a ``datetime`` column.

    The file date is taken from the filename (``PSONLLD_YYYYMMDD_HHMMSS.txt`` ->
    ``YYYYMMDD``) and combined with the per-row ``utc_time`` (``HHMMSS.f``).
    Midnight rollover within a single file is corrected by shifting the
    pre-rollover rows back one day.

    Returns ``None`` on failure (with the error logged).
    """
    try:
        df = pd.read_csv(
            file_path,
            header=None,
            names=_USBL_COLUMNS,
            dtype={"utc_time": str},
        )

        file_name = Path(file_path).name
        # e.g. "PSONLLD_20251018_000000.txt" -> "20251018"
        date_str = file_name.split("_")[1]

        df["datetime"] = pd.to_datetime(
            date_str + " " + df["utc_time"].astype(str),
            format="%Y%m%d %H%M%S.%f",
            utc=True,
        )

        # Handle midnight rollover: if the clock time decreases at some point,
        # every row before the rollover belongs to the previous day.
        time_values = pd.to_datetime(df["utc_time"], format="%H%M%S.%f", errors="coerce")
        if len(time_values) > 1:
            first_time = time_values.iloc[0]
            last_time = time_values.iloc[-1]
            if not pd.isna(first_time) and not pd.isna(last_time):
                if first_time.time() > last_time.time():
                    rollover_idx = (time_values.diff() < pd.Timedelta(0)).idxmax()
                    if rollover_idx > 0:
                        df.loc[: rollover_idx - 1, "datetime"] -= pd.Timedelta(days=1)

        usbl_df = df[_USBL_KEEP].copy()
        return usbl_df

    except Exception as exc:  # noqa: BLE001 - surface as log, return None
        logger.error("Error loading USBL file %s: %s", file_path, exc)
        return None


def parse_usbl_first_last(file_path: str) -> tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """Read the first and last ``$PSONLLD`` time tokens from a USBL file.

    Returns ``(first_dt, last_dt)`` as naive pandas Timestamps anchored to the
    ``YYYYMMDD`` date found in the filename, or ``(None, None)`` on failure.
    If the first time-of-day is later than the last, the first rows are
    assumed to belong to the previous day (midnight rollover).
    """
    try:
        m = re.search(r"(\d{8})", Path(file_path).name)
        if not m:
            return None, None
        file_date = pd.to_datetime(m.group(1), format="%Y%m%d", errors="coerce")
        if pd.isna(file_date):
            return None, None

        time_re = re.compile(r"\$PSONLLD,(\d{6}(?:\.\d+)?)")
        first_s = last_s = None

        with open(file_path, "r", encoding="latin1", errors="replace") as fh:
            for line in fh:
                mm = time_re.search(line)
                if not mm:
                    continue
                t = mm.group(1)
                if first_s is None:
                    first_s = t
                last_s = t

        if not first_s or not last_s:
            return None, None

        def hhmmss_to_td(s: str) -> pd.Timedelta:
            if "." in s:
                main, frac = s.split(".", 1)
                try:
                    frac = float("0." + frac)
                except ValueError:
                    frac = 0.0
            else:
                main, frac = s, 0.0
            main = main.zfill(6)
            hh = int(main[:-4]) if len(main) > 4 else 0
            mi = int(main[-4:-2])
            ss = int(main[-2:])
            return pd.Timedelta(seconds=hh * 3600 + mi * 60 + ss + frac)

        td_first = hhmmss_to_td(first_s)
        td_last = hhmmss_to_td(last_s)

        first_dt = pd.Timestamp(file_date) + td_first
        last_dt = pd.Timestamp(file_date) + td_last
        if td_first > td_last:
            first_dt -= pd.Timedelta(days=1)

        return first_dt, last_dt
    except Exception as exc:  # noqa: BLE001
        logger.error("Error scanning USBL file %s: %s", file_path, exc)
        return None, None


# ---------------------------------------------------------------------------
# Star-Oddi
# ---------------------------------------------------------------------------

def parse_staroddi_dat(file_path: str) -> Optional[pd.DataFrame]:
    """Parse a Star-Oddi ``.dat`` file into a standardized DataFrame.

    Returns columns: ``datetime`` plus pressure/depth/temperature and tilt
    channels.  Numbers use a comma decimal separator in the source files.
    """
    try:
        with open(file_path, "rb") as fh:
            lines = fh.read().decode("latin1").splitlines()

        data_start = next(i for i, line in enumerate(lines) if line and line[0].isdigit())
        colnames = ["index", "datetime", "temp", "press", "tilt_x", "tilt_y", "tilt_z", "EAL", "roll"]

        df = pd.read_csv(
            io.StringIO("\n".join(lines[data_start:])),
            sep="\t",
            names=colnames,
            header=None,
            na_values="____",
            decimal=",",
        )

        df["datetime"] = df["datetime"].astype(str).str.replace(",", ".", regex=False)
        for col in ["temp", "press", "tilt_x", "tilt_y", "tilt_z", "EAL", "roll"]:
            df[col] = df[col].astype(str).str.replace(",", ".", regex=False)
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["datetime"] = pd.to_datetime(
            df["datetime"], format="%d.%m.%Y %H:%M:%S.%f", errors="coerce"
        )

        return pd.DataFrame({
            "datetime": df["datetime"],
            "Pressure (dbar)": df["press"],
            "Sea Pressure (dbar)": df["press"],
            "Depth (m)": df["press"],
            "Temperature (°C)": df["temp"],
            "Tilt X": df["tilt_x"],
            "Tilt Y": df["tilt_y"],
            "Tilt Z": df["tilt_z"],
            "EAL": df["EAL"],
            "Roll": df["roll"],
        })

    except Exception as exc:  # noqa: BLE001
        logger.error("Error parsing Star-Oddi .dat file %s: %s", file_path, exc)
        return None


def parse_staroddi_acc(file_path: str) -> Optional[pd.DataFrame]:
    """Parse a Star-Oddi ``.acc`` (acceleration) file into a standardized DataFrame."""
    try:
        with open(file_path, "rb") as fh:
            lines = fh.read().decode("latin1").splitlines()

        data_start = next(i for i, line in enumerate(lines) if line and line[0].isdigit())
        colnames = ["rownum", "datetime", "g", "x_acc", "y_acc", "z_acc"]

        df = pd.read_csv(
            io.StringIO("\n".join(lines[data_start:])),
            sep="\t",
            names=colnames,
            header=None,
            na_values="____",
        )

        df["datetime"] = df["datetime"].astype(str).str.replace(",", ".", regex=False)
        df["datetime"] = pd.to_datetime(
            df["datetime"], format="%d.%m.%Y %H:%M:%S.%f", errors="coerce"
        )
        for col in ["g", "x_acc", "y_acc", "z_acc"]:
            df[col] = df[col].astype(str).str.replace(",", ".", regex=False)
            df[col] = pd.to_numeric(df[col], errors="coerce")

        return pd.DataFrame({
            "datetime": df["datetime"],
            "X_Acceleration": df["x_acc"],
            "Y_Acceleration": df["y_acc"],
            "Z_Acceleration": df["z_acc"],
            "Total_G": df["g"],
        })

    except Exception as exc:  # noqa: BLE001
        logger.error("Error parsing Star-Oddi .acc file %s: %s", file_path, exc)
        return None


def process_star_oddi_data(full_path: str) -> Optional[pd.DataFrame]:
    """Dispatch a Star-Oddi file to the correct parser based on extension.

    Unlike the Streamlit version this takes an already-resolved absolute path.
    Returns ``None`` for missing files or unsupported extensions.
    """
    try:
        if not os.path.exists(full_path):
            logger.error("Star-Oddi file not found: %s", full_path)
            return None

        lower = full_path.lower()
        if lower.endswith(".dat"):
            return parse_staroddi_dat(full_path)
        if lower.endswith(".acc"):
            return parse_staroddi_acc(full_path)

        logger.error("Unsupported Star-Oddi file format: %s", full_path)
        return None

    except Exception as exc:  # noqa: BLE001
        logger.error("Error processing Star-Oddi file %s: %s", full_path, exc)
        return None


# ---------------------------------------------------------------------------
# Winch
# ---------------------------------------------------------------------------

def parse_winch_dat(file_path: str, parsing_settings: dict) -> Optional[pd.DataFrame]:
    """Parse a winch ``.dat`` file using per-file settings.

    ``parsing_settings`` mirrors the entries in ``config.WINCH_FORMATS``:
        - ``delimiter`` (str, default ",")
        - ``header_lines`` (int, default 0)
        - ``columns`` (list[str], optional)
        - ``datetime_code`` (str: python expression producing the datetime col)
        - ``numeric_columns`` (list[str], optional)

    Returns a DataFrame with a ``datetime`` column, or ``None`` on failure.
    """
    try:
        delimiter = parsing_settings.get("delimiter", ",")
        header_lines = parsing_settings.get("header_lines", 0)
        columns = parsing_settings.get("columns", None)
        datetime_code = parsing_settings.get("datetime_code", "pd.to_datetime(df['datetime'])")
        numeric_columns = parsing_settings.get("numeric_columns", [])

        df = pd.read_csv(
            file_path,
            delimiter=delimiter,
            skiprows=header_lines,
            header=None if columns else 0,
            names=columns if columns else None,
            low_memory=False,
            on_bad_lines="skip",
        )

        # The datetime_code expressions reference a local ``df`` and ``pd``.
        exec(f"df['datetime'] = {datetime_code}", {"df": df, "pd": pd})  # noqa: S102
        if pd.api.types.is_datetime64_any_dtype(df["datetime"]):
            if getattr(df["datetime"].dt, "tz", None) is not None:
                df["datetime"] = df["datetime"].dt.tz_localize(None)

        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.strip(), errors="coerce")

        return df

    except Exception as exc:  # noqa: BLE001
        logger.error("Error parsing winch file %s: %s", file_path, exc)
        return None
