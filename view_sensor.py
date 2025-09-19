import os
import streamlit as st
import pandas as pd
from db_util import get_connection, fetch_cores
from utils import process_rsk_data

# --- Visualize Sensor Data Page ---
def view_sensor_data():
    st.title("📊 Visualize Sensor Data")
    if 'compare_enabled' not in st.session_state:
        st.session_state['compare_enabled'] = False
    if 'comparison_settings_expanded' not in st.session_state:
        st.session_state['comparison_settings_expanded'] = False

    # Fetch list of cores
    cores = fetch_cores()
    core_options = {f"{name} (ID: {id})": id for id, name in zip(cores['core_id'], cores['core_name'])}

    col1, col2 = st.columns([1, 3])

    with col1:
        st.header("Controls")
        with st.expander("Core and File Selection", expanded=True):
            selected_core_label = st.selectbox("Select Core to Visualize Sensor Data", list(core_options.keys()))
            selected_core_id = core_options[selected_core_label]

            # Fetch associated Sensor files for the selected core
            with get_connection() as conn:
                query = "SELECT file_name, file_path FROM files WHERE core_id = %s AND file_type = 'RBR Sensor'"
                df_files = pd.read_sql(query, conn, params=(selected_core_id,))

            if not df_files.empty:
                selected_file_label = st.selectbox("Select Sensor Data File", df_files['file_name'])
                file_row = df_files[df_files['file_name'] == selected_file_label].iloc[0]
                file_path = file_row['file_path']
                file_name = selected_file_label

                # Construct the full file path
                full_file_path = os.path.join(file_path, file_name)
                st.write(f"Full file path: {full_file_path}")  # Debugging

                # Process the selected file
                try:
                    processed_data = process_rsk_data(full_file_path)
                    if processed_data is not None:
                        st.subheader("Processed Data Preview")
                        st.dataframe(processed_data.head())  # Display the first few rows of the DataFrame
                    else:
                        st.warning("No data was returned from the processing function.")
                except Exception as e:
                    st.error(f"An error occurred while processing the file: {e}")
            else:
                st.warning("No Sensor file for this core.")