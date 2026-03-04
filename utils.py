import os
import re
import pandas as pd
import streamlit as st
import numpy as np
import io  # Add this missing import
from pyrsktools import RSK
from db_util import get_connection
from db_util import get_dynamic_fields_metadata
from config import get_full_path  # Import the utility function for constructing full paths
from datetime import time
from pathlib import Path
from pyproj import Transformer
from shapely.affinity import rotate, scale, translate
from shapely.geometry import Point

def parse_mscl_out_file(relative_path):
    """Parse an MSCL .out file and return a Pandas DataFrame."""
    try:
        # Construct the full file path using the relative path
        full_path = get_full_path(relative_path)

        # Open the file from the specified path
        with open(full_path, "r", encoding="utf-8") as file:
            lines = file.readlines()

        # Find the header line
        header_index = None
        for i, line in enumerate(lines):
            if line.strip().startswith("SB DEPTH"):
                header_index = i
                break
        if header_index is None:
            st.error("Could not find data header in file.")
            return None

        # Extract the header and data
        header_line = lines[header_index]
        header = re.findall(r"[A-Za-z0-9\^\-\(\)\/\s]+?(?=\s{2,}|\t|$)", header_line.strip())
        data_lines = lines[header_index + 2:]
        data = []
        for line in data_lines:
            if not line.strip():
                continue
            values = re.split(r'\s{2,}|\t', line.strip())
            while len(values) < len(header):
                values.append(None)
            data.append(values[:len(header)])

        # Create a DataFrame
        df = pd.DataFrame(data, columns=header)
        for col in df.columns:
            try:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            except Exception as e:
                st.warning(f"Could not convert column '{col}' to numeric: {e}")
        df.dropna(how="all", inplace=True)
        return df

    except FileNotFoundError:
        st.error(f"File not found: {full_path}")
        return None
    except Exception as e:
        st.error(f"An error occurred while parsing the file: {e}")
        return None

def process_rsk_data(relative_path):
    """Process an RSK file and return a DataFrame."""
    try:
        # Construct the full file path using the relative path
        full_path = get_full_path(relative_path)

        # Validate the file path
        if not os.path.exists(full_path):
            st.error(f"RSK file not found at path: {full_path}")
            return None

        # Process the RSK file
        with RSK(full_path) as rsk:
            rsk.open()
            rsk.readdata()
            rsk.deriveseapressure()
            rsk.derivedepth(latitude=45.0)
            data_dict = {
                "Timestamp": rsk.data["timestamp"],
                "Pressure (dbar)": rsk.data["pressure"],
                "Sea Pressure (dbar)": rsk.data["sea_pressure"],
                "Depth (m)": rsk.data["depth"],
            }
            df = pd.DataFrame(data_dict)
            return df

    except FileNotFoundError:
        st.error(f"RSK file not found at path: {full_path}")
        return None
    except OSError as e:
        st.error(f"Error processing RSK file: {e}")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
        return None

def downsample_data(df, max_points=1000):
    """Downsample a DataFrame to a maximum number of points."""
    if df is not None and len(df) > max_points:
        indices = np.linspace(0, len(df) - 1, max_points, dtype=int)
        return df.iloc[indices]
    return df

def map_data_type_to_input(data_type):
    """
    Map database column data types to Streamlit input types.
    """
    if data_type in ["integer", "bigint", "smallint"]:
        return {"input_type": "integer", "step": 1, "format": "%d"}
    elif data_type in ["real", "double precision", "numeric", "decimal"]:
        return {"input_type": "float", "step": 0.01, "format": "%.2f"}
    elif data_type in ["character varying", "text"]:
        return {"input_type": "text"}
    elif data_type in ["boolean"]:
        return {"input_type": "boolean"}
    elif data_type in ["date"]:
        return {"input_type": "date"}
    elif data_type in ["time without time zone", "time with time zone"]:
        return {"input_type": "time"}
    else:
        return {"input_type": "text"}  # Default to text input

