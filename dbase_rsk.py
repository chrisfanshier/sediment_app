import streamlit as st
from plot_rsk_file import plot_iterative  # Import the plotting functionality
import psycopg2
import pandas as pd

# Database connection
def get_connection():
    """Create and return a connection to the database."""
    return psycopg2.connect(
        host="localhost",
        database="sediment_cores",
        user="postgres",
        password="madmaxfuryroad"  # Replace with your database password
    )

@st.cache_data
def fetch_cores():
    """Fetch core names and IDs from the database."""
    with get_connection() as conn:
        query = "SELECT core_id, core_name FROM cores"
        cores = pd.read_sql(query, conn)
    return cores

@st.cache_data
def fetch_files_for_core(core_id):
    """Fetch file names and paths associated with a given core ID."""
    with get_connection() as conn:
        query = "SELECT file_name, file_path FROM files WHERE core_id = %s AND file_type = 'RBR Sensor'"
        files = pd.read_sql(query, conn, params=(core_id,))
    return files

# Streamlit App
st.title("RSK File Processor (Step 1: Select File)")

# Step 1: Core Selection
cores = fetch_cores()
if not cores.empty:
    core_options = {row["core_name"]: row["core_id"] for _, row in cores.iterrows()}
    selected_core_name = st.selectbox("Select Core", list(core_options.keys()))
    selected_core_id = core_options[selected_core_name]

    # Step 2: File Selection
    files = fetch_files_for_core(selected_core_id)
    if not files.empty:
        file_options = {row["file_name"]: row["file_path"] for _, row in files.iterrows()}
        selected_file_name = st.selectbox("Select RSK Data File", list(file_options.keys()))
        selected_file_path = file_options[selected_file_name]

        # Step 3: Call the plotting function
        if st.button("Process and Plot Selected File"):
            plot_iterative(selected_file_path, selected_file_name)  # Call the plotting functionality
    else:
        st.warning("No files found for the selected core.")
else:
    st.warning("No cores found in the database.")