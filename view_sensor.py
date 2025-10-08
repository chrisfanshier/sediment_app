import os
import streamlit as st
import pandas as pd
from db_util import get_connection, fetch_cores
from utils import process_rsk_data, process_star_oddi_data
from plotting import plot_rbr_downsampled, plot_rbr_high_resolution, plot_rbr_dual_stacked, plot_rbr_dual_stacked_flexible, plot_rbr_dual_high_resolution
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
                    
                    # Only calculate depth-based defaults if depth data exists and has valid values
                    if (temp_primary_df is not None and 
                        "Depth (m)" in temp_primary_df.columns and 
                        not temp_primary_df["Depth (m)"].isna().all()):
                        
                        max_depth_row = temp_primary_df.loc[temp_primary_df["Depth (m)"].idxmax()]
                        max_depth_time = max_depth_row["Timestamp"]
                        default_start_time = (max_depth_time - pd.Timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
                        default_end_time = (max_depth_time + pd.Timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
                    # If no depth data, leave defaults as empty strings
                        
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
                    
                    # Helper function to check if a column has actual data (not all NaN)
                    def has_valid_data(df, column):
                        return column in df.columns and not df[column].isna().all()
                    
                    # Build available options based on what's actually in the data with valid values
                    y_axis_options = []
                    
                    # Only add depth/pressure options if they have actual data
                    if has_valid_data(primary_df, "Depth (m)"):
                        y_axis_options.append("Depth (m)")
                    if has_valid_data(primary_df, "Pressure (dbar)"):
                        y_axis_options.append("Pressure (dbar)")
                    if has_valid_data(primary_df, "Sea Pressure (dbar)"):
                        y_axis_options.append("Sea Pressure (dbar)")
                    
                    # Add temperature if available and has data
                    if has_valid_data(primary_df, "Temperature (°C)"):
                        y_axis_options.append("Temperature (°C)")
                    
                    # Add Star Oddi tilt options if available and have data
                    tilt_options = []
                    for tilt_col in ["Tilt X", "Tilt Y", "Tilt Z", "Roll", "EAL"]:
                        if has_valid_data(primary_df, tilt_col):
                            tilt_options.append(tilt_col)
                            y_axis_options.append(tilt_col)
                    
                    # Add acceleration options if available and have data
                    acceleration_options = []
                    for acc_col in ["X_Acceleration", "Y_Acceleration", "Z_Acceleration", "Total_G"]:
                        if has_valid_data(primary_df, acc_col):
                            acceleration_options.append(acc_col)
                            y_axis_options.append(acc_col)
                    
                    # Show info about what type of data is available
                    data_types = []
                    if any(has_valid_data(primary_df, col) for col in ["Depth (m)", "Pressure (dbar)", "Sea Pressure (dbar)"]):
                        data_types.append("Depth/Pressure")
                    if tilt_options:
                        data_types.append("Tilt")
                    if acceleration_options:
                        data_types.append("Acceleration")
                    if has_valid_data(primary_df, "Temperature (°C)"):
                        data_types.append("Temperature")
                    
                    st.info(f"📊 **Available data types:** {', '.join(data_types) if data_types else 'None detected'}")
                    
                    # Error handling if no valid options
                    if not y_axis_options:
                        st.error("❌ No plottable parameters with valid data found in this file.")
                        st.write("**Possible issues:**")
                        st.write("- File may be corrupted or in wrong format")
                        st.write("- All data columns contain only NaN values")
                        st.write("- File parsing may have failed")
                        return
                    
                    # Dual plotting option
                    dual_plot_mode = st.checkbox("Enable Dual Parameter Plotting (Stacked)", 
                                                help="Plot two different parameters in vertically stacked plots sharing the same time axis")
                    
                    if dual_plot_mode:
                        # Only show dual plotting if we have at least 2 parameters
                        if len(y_axis_options) < 2:
                            st.warning("⚠️ Need at least 2 parameters with valid data for dual plotting. Only single plotting available.")
                            dual_plot_mode = False
                        else:
                            st.write("**Configure Dual Plot Parameters:**")
                            
                            # Create two columns for parameter configuration
                            col_param1, col_param2 = st.columns(2)
                            
                            with col_param1:
                                st.write("**Top Plot Configuration:**")
                                
                                # File selection for parameter 1
                                param1_file_source = st.radio("Data source for top plot:", 
                                                            ["Primary File", "Overlay File", "Third File"], 
                                                            key="param1_source")
                                
                                # Get the appropriate DataFrame and options for param1
                                if param1_file_source == "Primary File":
                                    param1_df = primary_df
                                    param1_options = y_axis_options
                                elif param1_file_source == "Overlay File" and overlay_df is not None:
                                    param1_df = overlay_df
                                    # Get available columns for overlay file
                                    param1_options = [col for col in y_axis_options if has_valid_data(overlay_df, col)]
                                elif param1_file_source == "Third File" and third_df is not None:
                                    param1_df = third_df
                                    # Get available columns for third file
                                    param1_options = [col for col in y_axis_options if has_valid_data(third_df, col)]
                                else:
                                    param1_df = primary_df
                                    param1_options = y_axis_options
                                    if param1_file_source != "Primary File":
                                        st.warning(f"⚠️ {param1_file_source} not available, using Primary File")
                                
                                # Parameter selection for param1
                                default_primary = 0
                                if "Depth (m)" in param1_options:
                                    default_primary = param1_options.index("Depth (m)")
                                
                                y_axis_1 = st.selectbox("Select Parameter:", 
                                                       options=param1_options, 
                                                       index=default_primary,
                                                       key="param1")
                            
                            with col_param2:
                                st.write("**Bottom Plot Configuration:**")
                                
                                # File selection for parameter 2
                                param2_file_source = st.radio("Data source for bottom plot:", 
                                                            ["Primary File", "Overlay File", "Third File"], 
                                                            key="param2_source")
                                
                                # Get the appropriate DataFrame and options for param2
                                if param2_file_source == "Primary File":
                                    param2_df = primary_df
                                    param2_options = y_axis_options
                                elif param2_file_source == "Overlay File" and overlay_df is not None:
                                    param2_df = overlay_df
                                    param2_options = [col for col in y_axis_options if has_valid_data(overlay_df, col)]
                                elif param2_file_source == "Third File" and third_df is not None:
                                    param2_df = third_df
                                    param2_options = [col for col in y_axis_options if has_valid_data(third_df, col)]
                                else:
                                    param2_df = primary_df
                                    param2_options = y_axis_options
                                    if param2_file_source != "Primary File":
                                        st.warning(f"⚠️ {param2_file_source} not available, using Primary File")
                                
                                # Filter out the already selected parameter if using same file
                                if param1_file_source == param2_file_source:
                                    param2_options = [opt for opt in param2_options if opt != y_axis_1]
                                
                                # Smart default for secondary parameter
                                default_secondary = 0
                                if tilt_options and tilt_options[0] in param2_options:
                                    default_secondary = param2_options.index(tilt_options[0])
                                elif acceleration_options and acceleration_options[0] in param2_options:
                                    default_secondary = param2_options.index(acceleration_options[0])
                                
                                if param2_options:  # Only show if options available
                                    y_axis_2 = st.selectbox("Select Parameter:", 
                                                           options=param2_options,
                                                           index=default_secondary,
                                                           key="param2")
                                else:
                                    st.error("No available parameters for second plot")
                                    dual_plot_mode = False
                            

                            if dual_plot_mode and param2_options:
                                # Generate dual plot with specified data sources
                                fig = plot_rbr_dual_stacked_flexible(
                                    param1_df, param2_df, 
                                    y_axis_1=y_axis_1, y_axis_2=y_axis_2,
                                    max_points=max_points, 
                                    param1_name=f"{param1_file_source} - {y_axis_1}",
                                    param2_name=f"{param2_file_source} - {y_axis_2}"
                                )
                                st.plotly_chart(fig, use_container_width=True)
                    
                    if not dual_plot_mode:
                        # Single parameter plotting (existing functionality)
                        # Smart default selection
                        default_index = 0
                        if "Depth (m)" in y_axis_options:
                            default_index = y_axis_options.index("Depth (m)")
                        
                        y_axis = st.selectbox("Select Parameter to Plot:", 
                                             options=y_axis_options, 
                                             index=default_index,
                                             key="y_axis_single")
                        
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
                                if dual_plot_mode and len(y_axis_options) >= 2:
                                    # Create high-resolution dual plot
                                    st.info("🔄 Generating high-resolution dual plot...")
                                    high_res_fig = plot_rbr_dual_high_resolution(
                                        param1_df, param2_df,
                                        y_axis_1=y_axis_1, y_axis_2=y_axis_2,
                                        start_time=start_time, end_time=end_time,
                                        param1_name=f"{param1_file_source} - {y_axis_1}",
                                        param2_name=f"{param2_file_source} - {y_axis_2}"
                                    )
                                else:
                                    # Single parameter high-resolution plot
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
                st.error(traceback.format_exc())

# Call the function to make it work as a page
if __name__ == "__main__":
    view_sensor_data()