def render_dynamic_fields_from_metadata(core_type_id, existing_values=None):
    """
    Render dynamic fields based on metadata from the database.
    
    Args:
        core_type_id: The core type ID to get fields for
        existing_values: Optional dict of existing field values to pre-populate
    """
    # Define units for dynamic fields
    field_units = {
        'core_length': 'feet',
        'trigger_line_length': 'feet',
        'trigger_core_length': 'feet',
        'scope': 'feet',
        'barrel_diameter': 'inches',
        'liner_diameter': 'inches',
        'pig_weights': 'quantity',
        'vibracorer_model': None  # No units for model names
    }
    
    # Fetch dynamic fields metadata
    dynamic_fields = get_dynamic_fields_metadata(core_type_id) or []  # Ensure it's a list, even if None is returned

    dynamic_field_values = {}
    
    # Use existing values if provided, otherwise empty dict
    existing = existing_values or {}

    # Render input fields based on the metadata
    for field in dynamic_fields:
        # Clean up field names for display and add units if applicable
        field_name = field.replace("_", " ").capitalize()
        unit = field_units.get(field)
        if unit:
            field_name = f"{field_name} ({unit})"
        
        # Get existing value for this field
        existing_value = existing.get(field, None)

        # Map the data type to Streamlit input type
        input_metadata = map_data_type_to_input(field)

        # Render inputs dynamically with existing values
        if input_metadata["input_type"] == "integer":
            default_value = int(existing_value) if existing_value is not None else 0
            dynamic_field_values[field] = st.number_input(
                field_name, 
                value=default_value,
                min_value=0, 
                step=input_metadata["step"], 
                format=input_metadata["format"], 
                help="Leave blank for NULL"
            )
            # Convert 0 to None if it was originally None
            if existing_value is None and dynamic_field_values[field] == 0:
                dynamic_field_values[field] = None
                
        elif input_metadata["input_type"] == "float":
            default_value = float(existing_value) if existing_value is not None else 0.0
            dynamic_field_values[field] = st.number_input(
                field_name, 
                value=default_value,
                min_value=0.0, 
                step=input_metadata["step"], 
                format=input_metadata["format"], 
                help="Leave blank for NULL"
            )
            # Convert 0.0 to None if it was originally None
            if existing_value is None and dynamic_field_values[field] == 0.0:
                dynamic_field_values[field] = None
                
        elif input_metadata["input_type"] == "text":
            default_value = str(existing_value) if existing_value is not None else ""
            dynamic_field_values[field] = st.text_input(
                field_name, 
                value=default_value,
                placeholder="Enter value or leave blank for NULL"
            )
            
        elif input_metadata["input_type"] == "boolean":
            default_value = bool(existing_value) if existing_value is not None else False
            dynamic_field_values[field] = st.checkbox(f"{field_name}", value=default_value)
            
        elif input_metadata["input_type"] == "date":
            # Handle date existing values
            if existing_value is not None:
                dynamic_field_values[field] = st.date_input(f"{field_name}", value=existing_value)
            else:
                dynamic_field_values[field] = st.date_input(f"{field_name}")
                
        elif input_metadata["input_type"] == "time":
            # Handle time existing values
            if existing_value is not None:
                dynamic_field_values[field] = st.time_input(f"{field_name}", value=existing_value)
            else:
                dynamic_field_values[field] = st.time_input(f"{field_name}")
        else:
            default_value = str(existing_value) if existing_value is not None else ""
            dynamic_field_values[field] = st.text_input(field_name, value=default_value)

    return dynamic_field_values

# Custom Time Input Function
def custom_time_input(label, default=""):
    time_str = st.text_input(label, value=default, max_chars=5, placeholder="HH:MM")
    if not time_str.strip():  # If the input is blank
        return None
    time_pattern = re.compile(r"^(2[0-3]|[01]?[0-9]):([0-5]?[0-9])$")  # Matches HH:MM format
    if time_pattern.match(time_str):
        hours, minutes = map(int, time_str.split(":"))
        return time(hours, minutes)
    else:
        st.warning(f"Invalid time format for '{label}'. Please use HH:MM (e.g., 14:30).")
        return None
    
