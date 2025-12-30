import streamlit as st
import pandas as pd
import os
import json
from db_util import get_connection, fetch_cores, fetch_cruise_options, add_sync_tracking
from sqlalchemy import text
from config import ROOT_DIRECTORY, SUBDIRECTORIES, get_full_path, WINCH_FORMATS

# --- Add Manage Files Page ---
st.title("📂 Manage Associated Data Files")
st.write("You can upload and manage files related to sediment cores and winch data here.")

# Define the upload_file function
def upload_file(file, file_type):
    # Get the subdirectory for the selected file type
    subdirectory = SUBDIRECTORIES.get(file_type)
    if not subdirectory:
        raise ValueError(f"Unknown file type: {file_type}")

    # Construct the full directory path
    upload_dir = os.path.join(ROOT_DIRECTORY, subdirectory)

    # Ensure the directory exists
    os.makedirs(upload_dir, exist_ok=True)

    # Save the file to the appropriate directory
    file_path = os.path.join(upload_dir, file.name)
    with open(file_path, "wb") as f:
        f.write(file.getbuffer())

    # Return only the relative directory (not the full path)
    return subdirectory

# Define the insert functions for specialized tables
def insert_mscl_file(core_id, file_name, file_path, file_type, remarks):
    with get_connection() as conn:
        values = {
            "core_id": core_id,
            "file_name": file_name,
            "file_path": file_path,
            "file_type": file_type,
            "remarks": remarks or None
        }
        # Add sync tracking
        values = add_sync_tracking(values)
        
        query = text("""
            INSERT INTO mscl_files (core_id, file_name, file_path, file_type, remarks, created_on_ship, sync_status)
            VALUES (:core_id, :file_name, :file_path, :file_type, :remarks, :created_on_ship, :sync_status)
        """)
        conn.execute(query, values)
        conn.commit()

def insert_sensor_file(core_id, file_name, file_path, file_type, sensor_location, sensor_type, remarks):
    with get_connection() as conn:
        values = {
            "core_id": core_id,
            "file_name": file_name,
            "file_path": file_path,
            "file_type": file_type,
            "sensor_location": sensor_location or None,
            "sensor_type": sensor_type or None,
            "remarks": remarks or None
        }
        # Add sync tracking
        values = add_sync_tracking(values)
        
        query = text("""
            INSERT INTO sensor_files (core_id, file_name, file_path, file_type, sensor_location, sensor_type, remarks, created_on_ship, sync_status)
            VALUES (:core_id, :file_name, :file_path, :file_type, :sensor_location, :sensor_type, :remarks, :created_on_ship, :sync_status)
        """)
        conn.execute(query, values)
        conn.commit()

def insert_winch_data(file_name, file_path, cruise_id, start_time, end_time, settings, notes=None):
    """Insert winch data metadata into the database"""
    with get_connection() as conn:
        values = {
            "file_name": file_name,
            "file_path": file_path,
            "cruise_id": cruise_id,
            "start_time": start_time,
            "end_time": end_time,
            "settings": settings,
            "notes": notes
        }
        # Add sync tracking
        values = add_sync_tracking(values)
        
        query = text('''
            INSERT INTO winch_data (
                file_name, file_path, cruise_id, start_time, end_time, settings, notes, created_on_ship, sync_status
            ) VALUES (:file_name, :file_path, :cruise_id, :start_time, :end_time, :settings, :notes, :created_on_ship, :sync_status)
        ''')
        conn.execute(query, values)
        conn.commit()

# Step 1: Select file category first
file_category = st.selectbox("Select File Category", ["MSCL Data", "Sensor Data", "Winch Data"])

if file_category in ["MSCL Data", "Sensor Data"]:
    # For core-related files, fetch and select core
    cores = fetch_cores(only_created_on_ship=True)
    if cores.empty:
        st.warning("No cores found. Please add cores first.")
        st.stop()
    
    core_options = {f"{name} (ID: {id})": id for id, name in zip(cores['core_id'], cores['core_name'])}
    selected_core_label = st.selectbox("Select Core to Associate File With", list(core_options.keys()))
    selected_core_id = core_options[selected_core_label]

elif file_category == "Winch Data":
    # For winch files, fetch and select cruise
    cruises = fetch_cruise_options(only_created_on_ship=True)
    if not cruises:
        st.warning("No cruises found. Please add a cruise first.")
        st.stop()
    
    cruise_options = ["Select Cruise"] + [f"{cruise.cruise_name} - {cruise.vessel_name} (ID: {cruise.cruise_id})" for cruise in cruises]
    cruise_choice = st.selectbox("Choose a cruise*", cruise_options)
    
    if cruise_choice != "Select Cruise":
        cruise_id = int(cruise_choice.split("ID: ")[1].rstrip(")"))
        cruise_name = cruise_choice.split(" - ")[0]
        st.success(f"✅ Selected cruise: **{cruise_name}**")
    else:
        st.warning("Please select a cruise to continue.")
        st.stop()

