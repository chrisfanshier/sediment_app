import os
import streamlit as st
import pandas as pd
from db_util import get_connection, fetch_cores
from utils import process_rsk_data, process_star_oddi_data
from plotting import plot_rbr_downsampled, plot_rbr_high_resolution, plot_rbr_dual_stacked
from config import get_full_path

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
            # --- Primary File Selection ---
            selected_core_label = st.selectbox("Select Core to Visualize Sensor Data", list(core_options.keys()))
            selected_core_id = core_options[selected_core_label]

            # Fetch associated Sensor files for the selected core
            with get_connection() as conn:
                query = "SELECT file_name, file_path, sensor_type, sensor_location, remarks FROM sensor_files WHERE core_id = %s"
                df_files = pd.read_sql(query, conn, params=(selected_core_id,))

            if not df_files.empty:
                selected_file_label = st.selectbox("Select Sensor Data File", df_files['file_name'])
                file_row = df_files[df_files['file_name'] == selected_file_label].iloc[0]
                
                # Display sensor metadata
                if file_row['sensor_type']:
                    st.info(f"**Sensor Type:** {file_row['sensor_type']}")
                if file_row['sensor_location']:
                    st.info(f"**Sensor Location:** {file_row['sensor_location']}")
                if file_row['remarks']:
                    st.info(f"**File Remarks:** {file_row['remarks']}")
                
                # Combine file_path and file_name to create the full relative path
                relative_path = os.path.join(file_row['file_path'], file_row['file_name'])
                primary_file_path = get_full_path(relative_path)
            else:
                st.warning("No sensor data file for this core.")
                primary_file_path = None

            # --- Secondary File Selection ---
            st.subheader("Overlay Plot")
            overlay_option = st.radio("Select overlay data source:", ["None", "Same Core", "Different Core"])
            overlay_file_path = None
            overlay_relative_path = None

            if overlay_option == "Same Core":
                other_files = [file for file in df_files['file_name'] if file != selected_file_label]
                if other_files:
                    overlay_file_label = st.selectbox("Select a file to overlay from the same core:", other_files, index=0)
                    overlay_file_row = df_files[df_files['file_name'] == overlay_file_label]
                    if not overlay_file_row.empty:
                        overlay_relative_path = os.path.join(overlay_file_row.iloc[0]['file_path'], overlay_file_row.iloc[0]['file_name'])
                        overlay_file_path = get_full_path(overlay_relative_path)
                    else:
                        st.warning("The selected overlay file could not be found.")
                else:
                    st.warning("No other files available for overlay in the same core.")

            elif overlay_option == "Different Core":
                overlay_core_label = st.selectbox("Select Core for Overlay:", list(core_options.keys()))
                overlay_core_id = core_options[overlay_core_label]
                with get_connection() as conn:
                    overlay_query = "SELECT file_name, file_path, sensor_type, sensor_location, remarks FROM sensor_files WHERE core_id = %s"
                    overlay_df_files = pd.read_sql(overlay_query, conn, params=(overlay_core_id,))
                if not overlay_df_files.empty:
                    overlay_file_label = st.selectbox("Select Overlay File", overlay_df_files['file_name'])
                    overlay_file_row = overlay_df_files[overlay_df_files['file_name'] == overlay_file_label]
                    if not overlay_file_row.empty:
                        overlay_relative_path = os.path.join(overlay_file_row.iloc[0]['file_path'], overlay_file_row.iloc[0]['file_name'])
                        overlay_file_path = get_full_path(overlay_relative_path)
                    else:
                        st.warning("The selected overlay file could not be found.")
                else:
                    st.warning("No sensor data files found for the selected core.")

            # --- Third Trace Selection ---
            st.subheader("Add a Third Trace (Optional)")
            third_trace_option = st.radio("Add a third data source?", ["None", "Select Core and File"])
            third_file_path = None
            third_relative_path = None
            if third_trace_option == "Select Core and File":
                third_core_label = st.selectbox("Select Core for Third Trace:", list(core_options.keys()))
                third_core_id = core_options[third_core_label]
                with get_connection() as conn:
                    third_query = "SELECT file_name, file_path, sensor_type, sensor_location, remarks FROM sensor_files WHERE core_id = %s"
                    third_df_files = pd.read_sql(third_query, conn, params=(third_core_id,))
                if not third_df_files.empty:
                    third_file_label = st.selectbox("Select Third Trace File", third_df_files['file_name'])
                    third_file_row = third_df_files[third_df_files['file_name'] == third_file_label].iloc[0]
                    third_relative_path = os.path.join(third_file_row['file_path'], third_file_row['file_name'])
                    third_file_path = get_full_path(third_relative_path)

        # --- High-Resolution Plot Controls (Moved to sidebar) ---
        with st.expander("High-Resolution Plot Controls", expanded=False):
            # Calculate default start and end times based on the greatest depth
            default_start_time = ""
            default_end_time = ""
            
            # We need to process the primary file first to get the depth data
            if primary_file_path:
                try:
                    # Helper function to determine if file is Star Oddi (moved up)
                    def is_star_oddi_file(file_path, sensor_type=None):
                        file_extension = os.path.splitext(file_path)[1].lower()
                        sensor_type_lower = sensor_type.lower() if sensor_type else ''
                        return (file_extension in ['.dat', '.acc'] or 
                               ('star' in sensor_type_lower and 'oddi' in sensor_type_lower))
                    
                    # Process primary file to get default times
                    if is_star_oddi_file(primary_file_path, file_row['sensor_type']):
                        temp_primary_df = process_star_oddi_data(relative_path)
                    else:
                        temp_primary_df = process_rsk_data(primary_file_path)
                    
                    if temp_primary_df is not None and "Depth (m)" in temp_primary_df.columns:
                        max_depth_row = temp_primary_df.loc[temp_primary_df["Depth (m)"].idxmax()]
                        max_depth_time = max_depth_row["Timestamp"]
                        default_start_time = (max_depth_time - pd.Timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
                        default_end_time = (max_depth_time + pd.Timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
                except:
                    # If there's any error, just use empty defaults
                    default_start_time = ""
                    default_end_time = ""
            
            # Input fields for start and end times with calculated defaults
            start_time = st.text_input("Start Time (YYYY-MM-DD HH:MM:SS):", value=default_start_time, key="start_time")
            end_time = st.text_input("End Time (YYYY-MM-DD HH:MM:SS):", value=default_end_time, key="end_time")

            # Add number inputs for x and y offsets
            st.write("**Adjust Overlay Offsets:**")
            overlay_x_offset = st.number_input("Overlay X Offset", value=0.0, step=0.1)
            overlay_y_offset = st.number_input("Overlay Y Offset", value=0.0, step=0.1)
            
            st.write("**Adjust Third Trace Offsets:**")
            third_x_offset = st.number_input("Third Trace X Offset", value=0.0, step=0.1)
            third_y_offset = st.number_input("Third Trace Y Offset", value=0.0, step=0.1)

            # Generate high-resolution plot button
            generate_high_res = st.button("Generate High-Resolution Plot", type="primary")

    # --- Plotting in the Right Column ---
    with col2:
        if primary_file_path:
            try:
                # Helper function to determine if file is Star Oddi
                def is_star_oddi_file(file_path, sensor_type=None):
                    file_extension = os.path.splitext(file_path)[1].lower()
                    sensor_type_lower = sensor_type.lower() if sensor_type else ''
                    return (file_extension in ['.dat', '.acc'] or 
                           ('star' in sensor_type_lower and 'oddi' in sensor_type_lower))

                # Process primary file
                st.write("**Debug Info:**")
                st.write(f"Sensor type from DB: '{file_row['sensor_type']}'")
                st.write(f"File extension: {os.path.splitext(primary_file_path)[1].lower()}")
                
                if is_star_oddi_file(primary_file_path, file_row['sensor_type']):
                    st.write("✅ Using Star Oddi parser for primary file")
                    primary_df = process_star_oddi_data(relative_path)
                else:
                    st.write("✅ Using RBR parser for primary file")
                    primary_df = process_rsk_data(primary_file_path)

                # Process overlay file
                overlay_df = None
                if overlay_file_path and overlay_relative_path:
                    if overlay_option == "Same Core":
                        overlay_sensor_type = overlay_file_row.iloc[0]['sensor_type']
                    elif overlay_option == "Different Core":
                        overlay_sensor_type = overlay_file_row.iloc[0]['sensor_type']
                    
                    if is_star_oddi_file(overlay_file_path, overlay_sensor_type):
                        st.write("✅ Using Star Oddi parser for overlay file")
                        overlay_df = process_star_oddi_data(overlay_relative_path)
                    else:
                        st.write("✅ Using RBR parser for overlay file")
                        overlay_df = process_rsk_data(overlay_file_path)

                # Process third file
                third_df = None
                if third_file_path and third_relative_path:
                    if is_star_oddi_file(third_file_path, third_file_row['sensor_type']):
                        st.write("✅ Using Star Oddi parser for third file")
                        third_df = process_star_oddi_data(third_relative_path)
                    else:
                        st.write("✅ Using RBR parser for third file")
                        third_df = process_rsk_data(third_file_path)

                if primary_df is not None:
                    st.subheader("Interactive Plotting")
                    max_points = st.slider("Max Points for Plotting", min_value=100, max_value=5000, value=1000, step=100)
                    
                    # Check what columns are available in the DataFrame
                    available_columns = primary_df.columns.tolist()
                    st.write(f"Available columns: {available_columns}")  # Debug info
                    
                    # Standard options that work for both RBR and Star Oddi
                    y_axis_options = ["Pressure (dbar)", "Sea Pressure (dbar)", "Depth (m)"]
                    
                    # Add Star Oddi specific options if available
                    star_oddi_options = []
                    if "Tilt X" in available_columns:
                        star_oddi_options = ["Tilt X", "Tilt Y", "Tilt Z", "Roll", "EAL"]
                        y_axis_options.extend(star_oddi_options)
                    
                    # Add acceleration options if available
                    acceleration_options = []
                    if "X_Acceleration" in available_columns:
                        acceleration_options = ["X_Acceleration", "Y_Acceleration", "Z_Acceleration", "Total_G"]
                        y_axis_options.extend(acceleration_options)
                    
                    if "Temperature (°C)" in available_columns:
                        y_axis_options.append("Temperature (°C)")
                    
                    # Dual plotting option
                    dual_plot_mode = st.checkbox("Enable Dual Parameter Plotting (Stacked)", 
                                                help="Plot two different parameters in vertically stacked plots sharing the same time axis")
                    
                    if dual_plot_mode:
                        # Two parameter selection
                        col_param1, col_param2 = st.columns(2)
                        
                        with col_param1:
                            y_axis_1 = st.selectbox("Primary Parameter (Top Plot):", 
                                                   options=y_axis_options, 
                                                   index=2,  # Default to Depth (m)
                                                   key="param1")
                        
                        with col_param2:
                            # Filter out the already selected parameter
                            secondary_options = [opt for opt in y_axis_options if opt != y_axis_1]
                            default_secondary = 0
                            # Smart default: if we have tilt data, default to Tilt X
                            if "Tilt X" in secondary_options:
                                default_secondary = secondary_options.index("Tilt X")
                            elif acceleration_options and acceleration_options[0] in secondary_options:
                                default_secondary = secondary_options.index(acceleration_options[0])
                            
                            y_axis_2 = st.selectbox("Secondary Parameter (Bottom Plot):", 
                                                   options=secondary_options,
                                                   index=default_secondary,
                                                   key="param2")
                        
                        # Generate dual plot
                        fig = plot_rbr_dual_stacked(
                            primary_df, overlay_df, third_df, 
                            y_axis_1=y_axis_1, y_axis_2=y_axis_2,
                            max_points=max_points, primary_core_name=selected_core_label,
                            overlay_x_offset=overlay_x_offset, overlay_y_offset=overlay_y_offset,
                            third_x_offset=third_x_offset, third_y_offset=third_y_offset
                        )
                        st.plotly_chart(fig, use_container_width=True)
                        
                    else:
                        # Single parameter plotting (existing functionality)
                        y_axis = st.selectbox("Select Parameter to Plot:", options=y_axis_options, index=2)
                        
                        fig = plot_rbr_downsampled(
                            primary_df, overlay_df, third_df, y_axis=y_axis, max_points=max_points, primary_core_name=selected_core_label
                        )
                        st.plotly_chart(fig, use_container_width=True)

                    # --- High-Resolution Plotting ---
                    st.subheader("High-Resolution Plot")
                    
                    # Generate high-resolution plot when button is clicked
                    if generate_high_res:
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
                    else:
                        st.info("Use the controls in the left sidebar to configure and generate a high-resolution plot.")
                        
            except Exception as e:
                st.error(f"An error occurred while processing the files: {e}")
                import traceback
                st.error(traceback.format_exc())  # Add full error traceback for debugging