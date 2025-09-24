import os
import streamlit as st
import pandas as pd
from db_util import get_connection, fetch_cores
from utils import process_rsk_data
from plotting import plot_rbr_downsampled, plot_rbr_high_resolution
from config import get_full_path  # Import the utility function for constructing full paths

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

    col1, col2 = st.columns([1, 3])  # Left column for controls, right column for plotting

    with col1:
        st.header("Controls")
        with st.expander("Core and File Selection", expanded=True):
            # --- Primary File Selection ---
            selected_core_label = st.selectbox("Select Core to Visualize Sensor Data", list(core_options.keys()))
            selected_core_id = core_options[selected_core_label]

            # Fetch associated Sensor files for the selected core
            with get_connection() as conn:
                query = "SELECT file_name, file_path FROM files WHERE core_id = %s AND file_type = 'RBR Sensor'"
                df_files = pd.read_sql(query, conn, params=(selected_core_id,))

            if not df_files.empty:
                selected_file_label = st.selectbox("Select Primary Sensor Data File", df_files['file_name'])
                file_row = df_files[df_files['file_name'] == selected_file_label].iloc[0]
                # Construct the full file path for the primary file
                primary_file_path = get_full_path(file_row['file_path'])
            else:
                st.warning("No sensor data file for this core.")
                primary_file_path = None

            # --- Secondary File Selection ---
            st.subheader("Overlay Plot")
            overlay_option = st.radio("Select overlay data source:", ["None", "Same Core", "Different Core"])
            overlay_file_path = None

            if overlay_option == "Same Core":
                overlay_file_label = st.selectbox(
                    "Select a file to overlay from the same core:",
                    [file for file in df_files['file_name'] if file != selected_file_label],
                    index=0 if len(df_files) > 1 else None
                )
                overlay_file_row = df_files[df_files['file_name'] == overlay_file_label].iloc[0]
                overlay_file_path = get_full_path(overlay_file_row['file_path'])

            elif overlay_option == "Different Core":
                overlay_core_label = st.selectbox("Select Core for Overlay:", list(core_options.keys()))
                overlay_core_id = core_options[overlay_core_label]
                with get_connection() as conn:
                    overlay_query = "SELECT file_name, file_path FROM files WHERE core_id = %s AND file_type = 'RBR Sensor'"
                    overlay_df_files = pd.read_sql(overlay_query, conn, params=(overlay_core_id,))
                if not overlay_df_files.empty:
                    overlay_file_label = st.selectbox("Select Overlay File", overlay_df_files['file_name'])
                    overlay_file_row = overlay_df_files[overlay_df_files['file_name'] == overlay_file_label].iloc[0]
                    overlay_file_path = get_full_path(overlay_file_row['file_path'])

            # --- Third Trace Selection ---
            st.subheader("Add a Third Trace (Optional)")
            third_trace_option = st.radio("Add a third data source?", ["None", "Select Core and File"])
            third_file_path = None
            if third_trace_option == "Select Core and File":
                third_core_label = st.selectbox("Select Core for Third Trace:", list(core_options.keys()))
                third_core_id = core_options[third_core_label]
                with get_connection() as conn:
                    third_query = "SELECT file_name, file_path FROM files WHERE core_id = %s AND file_type = 'RBR Sensor'"
                    third_df_files = pd.read_sql(third_query, conn, params=(third_core_id,))
                if not third_df_files.empty:
                    third_file_label = st.selectbox("Select Third Trace File", third_df_files['file_name'])
                    third_file_row = third_df_files[third_df_files['file_name'] == third_file_label].iloc[0]
                    third_file_path = get_full_path(third_file_row['file_path'])

    # --- Plotting in the Right Column ---
    with col2:
        if primary_file_path:
            try:
                primary_df = process_rsk_data(primary_file_path)
                overlay_df = process_rsk_data(overlay_file_path) if overlay_file_path else None
                third_df = process_rsk_data(third_file_path) if third_file_path else None

                if primary_df is not None:
                    st.subheader("Interactive Plotting")
                    max_points = st.slider("Max Points for Plotting", min_value=100, max_value=5000, value=1000, step=100)
                    y_axis = st.selectbox(
                        "Select Parameter to Plot:",
                        options=["Pressure (dbar)", "Sea Pressure (dbar)", "Depth (m)"],
                        index=2,
                    )
                    fig = plot_rbr_downsampled(
                        primary_df, overlay_df, third_df, y_axis=y_axis, max_points=max_points, primary_core_name=selected_core_label
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    # --- High-Resolution Plotting ---
                    st.subheader("High-Resolution Plot")

                    # Calculate default start and end times based on the greatest depth
                    if primary_df is not None and "Depth (m)" in primary_df.columns:
                        max_depth_row = primary_df.loc[primary_df["Depth (m)"].idxmax()]
                        max_depth_time = max_depth_row["Timestamp"]
                        default_start_time = (max_depth_time - pd.Timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
                        default_end_time = (max_depth_time + pd.Timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        default_start_time = ""
                        default_end_time = ""

                    # Input fields for start and end times
                    start_time = st.text_input("Start Time (YYYY-MM-DD HH:MM:SS):", value=default_start_time, key="start_time")
                    end_time = st.text_input("End Time (YYYY-MM-DD HH:MM:SS):", value=default_end_time, key="end_time")

                    # Add number inputs for x and y offsets
                    st.subheader("Adjust Overlay and Third Trace (Offsets)")
                    overlay_x_offset = st.number_input("Overlay X Offset", value=0.0, step=0.1)
                    overlay_y_offset = st.number_input("Overlay Y Offset", value=0.0, step=0.1)
                    third_x_offset = st.number_input("Third Trace X Offset", value=0.0, step=0.1)
                    third_y_offset = st.number_input("Third Trace Y Offset", value=0.0, step=0.1)

                    # Generate high-resolution plot
                    if st.button("Generate High-Resolution Plot"):
                        if start_time and end_time:
                            try:
                                high_res_fig = plot_rbr_high_resolution(
                                    primary_df, overlay_df, third_df, y_axis=y_axis, start_time=start_time, end_time=end_time,
                                    primary_core_name=selected_core_label,
                                    overlay_x_offset=overlay_x_offset, overlay_y_offset=overlay_y_offset,
                                    third_x_offset=third_x_offset, third_y_offset=third_y_offset
                                )
                                st.plotly_chart(high_res_fig, use_container_width=True)
                            except Exception as e:
                                st.error(f"An error occurred while generating the high-resolution plot: {e}")
                        else:
                            st.warning("Please provide both Start Time and End Time for high-resolution plotting.")
            except Exception as e:
                st.error(f"An error occurred while processing the files: {e}")