# File processing based on category
if file_category == "MSCL Data":
    st.subheader("📊 MSCL Data File")
    
    file_type = "MSCL Data"
    uploaded_file = st.file_uploader("Upload MSCL Data File", type=["out", "csv", "txt"], key="mscl_uploader")
    remarks = st.text_area("MSCL Remarks", placeholder="Enter MSCL-specific remarks...")
    
    if uploaded_file is not None:
        if st.button("Save MSCL File"):
            with st.spinner(f"Processing MSCL file '{uploaded_file.name}'..."):
                uploaded_file_path = upload_file(uploaded_file, "MSCL Data")
                insert_mscl_file(selected_core_id, uploaded_file.name, uploaded_file_path, file_type, remarks)
                st.success(f"MSCL file '{uploaded_file.name}' saved successfully!")

elif file_category == "Sensor Data":
    st.subheader("🌡️ Sensor Data File")
    
    file_type = st.selectbox("Sensor Brand", ["RBR Sensor", "Star-Oddi Sensor"])
    
    if file_type == "RBR Sensor":
        file_extensions = ["rsk"]
    elif file_type == "Star-Oddi Sensor":
        file_extensions = ["dat", "acc", "txt", "csv"]
    
    sensor_location_options = [
        "Weight Stand",
        "Release Device", 
        "Trigger Core/Weight",
        "Other Location"
    ]
    sensor_location = st.selectbox("Sensor Location", ["Select Location..."] + sensor_location_options)
    if sensor_location == "Select Location...":
        sensor_location = None
    elif sensor_location == "Other Location":
        sensor_location = st.text_input("Specify Other Location")

    st.write("**Sensor Measurements (select all that apply):**")
    measurements = {
        "Temperature": st.checkbox("Temperature"),
        "Depth/Pressure": st.checkbox("Depth/Pressure"),
        "Acceleration": st.checkbox("Acceleration"),
        "Tilt": st.checkbox("Tilt")
    }
    
    selected_measurements = [measurement for measurement, selected in measurements.items() if selected]
    sensor_type = ", ".join(selected_measurements) if selected_measurements else None
    
    uploaded_file = st.file_uploader("Upload Sensor Data File", type=file_extensions, key="sensor_uploader")
    remarks = st.text_area("Sensor Remarks", placeholder="Enter sensor-specific remarks...")
    
    missing_fields = []
    if not sensor_location:
        missing_fields.append("Sensor Location")
    if not selected_measurements:
        missing_fields.append("Sensor Measurements")
    
    if uploaded_file is not None:
        if missing_fields:
            st.warning(f"Please complete the following fields: {', '.join(missing_fields)}")
        else:
            if st.button("Save Sensor File"):
                with st.spinner(f"Processing sensor file '{uploaded_file.name}'..."):
                    uploaded_file_path = upload_file(uploaded_file, file_type)
                    insert_sensor_file(
                        selected_core_id, 
                        uploaded_file.name, 
                        uploaded_file_path, 
                        file_type,
                        sensor_location, 
                        sensor_type,
                        remarks
                    )
                    st.success(f"Sensor file '{uploaded_file.name}' saved successfully!")

