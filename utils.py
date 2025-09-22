import os
import re
import pandas as pd
import streamlit as st
import numpy as np
from pyrsktools import RSK
from db_util import get_connection
from db_util import get_dynamic_fields_metadata

def parse_mscl_out_file(file_path, file_name):
    """Parse an MSCL .out file and return a Pandas DataFrame."""
    try:

        # Construct the full file path
        full_path = os.path.join(file_path, file_name)

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

def process_rsk_data(file_path):
    """Process an RSK file and return a DataFrame."""

    # Validate the file path
    if not os.path.exists(file_path):
        st.error(f"RSK file not found at path: {file_path}")
        return None

    try:
        with RSK(file_path) as rsk:
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
        st.error(f"RSK file not found at path: {file_path}")
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

def render_dynamic_fields_from_metadata(core_type_id):
    """
    Render dynamic fields based on metadata from the database.
    """
    # Fetch dynamic fields metadata
    dynamic_fields = get_dynamic_fields_metadata(core_type_id) or []  # Ensure it's a list, even if None is returned

    dynamic_field_values = {}

    # Render input fields based on the metadata
    for field in dynamic_fields:
        field_name = field.replace("_", " ").capitalize()  # Clean up field names for display

        # Map the data type to Streamlit input type
        input_metadata = map_data_type_to_input(field)

        # Render inputs dynamically
        if input_metadata["input_type"] == "integer":
            dynamic_field_values[field] = st.number_input(
                f"{field_name} (integer)", min_value=0, step=input_metadata["step"], format=input_metadata["format"]
            )
        elif input_metadata["input_type"] == "float":
            dynamic_field_values[field] = st.number_input(
                f"{field_name} (numeric)", min_value=0.0, step=input_metadata["step"], format=input_metadata["format"]
            )
        elif input_metadata["input_type"] == "text":
            dynamic_field_values[field] = st.text_input(f"{field_name}")
        elif input_metadata["input_type"] == "boolean":
            dynamic_field_values[field] = st.checkbox(f"{field_name}")
        elif input_metadata["input_type"] == "date":
            dynamic_field_values[field] = st.date_input(f"{field_name}")
        elif input_metadata["input_type"] == "time":
            dynamic_field_values[field] = st.time_input(f"{field_name}")
        else:
            dynamic_field_values[field] = st.text_input(f"{field_name} (default)")

    return dynamic_field_values