def parse_staroddi_dat(file_path):
    """Parse Star Oddi .dat file and return DataFrame compatible with RBR plotting functions"""
    try:
        with open(file_path, 'rb') as file:
            lines = file.read().decode("latin1").splitlines()
        
        data_start = next(i for i, line in enumerate(lines) if line and line[0].isdigit())
        colnames = ["index", "datetime", "temp", "press", "tilt_x", "tilt_y", "tilt_z", "EAL", "roll"]
        
        df = pd.read_csv(
            io.StringIO('\n'.join(lines[data_start:])),
            sep="\t",
            names=colnames,
            header=None,
            na_values="____",
            decimal=",",
        )
        
        # Clean up datetime and numeric columns
        df["datetime"] = df["datetime"].str.replace(",", ".", regex=False)
        for col in ["temp", "press", "tilt_x", "tilt_y", "tilt_z", "EAL", "roll"]:
            df[col] = df[col].astype(str).str.replace(",", ".", regex=False)
            df[col] = pd.to_numeric(df[col], errors="coerce")
        
        df["datetime"] = pd.to_datetime(df["datetime"], format="%d.%m.%Y %H:%M:%S.%f", errors="coerce")
        
        # Standardize to match RBR format for plotting compatibility + include all Star Oddi columns
        standardized_df = pd.DataFrame({
            "Timestamp": df["datetime"],
            "Pressure (dbar)": df["press"],  # Star Oddi pressure
            "Sea Pressure (dbar)": df["press"],  # Use same for sea pressure 
            "Depth (m)": df["press"],  # Star Oddi press column represents depth
            "Temperature (°C)": df["temp"],  # Include temperature
            # Add all Star Oddi specific columns
            "Tilt X": df["tilt_x"],
            "Tilt Y": df["tilt_y"], 
            "Tilt Z": df["tilt_z"],
            "EAL": df["EAL"],
            "Roll": df["roll"],
            "Index": df["index"]
        })
        
        return standardized_df
        
    except Exception as e:
        st.error(f"Error parsing Star Oddi .dat file: {e}")
        return None

def parse_staroddi_acc(file_path):
    """Parse Star Oddi .acc file and return DataFrame (acceleration data)"""
    try:
        with open(file_path, 'rb') as file:
            lines = file.read().decode("latin1").splitlines()
        
        data_start = next(i for i, line in enumerate(lines) if line and line[0].isdigit())
        colnames = ["rownum", "datetime", "g", "x_acc", "y_acc", "z_acc"]
        
        df = pd.read_csv(
            io.StringIO('\n'.join(lines[data_start:])),
            sep="\t",
            names=colnames,
            header=None,
            na_values="____"
        )
        
        df["datetime"] = df["datetime"].astype(str).str.replace(",", ".", regex=False)
        df["datetime"] = pd.to_datetime(df["datetime"], format="%d.%m.%Y %H:%M:%S.%f", errors="coerce")
        
        for col in ["g", "x_acc", "y_acc", "z_acc"]:
            df[col] = df[col].astype(str).str.replace(",", ".", regex=False)
            df[col] = pd.to_numeric(df[col], errors="coerce")
        
        # For acceleration files, we don't have depth data
        # Return standardized format but with acceleration data
        standardized_df = pd.DataFrame({
            "Timestamp": df["datetime"],
            "X_Acceleration": df["x_acc"],
            "Y_Acceleration": df["y_acc"],
            "Z_Acceleration": df["z_acc"],
            "Total_G": df["g"]
        })
        
        return standardized_df
        
    except Exception as e:
        st.error(f"Error parsing Star Oddi .acc file: {e}")
        return None

