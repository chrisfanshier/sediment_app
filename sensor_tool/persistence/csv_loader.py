"""
CSV loader - handles reading sensor CSV files with multiple encoding
fallbacks and format detection.

Depth columns retain their original names from the CSV throughout
the application. No renaming to Sensor_A/B/C/D occurs.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import numpy as np

from ..domain.models.sensor_data import SensorData

# Encodings to try in order
ENCODINGS = ['utf-8', 'utf-8-sig', 'cp1252', 'iso-8859-1', 'latin-1']


class CSVLoader:
    """Load sensor data from CSV files into SensorData instances."""

    @staticmethod
    def load_export_csv(
        file_path: str | Path,
        datetime_col: str = 'datetime',
    ) -> SensorData:
        """
        Load a Sediment App batch-export CSV.

        These files have comment lines starting with '#' and a header row
        starting with 'datetime'. Depth columns contain 'Depth' in the name.
        Columns keep their original names.
        """
        file_path = Path(file_path)

        lines = CSVLoader._read_lines(file_path)

        core_title = ''
        metadata = {}
        skiprows = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('# Core:'):
                core_title = stripped.split(':', 1)[1].strip()
            elif stripped.startswith('# Core Type:'):
                metadata['core_type'] = stripped.split(':', 1)[1].strip()
            elif stripped.startswith('# Core length:'):
                try:
                    metadata['core_length'] = float(stripped.split(':', 1)[1].strip())
                except ValueError:
                    pass
            elif stripped.startswith('# Trigger core length:'):
                try:
                    metadata['trigger_core_length'] = float(stripped.split(':', 1)[1].strip())
                except ValueError:
                    pass
            elif stripped.startswith('# Trigger line length:'):
                try:
                    metadata['trigger_line_length'] = float(stripped.split(':', 1)[1].strip())
                except ValueError:
                    pass
            elif stripped.startswith('# Scope:'):
                try:
                    metadata['scope'] = float(stripped.split(':', 1)[1].strip())
                except ValueError:
                    pass
            elif stripped.startswith('# Trip detected at:'):
                try:
                    val = stripped.split(':', 1)[1].strip()
                    if '(' in val:
                        val = val[:val.index('(')].strip()
                    metadata['trip_time'] = val
                except Exception:
                    pass
            if stripped.startswith(datetime_col):
                skiprows = i
                break

        df = CSVLoader._read_csv_with_encoding(file_path, skiprows=skiprows)
        df.columns = df.columns.str.strip()

        if datetime_col not in df.columns:
            raise ValueError(f"No '{datetime_col}' column found in {file_path.name}")

        df[datetime_col] = pd.to_datetime(df[datetime_col], errors='coerce')

        # Find depth columns - keep original names
        depth_cols = [col for col in df.columns if 'Depth' in col]
        if not depth_cols:
            raise ValueError(f"No depth columns found in {file_path.name}")

        return SensorData(
            df=df,
            datetime_col=datetime_col,
            depth_columns=depth_cols,
            source_file=file_path.name,
            core_title=core_title,
            metadata=metadata,
        )

    @staticmethod
    def load_sensor_csv(
        file_path: str | Path,
        sensor_patterns: list[str],
        datetime_col: str = 'datetime',
        skip_rows: int = 0,
    ) -> SensorData:
        """
        Load a CSV file using sensor name patterns to find depth columns.

        This is for the format where columns are identified by matching
        sensor serial numbers (e.g., '230405', '230406').
        Columns keep their original names.
        """
        file_path = Path(file_path)

        df = None
        for encoding in ENCODINGS:
            try:
                df = pd.read_csv(file_path, comment='#', encoding=encoding)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
            except Exception:
                try:
                    df = pd.read_csv(file_path, skiprows=skip_rows, encoding=encoding)
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue
                except Exception:
                    try:
                        df = pd.read_csv(file_path, encoding=encoding)
                        break
                    except (UnicodeDecodeError, UnicodeError):
                        continue

        if df is None:
            raise ValueError(f"Could not load {file_path.name} with any common encoding")

        # Find depth columns by matching patterns - keep original names
        depth_cols = []
        for pattern in sensor_patterns:
            matches = [col for col in df.columns if pattern in col and 'Depth' in col]
            if not matches:
                raise ValueError(
                    f"Could not find column for sensor pattern: {pattern}\n"
                    f"Available columns: {list(df.columns)}"
                )
            depth_cols.append(matches[0])

        # Keep only datetime + depth columns, drop rows where all depths NaN
        df_depth = df[[datetime_col] + depth_cols].copy()
        df_depth = df_depth.dropna(subset=depth_cols, how='all')

        return SensorData(
            df=df_depth,
            datetime_col=datetime_col,
            depth_columns=depth_cols,
            source_file=file_path.name,
        )

    @staticmethod
    def load_raw_csv(
        file_path: str | Path,
        datetime_col: str = 'datetime',
    ) -> tuple[pd.DataFrame, str, list[str]]:
        """
        Load a CSV with minimal processing - returns the raw DataFrame
        plus detected metadata. Useful when full control is needed.

        Returns:
            (DataFrame, core_title, depth_column_names)
        """
        file_path = Path(file_path)
        lines = CSVLoader._read_lines(file_path)

        core_title = ''
        skiprows = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('# Core:'):
                core_title = stripped.split(':', 1)[1].strip()
            if stripped.startswith(datetime_col):
                skiprows = i
                break

        df = CSVLoader._read_csv_with_encoding(file_path, skiprows=skiprows)
        df.columns = df.columns.str.strip()

        depth_cols = [col for col in df.columns if 'Depth' in col]

        return df, core_title, depth_cols

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_lines(file_path: Path) -> list[str]:
        for enc in ENCODINGS:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    return f.readlines()
            except (UnicodeDecodeError, UnicodeError):
                continue
        raise ValueError(f"Could not read {file_path.name} with any common encoding")

    @staticmethod
    def _read_csv_with_encoding(file_path: Path, skiprows: int = 0) -> pd.DataFrame:
        for enc in ENCODINGS:
            try:
                return pd.read_csv(file_path, skiprows=skiprows, encoding=enc)
            except (UnicodeDecodeError, UnicodeError):
                continue
        raise ValueError(f"Could not load {file_path.name} with any common encoding")
