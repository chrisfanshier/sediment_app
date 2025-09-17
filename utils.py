import re
import pandas as pd
import streamlit as st

def parse_mscl_out_file(file_path, file_name):
    """Parse an MSCL .out file and return a Pandas DataFrame."""
    try:
        # Construct the full file path using the file_path column and file_name
        full_path = f"{file_path}/{file_name}"

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