def process_star_oddi_data(relative_path):
    """Process Star Oddi data files and return standardized DataFrame"""
    try:
        # Construct the full file path using the relative path
        full_path = get_full_path(relative_path)
        
        # Validate the file path
        if not os.path.exists(full_path):
            st.error(f"Star Oddi file not found at path: {full_path}")
            return None
        
        # Determine file type and parse accordingly
        if full_path.lower().endswith('.dat'):
            return parse_staroddi_dat(full_path)
        elif full_path.lower().endswith('.acc'):
            return parse_staroddi_acc(full_path)
        else:
            st.error(f"Unsupported Star Oddi file format: {full_path}")
            return None
            
    except Exception as e:
        st.error(f"An error occurred while processing Star Oddi file: {e}")
        return None

def parse_winch_dat(file_path, parsing_settings):
    """
    Parse winch .dat file with custom settings
    
    Args:
        file_path: Path to the .dat file
        parsing_settings: Dict with keys:
            - delimiter: str (default ",")
            - header_lines: int (default 0)
            - columns: list of column names (optional)
            - datetime_code: str, Python code to create datetime column
            - numeric_columns: list of column names to convert to numeric (optional)
    
    Returns:
        DataFrame with parsed data including 'datetime' column
    """
    delimiter = parsing_settings.get("delimiter", ",")
    header_lines = parsing_settings.get("header_lines", 0)
    columns = parsing_settings.get("columns", None)
    datetime_code = parsing_settings.get("datetime_code", "pd.to_datetime(df['datetime'])")
    numeric_columns = parsing_settings.get("numeric_columns", [])
    
    # Read the file
    df = pd.read_csv(
        file_path,
        delimiter=delimiter,
        skiprows=header_lines,
        header=None if columns else 0,
        names=columns if columns else None,
        low_memory=False,
        on_bad_lines='skip'  # <-- Add this!
    )
    
    # Execute the datetime code to create datetime column
    try:
        exec(f"df['datetime'] = {datetime_code}", {"df": df, "pd": pd})
        # Make datetime column timezone naive
        if pd.api.types.is_datetime64_any_dtype(df['datetime']):
            df['datetime'] = df['datetime'].dt.tz_localize(None)
    except Exception as e:
        raise ValueError(f"Error creating datetime column: {e}\nCode: {datetime_code}")
    
    # Convert specified columns to numeric
    for col in numeric_columns:
        if col in df.columns:
            try:
                # Remove common formatting and convert to numeric
                df[col] = pd.to_numeric(df[col].astype(str).str.strip(), errors='coerce')
                print(f"✅ Converted column '{col}' to numeric")
            except Exception as e:
                print(f"⚠️ Warning: Could not convert column '{col}' to numeric: {e}")
    
    return df

import re

def parse_usbl_first_last(fileobj, filename):
    """
    Read first and last $PSONLLD time tokens from a file-like object and
    return (first_dt, last_dt) as naive pandas.Timestamp anchored to the
    YYYYMMDD found in the filename. Returns (None, None) on failure.
    """
    try:
        m = re.search(r'(\d{8})', filename)
        if not m:
            return None, None
        file_date = pd.to_datetime(m.group(1), format="%Y%m%d", errors="coerce")
        if pd.isna(file_date):
            return None, None

        time_re = re.compile(r'\$PSONLLD,(\d{6}(?:\.\d+)?)')
        first_s = last_s = None

        # iterate lines without loading whole file into memory
        fileobj.seek(0)
        for raw in fileobj:
            line = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
            mm = time_re.search(line)
            if not mm:
                continue
            t = mm.group(1)
            if first_s is None:
                first_s = t
            last_s = t

        if not first_s or not last_s:
            return None, None

        def hhmmss_to_td(s):
            s = str(s)
            if '.' in s:
                main, frac = s.split('.', 1)
                try:
                    frac = float("0." + frac)
                except Exception:
                    frac = 0.0
            else:
                main, frac = s, 0.0
            main = main.zfill(6)
            hh = int(main[:-4]) if len(main) > 4 else 0
            mm = int(main[-4:-2])
            ss = int(main[-2:])
            return pd.Timedelta(seconds=hh * 3600 + mm * 60 + ss + frac)

        td_first = hhmmss_to_td(first_s)
        td_last = hhmmss_to_td(last_s)

        first_dt = pd.Timestamp(file_date) + td_first
        last_dt = pd.Timestamp(file_date) + td_last

        # if first > last, assume first line belongs to previous day
        if td_first > td_last:
            first_dt -= pd.Timedelta(days=1)

        return first_dt, last_dt
    except Exception:
        return None, None