elif file_category == "Winch Data":
    st.subheader("🚢 Winch Data File")
    
    uploaded_file = st.file_uploader("Upload Winch File")

    if uploaded_file is not None:
        # Format selection dropdown
        st.subheader("⚙️ File Format")
        format_choice = st.selectbox("Select Format", list(WINCH_FORMATS.keys()))
        selected_format = WINCH_FORMATS[format_choice]
        
        # Show format details
        if format_choice != "Custom Format":
            with st.expander(f"📋 {format_choice} Format Details"):
                st.json(selected_format)

        # Initialize settings from selected format
        header_lines = st.number_input("Number of header lines to skip", 
                                     min_value=0, 
                                     value=selected_format["header_lines"], 
                                     step=1)

        # Delimiter selection with format default
        delimiter_options = [
            ("Comma (,)", ","),
            ("Tab (\\t)", "\t"),
            ("Pipe (|)", "|"),
            ("Space ( )", " "),
            ("Semicolon (;)", ";"),
            ("Whitespace (\\s+)", r"\s+")
        ]
        
        # Find the default delimiter for the selected format
        format_delimiter = selected_format["delimiter"]
        default_idx = 0
        for i, (label, value) in enumerate(delimiter_options):
            if value == format_delimiter:
                default_idx = i
                break
        
        delimiter_label = st.selectbox("Select Delimiter", 
                                     [label for label, _ in delimiter_options],
                                     index=default_idx)
        delimiter = next(value for label, value in delimiter_options if label == delimiter_label)

        # Custom delimiter
        custom_delim = st.text_input("Custom delimiter (optional)", "")
        if custom_delim:
            delimiter = custom_delim

        # Preview raw data
        try:
            uploaded_file.seek(0)
            if delimiter == r"\s+":
                df_preview = pd.read_csv(uploaded_file, sep='\s+', skiprows=header_lines, nrows=20, header=None)
            else:
                df_preview = pd.read_csv(
                    uploaded_file,
                    delimiter=delimiter,
                    skiprows=header_lines,
                    nrows=20,
                    header=None,
                    on_bad_lines='skip'  # <-- Add this
                )
            st.write("Raw Preview (first 20 rows):", df_preview)
        except Exception as e:
            st.error(f"Error reading file: {e}")
            st.stop()

        # Column renaming with format default
        st.subheader("Rename Columns")
        default_columns = str(selected_format["columns"]) if selected_format["columns"] else "[]"
        colnames_input = st.text_area(
            "Enter column names as a Python list (e.g., ['year', 'month', 'day', ...])",
            value=default_columns
        )
        try:
            colnames = eval(colnames_input)
            if len(colnames) != len(df_preview.columns):
                st.warning("The number of column names does not match the number of columns in the file.")
            else:
                df_preview.columns = colnames
                st.write("Preview with renamed columns:", df_preview)
        except Exception as e:
            st.error(f"Error parsing column names: {e}")

        # Datetime column creation with format default
        st.subheader("Create Datetime Column")
        st.markdown(
            "Use the DataFrame `df` in your code. For example:\n"
            "`pd.to_datetime(df[['year', 'month', 'day', 'hour', 'minute', 'second']])`"
        )
        datetime_code = st.text_area(
            "Enter the Python code for creating the datetime column",
            value=selected_format["datetime_code"]
        )

        # Test datetime creation
        try:
            if datetime_code.strip():
                # Read the entire dataset
                uploaded_file.seek(0)
                if delimiter == r"\s+":
                    df = pd.read_csv(uploaded_file, sep='\s+', skiprows=header_lines, names=colnames, low_memory=False)
                else:
                    df = pd.read_csv(
                        uploaded_file,
                        delimiter=delimiter,
                        skiprows=header_lines,
                        names=colnames,
                        low_memory=False,
                        on_bad_lines='skip'  # <-- Add this
                    )

                # Execute datetime creation
                exec(f"df['datetime'] = {datetime_code}")
                
                # Convert numeric columns if specified in format
                if "numeric_columns" in selected_format:
                    numeric_cols = selected_format["numeric_columns"]
                    for col in numeric_cols:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col].astype(str).str.strip(), errors='coerce')
                            st.info(f"✅ Converted '{col}' to numeric")
                
                st.write("Preview with datetime column (first 20 rows):", df.head())

                # Calculate time range
                start_datetime = df['datetime'].min()
                end_datetime = df['datetime'].max()
                st.write(f"Start Datetime: {start_datetime}")
                st.write(f"End Datetime: {end_datetime}")
            else:
                start_datetime = None
                end_datetime = None
        except Exception as e:
            st.error(f"Error creating datetime column: {e}")
            start_datetime = None
            end_datetime = None

        # Optional notes
        notes = st.text_area("📝 Notes (Optional)", placeholder="Enter any notes about this winch data file")

        # Save winch file + metadata
        if st.button("Save Winch File"):
            if not colnames:
                st.error("❌ Please specify column names before saving")
            elif not datetime_code.strip():
                st.error("❌ Please specify datetime creation code before saving")
            elif start_datetime is None:
                st.error("❌ Please test datetime creation successfully before saving")
            else:
                try:
                    with st.spinner(f"Processing winch file '{uploaded_file.name}'..."):
                        # Save file using the same pattern as other files
                        uploaded_file_path = upload_file(uploaded_file, "Winch Data")

                        # Prepare settings as JSON - include numeric_columns from format
                        settings_dict = {
                            "delimiter": delimiter,
                            "header_lines": header_lines,
                            "columns": colnames,
                            "datetime_code": datetime_code,
                            "total_records": len(df),
                            "duration_hours": (end_datetime - start_datetime).total_seconds() / 3600
                        }
                        
                        # Add numeric_columns if present in selected format
                        if "numeric_columns" in selected_format:
                            settings_dict["numeric_columns"] = selected_format["numeric_columns"]
                        
                        settings = json.dumps(settings_dict)

                        # Insert metadata
                        insert_winch_data(
                            uploaded_file.name,
                            uploaded_file_path,
                            cruise_id,
                            str(start_datetime),
                            str(end_datetime),
                            settings,
                            notes
                        )

                        st.success(f"✅ Winch file '{uploaded_file.name}' saved successfully!")
                        st.write(f"**File saved to:** `{os.path.join(ROOT_DIRECTORY, uploaded_file_path, uploaded_file.name)}`")
                        st.write(f"**Cruise:** {cruise_name}")
                        st.write(f"**Records:** {len(df):,} data points")

                except Exception as e:
                    st.error(f"❌ Error saving file: {e}")
                    import traceback
                    st.code(traceback.format_exc())