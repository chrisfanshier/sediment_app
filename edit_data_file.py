import streamlit as st
import pandas as pd
import os
from db_util import get_connection, fetch_cores
from sqlalchemy import text
from config import ROOT_DIRECTORY, SUBDIRECTORIES, get_full_path

# Custom CSS to reduce blank space
st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
        padding-left: 0rem !important;
        padding-right: 1rem !important;
    }
    .css-1lcbmhc {
        margin-left: 0rem !important;
        margin-right: 0rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("✏️ Edit Data File Associations")
st.write("Select and edit existing file associations with cores.")

# Fetch list of cores
cores = fetch_cores()
if cores.empty:
    st.warning("No cores found. Please add cores first.")
else:
    core_options = {f"{name} (ID: {id})": id for id, name in zip(cores['core_id'], cores['core_name'])}

    # Step 1: Select Core
    selected_core_label = st.selectbox("Select Core", list(core_options.keys()))
    selected_core_id = core_options[selected_core_label]

    # Step 2: Get files for selected core
    with get_connection() as conn:
        # Get MSCL files
        mscl_query = text("SELECT file_id, file_name, file_type, remarks FROM mscl_files WHERE core_id = :core_id")
        mscl_files = pd.read_sql(mscl_query, conn, params={"core_id": selected_core_id})
        
        # Get Sensor files
        sensor_query = text("SELECT file_id, file_name, file_type, sensor_location, sensor_type, remarks FROM sensor_files WHERE core_id = :core_id")
        sensor_files = pd.read_sql(sensor_query, conn, params={"core_id": selected_core_id})

    # Step 3: Display files and allow selection
    total_files = len(mscl_files) + len(sensor_files)
    
    if total_files == 0:
        st.info(f"No files found for core: {selected_core_label}")
    else:
        st.write(f"**Found {total_files} file(s) for {selected_core_label}:**")
        
        # Create file options for selection
        file_options = {}
        
        # Add MSCL files to options
        for _, row in mscl_files.iterrows():
            label = f"📊 {row['file_name']} (MSCL - {row['file_type']})"
            file_options[label] = ("mscl", row['file_id'])
        
        # Add Sensor files to options
        for _, row in sensor_files.iterrows():
            label = f"🌡️ {row['file_name']} ({row['file_type']} - {row['sensor_type'] or 'Unknown'})"
            file_options[label] = ("sensor", row['file_id'])
        
        # Step 4: Select file to edit
        selected_file_label = st.selectbox("Select File to Edit", list(file_options.keys()))
        file_type, file_id = file_options[selected_file_label]
        
        # Step 5: Load and edit file data
        if file_type == "mscl":
            st.subheader("📊 Edit MSCL File")
            
            # Get current MSCL file data
            with get_connection() as conn:
                query = text("SELECT * FROM mscl_files WHERE file_id = :file_id")
                file_data = conn.execute(query, {"file_id": file_id}).fetchone()
            
            if file_data:
                # Display current values
                st.write(f"**File Name:** {file_data.file_name}")
                st.write(f"**File Path:** {file_data.file_path}")
                st.write(f"**File Type:** {file_data.file_type}")  # Just display, don't edit
                
                # Only editable field for MSCL files
                new_remarks = st.text_area("MSCL Remarks", value=file_data.remarks or "", placeholder="Enter MSCL-specific remarks...")
                
                # Update button
                if st.button("Update MSCL File"):
                    with get_connection() as conn:
                        update_query = text("""
                            UPDATE mscl_files 
                            SET remarks = :remarks
                            WHERE file_id = :file_id
                        """)
                        conn.execute(update_query, {
                            "remarks": new_remarks or None,
                            "file_id": file_id
                        })
                        conn.commit()
                    st.success("MSCL file updated successfully!")
                    st.rerun()
        
        elif file_type == "sensor":
            st.subheader("🌡️ Edit Sensor File")
            
            # Get current sensor file data
            with get_connection() as conn:
                query = text("SELECT * FROM sensor_files WHERE file_id = :file_id")
                file_data = conn.execute(query, {"file_id": file_id}).fetchone()
            
            if file_data:
                # Display current values and allow editing
                st.write(f"**File Name:** {file_data.file_name}")
                st.write(f"**File Path:** {file_data.file_path}")
                
                # Editable fields
                new_file_type = st.selectbox("Sensor Brand", 
                    ["RBR Sensor", "Star-Oddi Sensor"],
                    index=["RBR Sensor", "Star-Oddi Sensor"].index(file_data.file_type) if file_data.file_type in ["RBR Sensor", "Star-Oddi Sensor"] else 0)
                
                # Sensor location dropdown
                sensor_location_options = [
                    "Weight Stand",
                    "Release Device", 
                    "Trigger Core/Weight",
                    "Core Barrel",
                    "External Mount",
                    "Other Location"
                ]
                current_location_idx = 0
                if file_data.sensor_location in sensor_location_options:
                    current_location_idx = sensor_location_options.index(file_data.sensor_location)
                
                new_sensor_location = st.selectbox("Sensor Location", 
                    ["Select Location..."] + sensor_location_options,
                    index=current_location_idx + 1 if file_data.sensor_location else 0)
                
                if new_sensor_location == "Select Location...":
                    new_sensor_location = None
                elif new_sensor_location == "Other Location":
                    new_sensor_location = st.text_input("Specify Other Location", value=file_data.sensor_location if file_data.sensor_location not in sensor_location_options else "")
                
                # Parse current sensor measurements
                current_measurements = file_data.sensor_type.split(", ") if file_data.sensor_type else []
                
                # Sensor type - what measurements the sensor takes
                st.write("**Sensor Measurements (select all that apply):**")
                measurements = {
                    "Temperature": st.checkbox("Temperature", value="Temperature" in current_measurements),
                    "Depth/Pressure": st.checkbox("Depth/Pressure", value="Depth/Pressure" in current_measurements),
                    "Acceleration": st.checkbox("Acceleration", value="Acceleration" in current_measurements),
                    "Tilt": st.checkbox("Tilt", value="Tilt" in current_measurements)
                }
                
                # Build sensor_type string from selected measurements
                selected_measurements = [measurement for measurement, selected in measurements.items() if selected]
                if selected_measurements:
                    new_sensor_type = ", ".join(selected_measurements)
                else:
                    new_sensor_type = None
                
                new_remarks = st.text_area("Sensor Remarks", value=file_data.remarks or "", placeholder="Enter sensor-specific remarks...")
                
                # Validation
                missing_fields = []
                if not new_sensor_location:
                    missing_fields.append("Sensor Location")
                if not selected_measurements:
                    missing_fields.append("Sensor Measurements")
                
                # Update button
                if missing_fields:
                    st.warning(f"Please complete the following fields: {', '.join(missing_fields)}")
                else:
                    if st.button("Update Sensor File"):
                        with get_connection() as conn:
                            update_query = text("""
                                UPDATE sensor_files 
                                SET file_type = :file_type, sensor_location = :sensor_location, 
                                    sensor_type = :sensor_type, remarks = :remarks
                                WHERE file_id = :file_id
                            """)
                            conn.execute(update_query, {
                                "file_type": new_file_type,
                                "sensor_location": new_sensor_location,
                                "sensor_type": new_sensor_type,
                                "remarks": new_remarks or None,
                                "file_id": file_id
                            })
                            conn.commit()
                        st.success("Sensor file updated successfully!")
                        st.rerun()

        # Delete file option
        st.markdown("---")
        st.subheader("🗑️ Delete File")
        st.warning("⚠️ This will permanently delete the file record from the database (but not the actual file).")
        
        if st.button("Delete File Record", type="secondary"):
            with get_connection() as conn:
                if file_type == "mscl":
                    delete_query = text("DELETE FROM mscl_files WHERE file_id = :file_id")
                else:
                    delete_query = text("DELETE FROM sensor_files WHERE file_id = :file_id")
                
                conn.execute(delete_query, {"file_id": file_id})
                conn.commit()
            st.success("File record deleted successfully!")
            st.rerun()