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

def _remove_control_chars_series(s: pd.Series) -> pd.Series:
    """Remove ASCII C0/C1 control bytes and trim whitespace."""
    return s.astype(str).str.replace(r'[\x00-\x1F\x7F-\x9F]', '', regex=True).str.strip()

def sanitize_text_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip control/non-printable chars from all object columns in-place and return df."""
    for c in df.select_dtypes(include=['object']).columns:
        df[c] = _remove_control_chars_series(df[c])
    return df

def sanitize_df_for_display(df: pd.DataFrame, target_encoding: str | None = None) -> pd.DataFrame:
    """Return a copy safe to display under target_encoding by replacing unencodable chars."""
    import locale
    enc = target_encoding or locale.getpreferredencoding(False) or "cp1252"
    out = df.copy()
    for c in out.select_dtypes(include=['object']).columns:
        out[c] = out[c].astype(str).apply(lambda s: s.encode(enc, errors='replace').decode(enc, errors='replace'))
    return out

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
    
    # Read the file (keep encoding explicit if desired)
    df = pd.read_csv(
        file_path,
        delimiter=delimiter,
        skiprows=header_lines,
        header=None if columns else 0,
        names=columns if columns else None,
        low_memory=False,
        on_bad_lines='skip'
    )

    # CLEAN TEXT COLUMNS FIRST (remove control bytes that later break display/encoding)
    df = sanitize_text_columns(df)

    # Execute the datetime code to create datetime column (expect errors='coerce' in datetime_code)
    try:
        exec(f"df['datetime'] = {datetime_code}", {"df": df, "pd": pd})
        if pd.api.types.is_datetime64_any_dtype(df['datetime']):
            df['datetime'] = df['datetime'].dt.tz_localize(None)   
    except Exception as e:
        # write small diagnostic sample for debugging
        sample = df.head(200).to_csv(index=False, encoding='utf-8', errors='replace')
        diag = str(file_path) + ".diag_sample.csv"
        open(diag, "w", encoding="utf-8", errors="replace").write(sample)
        raise ValueError(f"Error creating datetime column: {e}. Wrote sample to {diag}")

    # Convert specified columns to numeric
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.strip(), errors='coerce')

    # Drop rows missing required datetime (optional, keep as default)
    if 'datetime' in df.columns:
        df = df[df['datetime'].notna()].reset_index(drop=True)

    return df


