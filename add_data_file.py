import streamlit as st
import pandas as pd
import os
from db_util import get_connection, fetch_cores
from sqlalchemy import text
from config import ROOT_DIRECTORY, SUBDIRECTORIES, get_full_path

# --- Add Manage Files Page ---
st.title("📂 Manage Associated Data Files")
st.write("You can upload and manage files related to sediment cores here.")

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
        query = text("""
            INSERT INTO mscl_files (core_id, file_name, file_path, file_type, remarks)
            VALUES (:core_id, :file_name, :file_path, :file_type, :remarks)
        """)
        conn.execute(query, {
            "core_id": core_id,
            "file_name": file_name,
            "file_path": file_path,
            "file_type": file_type,
            "remarks": remarks or None
        })
        conn.commit()

def insert_sensor_file(core_id, file_name, file_path, file_type, sensor_location, sensor_type, remarks):
    with get_connection() as conn:
        query = text("""
            INSERT INTO sensor_files (core_id, file_name, file_path, file_type, sensor_location, sensor_type, remarks)
            VALUES (:core_id, :file_name, :file_path, :file_type, :sensor_location, :sensor_type, :remarks)
        """)
        conn.execute(query, {
            "core_id": core_id,
            "file_name": file_name,
            "file_path": file_path,
            "file_type": file_type,
            "sensor_location": sensor_location or None,
            "sensor_type": sensor_type or None,
            "remarks": remarks or None
        })
        conn.commit()

# Fetch list of cores
cores = fetch_cores()
if cores.empty:
    st.warning("No cores found. Please add cores first.")
else:
    core_options = {f"{name} (ID: {id})": id for id, name in zip(cores['core_id'], cores['core_name'])}

    # Dropdown to select core
    selected_core_label = st.selectbox("Select Core to Associate File With", list(core_options.keys()))
    selected_core_id = core_options[selected_core_label]

    # File category selection
    file_category = st.selectbox("Select File Category", ["MSCL Data", "Sensor Data"])

    if file_category == "MSCL Data":
        st.subheader("📊 MSCL Data File")
        
        # File type for MSCL is always "MSCL Data"
        file_type = "MSCL Data"
        
        # File upload
        uploaded_file = st.file_uploader("Upload MSCL Data File", type=["out", "csv", "txt"], key="mscl_uploader")
        
        # MSCL remarks field
        remarks = st.text_area("MSCL Remarks", placeholder="Enter MSCL-specific remarks...")
        
        # Process MSCL file upload
        if uploaded_file is not None:
            if st.button("Save MSCL File"):
                with st.spinner(f"Processing MSCL file '{uploaded_file.name}'..."):
                    uploaded_file_path = upload_file(uploaded_file, "MSCL Data")
                    insert_mscl_file(selected_core_id, uploaded_file.name, uploaded_file_path, file_type, remarks)
                    st.success(f"MSCL file '{uploaded_file.name}' saved successfully!")

    elif file_category == "Sensor Data":
        st.subheader("🌡️ Sensor Data File")
        
        # File type selection (RBR vs Star-Oddi)
        file_type = st.selectbox("Sensor Brand", ["RBR Sensor", "Star-Oddi Sensor"])
        
        # Set file extensions based on sensor brand
        if file_type == "RBR Sensor":
            file_extensions = ["rsk"]
        elif file_type == "Star-Oddi Sensor":
            file_extensions = ["dat", "txt", "csv"]
        
        # Sensor location dropdown
        sensor_location_options = [
            "Weight Stand",
            "Release Device", 
            "Trigger Core/Weight",
            "Core Barrel",
            "External Mount",
            "Other Location"
        ]
        sensor_location = st.selectbox("Sensor Location", ["Select Location..."] + sensor_location_options)
        if sensor_location == "Select Location...":
            sensor_location = None
        elif sensor_location == "Other Location":
            sensor_location = st.text_input("Specify Other Location")

        # Sensor type - what measurements the sensor takes
        st.write("**Sensor Measurements (select all that apply):**")
        measurements = {
            "Temperature": st.checkbox("Temperature"),
            "Depth/Pressure": st.checkbox("Depth/Pressure"),
            "Acceleration": st.checkbox("Acceleration"),
            "Tilt": st.checkbox("Tilt")
        }
        
        # Build sensor_type string from selected measurements
        selected_measurements = [measurement for measurement, selected in measurements.items() if selected]
        if selected_measurements:
            sensor_type = ", ".join(selected_measurements)
        else:
            sensor_type = None
        
        # File upload
        uploaded_file = st.file_uploader("Upload Sensor Data File", type=file_extensions, key="sensor_uploader")
        
        # Sensor remarks field
        remarks = st.text_area("Sensor Remarks", placeholder="Enter sensor-specific remarks...")
        
        # Validation and save
        missing_fields = []
        if not sensor_location:
            missing_fields.append("Sensor Location")
        if not selected_measurements:
            missing_fields.append("Sensor Measurements")
        
        # Process sensor file upload
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