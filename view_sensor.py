import os
import streamlit as st
import pandas as pd
from db_util import get_connection, fetch_cores
from utils import process_rsk_data, process_star_oddi_data
from plotting import plot_rbr_downsampled, plot_rbr_high_resolution, plot_rbr_dual_simple, plot_rbr_dual_simple_high_res
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

        # --- Dual Plot Configuration ---
        st.divider()
        dual_plot_mode = st.checkbox("🔄 Enable Dual Stacked Plotting", 
                                    help="Create two vertically stacked plots with shared time axis")

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

        # --- Bottom Plot Configuration (only shown if dual plotting is enabled) ---
        if dual_plot_mode:
            with st.expander("Bottom Plot Configuration", expanded=True):
                st.write("**Configure data sources for the bottom stacked plot:**")
                
                # --- Bottom Primary File Selection ---
                bottom_selected_core_label = st.selectbox("Select Core for Bottom Plot:", list(core_options.keys()), key="bottom_core")
                bottom_selected_core_id = core_options[bottom_selected_core_label]

                # Fetch associated Sensor files for the bottom plot core
                with get_connection() as conn:
                    bottom_query = "SELECT file_name, file_path, sensor_type, sensor_location, remarks FROM sensor_files WHERE core_id = %s"
                    bottom_df_files = pd.read_sql(bottom_query, conn, params=(bottom_selected_core_id,))

                if not bottom_df_files.empty:
                    bottom_selected_file_label = st.selectbox("Select Bottom Plot Data File", bottom_df_files['file_name'], key="bottom_file")
                    bottom_file_row = bottom_df_files[bottom_df_files['file_name'] == bottom_selected_file_label].iloc[0]
                    
                    # Display bottom file metadata
                    if bottom_file_row['sensor_type']:
                        st.info(f"**Bottom File Sensor Type:** {bottom_file_row['sensor_type']}")
                    
                    # Combine file_path and file_name to create the full relative path
                    bottom_relative_path = os.path.join(bottom_file_row['file_path'], bottom_file_row['file_name'])
                    bottom_primary_file_path = get_full_path(bottom_relative_path)
                else:
                    st.warning("No sensor data file for this core.")
                    bottom_primary_file_path = None

                # --- Bottom Secondary File Selection ---
                st.subheader("Bottom Plot Overlay")
                bottom_overlay_option = st.radio("Select bottom overlay data source:", ["None", "Same Core", "Different Core"], key="bottom_overlay_option")
                bottom_overlay_file_path = None
                bottom_overlay_relative_path = None

                if bottom_overlay_option == "Same Core":
                    bottom_other_files = [file for file in bottom_df_files['file_name'] if file != bottom_selected_file_label]
                    if bottom_other_files:
                        bottom_overlay_file_label = st.selectbox("Select bottom overlay file from same core:", bottom_other_files, index=0, key="bottom_overlay_same")
                        bottom_overlay_file_row = bottom_df_files[bottom_df_files['file_name'] == bottom_overlay_file_label]
                        if not bottom_overlay_file_row.empty:
                            bottom_overlay_relative_path = os.path.join(bottom_overlay_file_row.iloc[0]['file_path'], bottom_overlay_file_row.iloc[0]['file_name'])
                            bottom_overlay_file_path = get_full_path(bottom_overlay_relative_path)
                        else:
                            st.warning("The selected bottom overlay file could not be found.")
                    else:
                        st.warning("No other files available for bottom overlay in the same core.")

                elif bottom_overlay_option == "Different Core":
                    bottom_overlay_core_label = st.selectbox("Select Core for Bottom Overlay:", list(core_options.keys()), key="bottom_overlay_core")
                    bottom_overlay_core_id = core_options[bottom_overlay_core_label]
                    with get_connection() as conn:
                        bottom_overlay_query = "SELECT file_name, file_path, sensor_type, sensor_location, remarks FROM sensor_files WHERE core_id = %s"
                        bottom_overlay_df_files = pd.read_sql(bottom_overlay_query, conn, params=(bottom_overlay_core_id,))
                    if not bottom_overlay_df_files.empty:
                        bottom_overlay_file_label = st.selectbox("Select Bottom Overlay File", bottom_overlay_df_files['file_name'], key="bottom_overlay_diff")
                        bottom_overlay_file_row = bottom_overlay_df_files[bottom_overlay_df_files['file_name'] == bottom_overlay_file_label]
                        if not bottom_overlay_file_row.empty:
                            bottom_overlay_relative_path = os.path.join(bottom_overlay_file_row.iloc[0]['file_path'], bottom_overlay_file_row.iloc[0]['file_name'])
                            bottom_overlay_file_path = get_full_path(bottom_overlay_relative_path)
                        else:
                            st.warning("The selected bottom overlay file could not be found.")
                    else:
                        st.warning("No sensor data files found for the selected core.")

                # --- Bottom Third Trace Selection ---
                st.subheader("Add Bottom Third Trace (Optional)")
                bottom_third_trace_option = st.radio("Add a bottom third data source?", ["None", "Select Core and File"], key="bottom_third_option")
                bottom_third_file_path = None
                bottom_third_relative_path = None
                if bottom_third_trace_option == "Select Core and File":
                    bottom_third_core_label = st.selectbox("Select Core for Bottom Third Trace:", list(core_options.keys()), key="bottom_third_core")
                    bottom_third_core_id = core_options[bottom_third_core_label]
                    with get_connection() as conn:
                        bottom_third_query = "SELECT file_name, file_path, sensor_type, sensor_location, remarks FROM sensor_files WHERE core_id = %s"
                        bottom_third_df_files = pd.read_sql(bottom_third_query, conn, params=(bottom_third_core_id,))
                    if not bottom_third_df_files.empty:
                        bottom_third_file_label = st.selectbox("Select Bottom Third Trace File", bottom_third_df_files['file_name'], key="bottom_third_file")
                        bottom_third_file_row = bottom_third_df_files[bottom_third_df_files['file_name'] == bottom_third_file_label].iloc[0]
                        bottom_third_relative_path = os.path.join(bottom_third_file_row['file_path'], bottom_third_file_row['file_name'])
                        bottom_third_file_path = get_full_path(bottom_third_relative_path)
        else:
            # Initialize bottom plot variables to None when dual mode is disabled
            bottom_primary_file_path = None
            bottom_overlay_file_path = None
            bottom_third_file_path = None
            bottom_relative_path = None
            bottom_overlay_relative_path = None
            bottom_third_relative_path = None
            bottom_file_row = None
            bottom_overlay_file_row = None
            bottom_third_file_row = None
            bottom_overlay_option = None
            bottom_selected_core_label = None

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
                        
                        # Process bottom plot files if dual mode is enabled
                        bottom_primary_df = None
                        bottom_overlay_df = None
                        bottom_third_df = None
                        
                        # Initialize bottom plot variables if not in dual mode
                        if 'dual_plot_mode' not in locals() or not dual_plot_mode:
                            bottom_primary_file_path = None
                            bottom_relative_path = None
                            bottom_overlay_file_path = None
                            bottom_overlay_relative_path = None
                            bottom_overlay_option = None
                            bottom_third_file_path = None
                            bottom_third_relative_path = None
                            bottom_file_row = None
                            bottom_overlay_file_row = None
                            bottom_third_file_row = None
                        
                        if dual_plot_mode and bottom_primary_file_path:
                            # Process bottom primary file
                            if is_star_oddi_file(bottom_primary_file_path, bottom_file_row['sensor_type']):
                                st.write("✅ Using Star Oddi parser for bottom primary file")
                                bottom_primary_df = process_star_oddi_data(bottom_relative_path)
                            else:
                                st.write("✅ Using RBR parser for bottom primary file")
                                bottom_primary_df = process_rsk_data(bottom_primary_file_path)

                            # Process bottom overlay file
                            if bottom_overlay_file_path and bottom_overlay_relative_path:
                                if bottom_overlay_option == "Same Core":
                                    bottom_overlay_sensor_type = bottom_overlay_file_row.iloc[0]['sensor_type']
                                elif bottom_overlay_option == "Different Core":
                                    bottom_overlay_sensor_type = bottom_overlay_file_row.iloc[0]['sensor_type']  # Fixed: was bottom_file_row
                                else:
                                    bottom_overlay_sensor_type = None
                                
                                if is_star_oddi_file(bottom_overlay_file_path, bottom_overlay_sensor_type):
                                    st.write("✅ Using Star Oddi parser for bottom overlay file")
                                    bottom_overlay_df = process_star_oddi_data(bottom_overlay_relative_path)
                                else:
                                    st.write("✅ Using RBR parser for bottom overlay file")
                                    bottom_overlay_df = process_rsk_data(bottom_overlay_file_path)

                            # Process bottom third file
                            if bottom_third_file_path and bottom_third_relative_path:
                                if is_star_oddi_file(bottom_third_file_path, bottom_third_file_row['sensor_type']):
                                    st.write("✅ Using Star Oddi parser for bottom third file")
                                    bottom_third_df = process_star_oddi_data(bottom_third_relative_path)
                                else:
                                    st.write("✅ Using RBR parser for bottom third file")
                                    bottom_third_df = process_rsk_data(bottom_third_file_path)
                        
                        # Helper function to get all available parameters from any DataFrame
                        def get_all_parameters(*dataframes):
                            all_params = set()
                            param_categories = {
                                'depth': ["Depth (m)", "Pressure (dbar)", "Sea Pressure (dbar)"],
                                'temperature': ["Temperature (°C)"],
                                'tilt': ["Tilt X", "Tilt Y", "Tilt Z", "Roll", "EAL"],
                                'acceleration': ["X_Acceleration", "Y_Acceleration", "Z_Acceleration", "Total_G"]
                            }
                            
                            for df in dataframes:
                                if df is not None:
                                    for category, params in param_categories.items():
                                        for param in params:
                                            if param in df.columns and not df[param].isna().all():
                                                all_params.add(param)
                            
                            return sorted(list(all_params))

                        # Get available parameters from top plot files
                        top_y_axis_options = get_all_parameters(primary_df, overlay_df, third_df)
                        
                        # Get available parameters from bottom plot files (if dual mode)
                        if dual_plot_mode and bottom_primary_df is not None:
                            bottom_y_axis_options = get_all_parameters(bottom_primary_df, bottom_overlay_df, bottom_third_df)
                        else:
                            bottom_y_axis_options = []

                        if dual_plot_mode and bottom_primary_df is not None:
                            # Dual plotting with separate file selections
                            st.write("**Parameter Selection:**")
                            col_top, col_bottom = st.columns(2)
                            
                            with col_top:
                                st.write("**Top Plot Parameter:**")
                                if top_y_axis_options:
                                    default_top_idx = 0
                                    if "Depth (m)" in top_y_axis_options:
                                        default_top_idx = top_y_axis_options.index("Depth (m)")
                                    
                                    top_y_axis = st.selectbox("Select Top Parameter:", 
                                                             options=top_y_axis_options, 
                                                             index=default_top_idx,
                                                             key="top_param")
                                else:
                                    st.error("No parameters available for top plot")
                                    top_y_axis = None
                            
                            with col_bottom:
                                st.write("**Bottom Plot Parameter:**")
                                if bottom_y_axis_options:
                                    # Smart default for bottom - prefer acceleration, then tilt, then depth
                                    default_bottom_idx = 0
                                    for preferred_param in ["Total_G", "X_Acceleration", "Tilt X", "Depth (m)"]:
                                        if preferred_param in bottom_y_axis_options:
                                            default_bottom_idx = bottom_y_axis_options.index(preferred_param)
                                            break
                                    
                                    bottom_y_axis = st.selectbox("Select Bottom Parameter:", 
                                                               options=bottom_y_axis_options, 
                                                               index=default_bottom_idx,
                                                               key="bottom_param")
                                else:
                                    st.error("No parameters available for bottom plot")
                                    bottom_y_axis = None
                            

                            if top_y_axis and bottom_y_axis:
                                # Show available data info
                                st.info(f"📊 **Top plot:** {len([df for df in [primary_df, overlay_df, third_df] if df is not None])} files available")
                                st.info(f"📊 **Bottom plot:** {len([df for df in [bottom_primary_df, bottom_overlay_df, bottom_third_df] if df is not None])} files available")
                                
                                # Generate dual stacked plot
                                fig = plot_rbr_dual_simple(
                                    # Top plot data
                                    primary_df, overlay_df, third_df, top_y_axis,
                                    # Bottom plot data  
                                    bottom_primary_df, bottom_overlay_df, bottom_third_df, bottom_y_axis,
                                    max_points=max_points,
                                    top_name=f"Top: {selected_core_label}",
                                    bottom_name=f"Bottom: {bottom_selected_core_label if 'bottom_selected_core_label' in locals() else 'Bottom Core'}"
                                )
                                st.plotly_chart(fig, use_container_width=True)
                        
                        else:
                            # Single parameter plotting (existing functionality)
                            if top_y_axis_options:
                                # Smart default selection
                                default_index = 0
                                if "Depth (m)" in top_y_axis_options:
                                    default_index = top_y_axis_options.index("Depth (m)")
                                
                                y_axis = st.selectbox("Select Parameter to Plot:", 
                                                     options=top_y_axis_options, 
                                                     index=default_index,
                                                     key="y_axis_single")
                                
                                fig = plot_rbr_downsampled(
                                    primary_df, overlay_df, third_df, y_axis=y_axis, max_points=max_points, primary_core_name=selected_core_label
                                )
                                st.plotly_chart(fig, use_container_width=True)
                            else:
                                st.error("❌ No plottable parameters found in any files.")

                        # --- High-Resolution Plotting ---
                        st.subheader("High-Resolution Plot")
                        
                        # Generate high-resolution plot when button is clicked
                        if generate_high_res:
                            if start_time and end_time:
                                try:
                                    if dual_plot_mode and bottom_primary_df is not None and top_y_axis and bottom_y_axis:
                                        # Create high-resolution dual plot
                                        high_res_fig = plot_rbr_dual_simple_high_res(
                                            # Top plot data
                                            primary_df, overlay_df, third_df, top_y_axis,
                                            # Bottom plot data  
                                            bottom_primary_df, bottom_overlay_df, bottom_third_df, bottom_y_axis,
                                            start_time=start_time, end_time=end_time,
                                            top_name=f"Top: {selected_core_label}",
                                            bottom_name=f"Bottom: {bottom_selected_core_label if 'bottom_selected_core_label' in locals() else 'Bottom Core'}"
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
            else:
                st.warning("Please select a sensor data file to visualize.")

# Call the function to make it work as a page
if __name__ == "__main__":
    view_sensor_data()

