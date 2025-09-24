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

# Define the insert_file function
def insert_file(core_id, file_name, file_path, file_type):
    with get_connection() as conn:
        query = text("""
            INSERT INTO files (core_id, file_name, file_path, file_type)
            VALUES (:core_id, :file_name, :file_path, :file_type)
        """)
        conn.execute(query, {
            "core_id": core_id,
            "file_name": file_name,
            "file_path": file_path,  # Only the relative directory
            "file_type": file_type
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

    # File type selection
    file_type = st.selectbox("Select File Type", ["MSCL Data", "RBR Sensor", "Star-Oddi Sensor"])

    # Dynamically set allowed file extensions based on file type
    allowed_extensions = {"MSCL Data": ["out"], "RBR Sensor": ["rsk"], "Star-Oddi Sensor": []}
    file_extensions = allowed_extensions[file_type]

    # Initialize session state for uploaded file tracking
    if "last_uploaded_file" not in st.session_state:
        st.session_state.last_uploaded_file = None

    # Upload file
    uploaded_file = st.file_uploader("Upload Data File", type=file_extensions, key="file_uploader")

    # Process the uploaded file only if it's new
    if uploaded_file is not None and uploaded_file != st.session_state.last_uploaded_file:
        # Save the file to session state to prevent duplicate processing
        st.session_state.last_uploaded_file = uploaded_file

        # Ensure only the current file is processed
        with st.spinner(f"Processing file '{uploaded_file.name}'..."):
            # Save the file to the 'uploaded_files' directory
            uploaded_file_path = upload_file(uploaded_file, file_type)
            st.success(f"File '{uploaded_file.name}' uploaded successfully!")
            st.write(f"File saved at: {uploaded_file_path}")

            # Insert the uploaded file into the database with the selected file type
            insert_file(selected_core_id, uploaded_file.name, uploaded_file_path, file_type)