def load_usbl_file(file_path):
    """Load a USBL file and return DataFrame with datetime index"""
    try:
        # Read the CSV
        df = pd.read_csv(
            file_path,
            header=None,
            names=[
                "ID","utc_time","beacon_name","fix_status","latitude_deg","longitude_deg",
                "depth_m","hor_err_major","hor_err_minor","hor_err_dir",
                "depth_error","reserved_1","reserved_2","reserved_3","checksum",
            ],
            dtype={"utc_time": str},
        )
        st.write(f"Loaded USBL file: {file_path}")
        #st.write("Columns:", list(df.columns))
        #st.dataframe(df.head(10), use_container_width=True)
        
        # Extract date from filename
        file_name = Path(file_path).name
        date_str = file_name.split("_")[1]  # "PSONLLD_20251018_000000.txt" -> "20251018"
        
        # Build UTC datetime
        df["datetime"] = pd.to_datetime(
            date_str + " " + df["utc_time"].astype(str),
            format="%Y%m%d %H%M%S.%f",
            utc=True
        )
        
        # Handle midnight rollover
        time_values = pd.to_datetime(df["utc_time"], format="%H%M%S.%f", errors="coerce")
        if len(time_values) > 1:
            first_time = time_values.iloc[0]
            last_time = time_values.iloc[-1]
            if not pd.isna(first_time) and not pd.isna(last_time):
                if first_time.time() > last_time.time():
                    # Find the rollover point
                    rollover_idx = (time_values.diff() < pd.Timedelta(0)).idxmax()
                    if rollover_idx > 0:
                        df.loc[:rollover_idx-1, "datetime"] -= pd.Timedelta(days=1)

        
        # Keep only the columns we need
        usbl_df = df[["datetime", "latitude_deg", "longitude_deg", "depth_m", "beacon_name", 
                      "fix_status", "hor_err_major", "hor_err_minor", 
                      "hor_err_dir", "depth_error"]].copy()
        
        #st.write(f"Preview of parsed USBL data from {file_name}:")
        #st.dataframe(usbl_df.head(10), use_container_width=True)
        #st.write("Datetime dtype:", usbl_df['datetime'].dtype)
        #st.write("Non-null latitude_deg:", usbl_df['latitude_deg'].notna().sum())
        
        return usbl_df
        
    except Exception as e:
        st.error(f"Error loading USBL file: {e}")
        return None

def add_utm_coords(df, lat_col="latitude_deg", lon_col="longitude_deg", utm_zone=33, northern=True):
    """
    Adds UTM X/Y columns to a DataFrame using specified UTM zone and hemisphere.
    Args:
        df: DataFrame with latitude and longitude columns
        lat_col: Name of latitude column
        lon_col: Name of longitude column
        utm_zone: Integer UTM zone (e.g., 33)
        northern: True for northern hemisphere, False for southern
    Returns:
        DataFrame with added 'X_Center' and 'Y_Center' columns (in meters)
    """
    utm_crs = f"+proj=utm +zone={utm_zone} +{'north' if northern else 'south'} +ellps=WGS84 +datum=WGS84 +units=m +no_defs"
    transformer = Transformer.from_crs("epsg:4326", utm_crs, always_xy=True)
    x, y = transformer.transform(df[lon_col].values, df[lat_col].values)
    df = df.copy()
    df["X_Center"] = x
    df["Y_Center"] = y
    return df

def ellipse_polygon(x, y, semi_major, semi_minor, azimuth_deg, n_points=60):
    circle = Point(0, 0).buffer(1, resolution=n_points)
    ellipse = scale(circle, semi_major, semi_minor)
    ellipse = rotate(ellipse, azimuth_deg, origin=(0, 0), use_radians=False)
    ellipse = translate(ellipse, x, y)
    return ellipse

