import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import os
from config import get_full_path
from db_util import get_connection
from sqlalchemy import text
from utils import process_rsk_data, process_star_oddi_data
import datetime

# Cache the sensor data loading function
@st.cache_data
def load_sensor_data(sensor_file_id):
    """Load sensor data from database and file"""
    with get_connection() as conn:
        query = text("""
            SELECT sf.*, c.core_name 
            FROM sensor_files sf 
            JOIN cores c ON sf.core_id = c.core_id 
            WHERE sf.file_id = :file_id
        """)
        sensor_info = conn.execute(query, {"file_id": sensor_file_id}).fetchone()
    
    if not sensor_info:
        return None, None
    
    relative_path = os.path.join(sensor_info.file_path, sensor_info.file_name)
    file_ext = os.path.splitext(sensor_info.file_name)[1].lower()
    sensor_type = sensor_info.sensor_type.lower() if sensor_info.sensor_type else ""
    
    try:
        if file_ext == '.rsk' or 'rbr' in sensor_type:
            df = process_rsk_data(relative_path)
        elif file_ext in ['.dat', '.acc'] or 'star-oddi' in sensor_type or 'staroddi' in sensor_type:
            df = process_star_oddi_data(relative_path)
        else:
            return None, None

        if df is not None:
            if 'datetime' not in df.columns:
                if 'Timestamp' in df.columns:
                    df['datetime'] = df['Timestamp']
                else:
                    df['datetime'] = pd.date_range(start='2024-01-01', periods=len(df), freq='1s')
            return df, sensor_info
        else:
            return None, None
    except Exception as e:
        st.error(f"Error loading sensor data: {e}")
        return None, None

@st.cache_data
def load_winch_data(winch_file_id):
    """Load winch data from database and file"""
    try:
        from utils import parse_winch_dat
        import json
        
        # Get file info from winch_data table
        with get_connection() as conn:
            query = text("SELECT file_name, file_path, settings FROM winch_data WHERE winch_file_id = :winch_file_id")
            file_info = conn.execute(query, {"winch_file_id": winch_file_id}).fetchone()
        
        if not file_info:
            return None, None
        
        # Parse the JSON settings
        try:
            settings = json.loads(file_info.settings) if file_info.settings else {}
        except json.JSONDecodeError:
            settings = {}
        
        # Construct full file path
        relative_path = os.path.join(file_info.file_path, file_info.file_name)
        full_file_path = get_full_path(relative_path)
        
        # Use the settings from the database
        if settings:
            parsing_settings = {
                "delimiter": settings.get("delimiter", ","),
                "header_lines": settings.get("header_lines", 0),
                "columns": settings.get("columns", []),
                "datetime_code": settings.get("datetime_code", "pd.to_datetime(df['datetime'])")
            }
            # Add numeric_columns if present in settings
            if "numeric_columns" in settings:
                parsing_settings["numeric_columns"] = settings["numeric_columns"]
        else:
            # Fallback settings
            file_ext = os.path.splitext(file_info.file_name)[1].lower()
            if file_ext == '.dat':
                parsing_settings = {
                    "delimiter": r"\s+",
                    "header_lines": 0,
                    "datetime_code": "pd.to_datetime(df[['year', 'month', 'day', 'hour', 'minute', 'second']])"
                }
            else:
                parsing_settings = {
                    "delimiter": ",",
                    "header_lines": 0,
                    "datetime_code": "pd.to_datetime(df['datetime'])"
                }
        
        df = parse_winch_dat(full_file_path, parsing_settings)
        return df, file_info
        
    except Exception as e:
        st.error(f"Error loading winch data: {e}")
        return None, None

@st.cache_data
def get_winch_parameters(winch_file_id):
    """Get available parameters from winch data"""
    df, _ = load_winch_data(winch_file_id)
    if df is None:
        return []
    
    # Get numeric columns for plotting (excluding datetime-related columns)
    exclude_cols = ['index', 'datetime', 'date', 'time', 'year', 'month', 'day', 'hour', 'minute', 'second']
    numeric_cols = [col for col in df.select_dtypes(include=['number']).columns 
                   if col.lower() not in exclude_cols]
    
    return sorted(numeric_cols)

def find_columns_to_plot(df, parameter):
    """Find columns to plot based on parameter selection"""
    if parameter == 'all':
        return [col for col in df.select_dtypes(include=['number']).columns 
                if col.lower() not in ['id', 'index']]
    else:
        # First try exact match
        cols_to_plot = [col for col in df.columns if col == parameter]
        # If no exact match, try case-insensitive exact match
        if not cols_to_plot:
            cols_to_plot = [col for col in df.columns if col.lower() == parameter.lower()]
        # If still no match, try substring match
        if not cols_to_plot:
            cols_to_plot = [col for col in df.columns if parameter.lower() in col.lower()]
        return cols_to_plot

def apply_offsets(df, x_offset, y_offset, global_x, global_y, parameter_cols):
    """Apply time and value offsets to dataframe"""
    df_offset = df.copy()
    
    # Apply time offset (x-axis)
    total_x_offset = x_offset + global_x
    if total_x_offset != 0:
        df_offset['datetime'] = df_offset['datetime'] + pd.Timedelta(seconds=total_x_offset)
    
    # Apply value offset (y-axis) to specified columns
    total_y_offset = y_offset + global_y
    if total_y_offset != 0:
        for col in parameter_cols:
            if col in df_offset.columns:
                df_offset[col] = df_offset[col] + total_y_offset
    
    return df_offset

def apply_zoom_filter(df, zoom_range):
    """Filter dataframe to zoom range"""
    if zoom_range is None:
        return df
    
    start_time, end_time = zoom_range
    mask = (df['datetime'] >= start_time) & (df['datetime'] <= end_time)
    df_filtered = df[mask].copy()
    return df_filtered

@st.cache_data
def create_export_dataframe(sensor_file_ids, additional_sensor_file_ids, parameter, additional_sensor_parameter, 
                           winch_file_id, winch_parameter, additional_winch_parameter, 
                           file_offsets, global_x_offset, global_y_offset, winch_x_offset, winch_y_offset,
                           max_points, enable_winch, additional_winch_plot, zoom_mode, zoom_range):
    """Create export dataframe with exactly what's being plotted (offset data only)"""
    
    export_data = []
    metadata = {
        'global_x_offset_seconds': global_x_offset,
        'global_y_offset': global_y_offset,
        'winch_x_offset_seconds': winch_x_offset,
        'winch_y_offset': winch_y_offset,
        'file_offsets': {}
    }
    
    # Collect main sensor data (exactly as plotted)
    for file_id in sensor_file_ids:
        df, info = load_sensor_data(file_id)
        if df is not None:
            cols_to_plot = find_columns_to_plot(df, parameter)
            
            # Apply offsets (same as plotting)
            if file_id in file_offsets:
                df = apply_offsets(df, 
                                file_offsets[file_id]['x'], 
                                file_offsets[file_id]['y'],
                                global_x_offset,
                                global_y_offset,
                                cols_to_plot)
                # Store offset info in metadata
                metadata['file_offsets'][info.file_name] = {
                    'x_seconds': file_offsets[file_id]['x'],
                    'y': file_offsets[file_id]['y']
                }
            
            # Apply zoom filter if in zoom mode (same as plotting)
            if zoom_mode and zoom_range:
                df = apply_zoom_filter(df, zoom_range)
            
            # Apply downsampling if not in zoom mode (same as plotting)
            if not zoom_mode and len(df) > max_points:
                step = max(1, len(df) // max_points)
                df = df.iloc[::step]
            
            # Create file identifier
            if info.sensor_location:
                file_identifier = f"{info.sensor_location}_{info.file_name}"
            else:
                file_identifier = info.file_name
            
            # Export plotted columns
            for col in cols_to_plot:
                if col in df.columns and not df[col].isna().all():
                    df_export = df[['datetime', col]].copy()
                    df_export.rename(columns={col: f"{file_identifier}_{col}"}, inplace=True)
                    export_data.append(df_export)
    
    # Collect additional sensor data (exactly as plotted)
    if additional_sensor_file_ids and additional_sensor_parameter:
        for file_id in additional_sensor_file_ids:
            df, info = load_sensor_data(file_id)
            if df is not None:
                cols_to_plot = find_columns_to_plot(df, additional_sensor_parameter)
                
                if file_id in file_offsets:
                    df = apply_offsets(df, 
                                    file_offsets[file_id]['x'], 
                                    file_offsets[file_id]['y'],
                                    global_x_offset,
                                    global_y_offset,
                                    cols_to_plot)
                    metadata['file_offsets'][f"ADD_{info.file_name}"] = {
                        'x_seconds': file_offsets[file_id]['x'],
                        'y': file_offsets[file_id]['y']
                    }
                
                if zoom_mode and zoom_range:
                    df = apply_zoom_filter(df, zoom_range)
                
                if not zoom_mode and len(df) > max_points:
                    step = max(1, len(df) // max_points)
                    df = df.iloc[::step]
                
                if info.sensor_location:
                    file_identifier = f"ADD_{info.sensor_location}_{info.file_name}"
                else:
                    file_identifier = f"ADD_{info.file_name}"
                
                for col in cols_to_plot:
                    if col in df.columns and not df[col].isna().all():
                        df_export = df[['datetime', col]].copy()
                        df_export.rename(columns={col: f"{file_identifier}_{col}"}, inplace=True)
                        export_data.append(df_export)
    
    # Collect winch data (exactly as plotted)
    if enable_winch and winch_file_id and winch_parameter:
        winch_df, winch_info = load_winch_data(winch_file_id)
        if winch_df is not None and winch_parameter in winch_df.columns:
            winch_df = apply_offsets(winch_df, winch_x_offset, winch_y_offset, 0, 0, [winch_parameter])
            
            if zoom_mode and zoom_range:
                winch_df = apply_zoom_filter(winch_df, zoom_range)
            
            if not zoom_mode and len(winch_df) > max_points:
                step = max(1, len(winch_df) // max_points)
                winch_df = winch_df.iloc[::step]
            
            df_winch_export = winch_df[['datetime', winch_parameter]].copy()
            df_winch_export.rename(columns={winch_parameter: f"WINCH_{winch_parameter}"}, inplace=True)
            export_data.append(df_winch_export)
    
    # Collect additional winch data (exactly as plotted)
    if additional_winch_plot and winch_file_id and additional_winch_parameter:
        winch_df, winch_info = load_winch_data(winch_file_id)
        if winch_df is not None and additional_winch_parameter in winch_df.columns:
            winch_df = apply_offsets(winch_df, winch_x_offset, winch_y_offset, 0, 0, [additional_winch_parameter])
            
            if zoom_mode and zoom_range:
                winch_df = apply_zoom_filter(winch_df, zoom_range)
            
            if not zoom_mode and len(winch_df) > max_points:
                step = max(1, len(winch_df) // max_points)
                winch_df = winch_df.iloc[::step]
            
            df_winch_export = winch_df[['datetime', additional_winch_parameter]].copy()
            df_winch_export.rename(columns={additional_winch_parameter: f"WINCH_ADD_{additional_winch_parameter}"}, inplace=True)
            export_data.append(df_winch_export)
    
    # Merge all data on datetime
    if export_data:
        final_export = export_data[0]
        for df_next in export_data[1:]:
            final_export = pd.merge(final_export, df_next, on='datetime', how='outer')
        
        # Sort by datetime
        final_export = final_export.sort_values('datetime').reset_index(drop=True)
        
        return final_export, metadata
    else:
        return pd.DataFrame(), metadata

def multiplot_sensor_data():
    """Main function for sensor data plotting - can be called from app.py or run standalone"""
    st.title("🌡️ Sensor Data Plotter")
    st.write("Overlay multiple sensor measurements with winch data")

    # Sidebar for controls
    with st.sidebar:
        st.header("📊 Data Selection")
        
        # Cruise selection
        # Only show cruises that have cores with sensor files
        with get_connection() as conn:
            query = text("""
                SELECT DISTINCT c.cruise_id, c.cruise_name, v.vessel_name
                FROM cruises c
                LEFT JOIN cores co ON c.cruise_id = co.cruise_id
                LEFT JOIN sensor_files sf ON co.core_id = sf.core_id
                LEFT JOIN vessels v ON c.vessel_id = v.vessel_id
                WHERE sf.file_id IS NOT NULL
                ORDER BY c.cruise_name
            """)
            cruises_with_sensors = pd.read_sql(query, conn)
        
        if cruises_with_sensors.empty:
            st.warning("No cruises found with sensor files")
            cruise_options = {}
        else:
            cruise_options = {
                f"{row['cruise_name']} - {row['vessel_name']}": row['cruise_id'] 
                for _, row in cruises_with_sensors.iterrows()
            }
        selected_cruise = st.selectbox("Select Cruise:", options=list(cruise_options.keys()))
        
        if selected_cruise:
            cruise_id = cruise_options[selected_cruise]
            
            # Core selection
            # Only show cores that have sensor files
            with get_connection() as conn:
                query = text("""
                    SELECT DISTINCT c.core_id, c.core_name 
                    FROM cores c
                    LEFT JOIN sensor_files sf ON c.core_id = sf.core_id
                    WHERE c.cruise_id = :cruise_id AND sf.file_id IS NOT NULL
                    ORDER BY c.core_name
                """)
                cores_df = pd.read_sql(query, conn, params={"cruise_id": cruise_id})
            
            if not cores_df.empty:
                core_options = {row['core_name']: row['core_id'] for _, row in cores_df.iterrows()}
                selected_core = st.selectbox("Select Core:", options=list(core_options.keys()))
                
                if selected_core:
                    core_id = core_options[selected_core]
                    
                    # Sensor files
                    with get_connection() as conn:
                        query = text("""
                            SELECT file_id, file_name, sensor_type, sensor_location 
                            FROM sensor_files WHERE core_id = :core_id ORDER BY file_name
                        """)
                        sensor_files_df = pd.read_sql(query, conn, params={"core_id": core_id})
                    
                    if not sensor_files_df.empty:
                        sensor_options = {
                            f"{row['file_name']} ({row['sensor_type']} - {row['sensor_location']})": row['file_id'] 
                            for _, row in sensor_files_df.iterrows()
                        }
                        selected_sensors = st.multiselect("Select Sensor Files:", options=list(sensor_options.keys()))
                        
                        if selected_sensors:
                            sensor_file_ids = [sensor_options[s] for s in selected_sensors]
                            
                            # Load data and get parameters
                            all_parameters = set()
                            for file_id in sensor_file_ids:
                                df, _ = load_sensor_data(file_id)
                                if df is not None:
                                    numeric_cols = [col for col in df.select_dtypes(include=['number']).columns 
                                                  if col.lower() not in ['id', 'index']]
                                    all_parameters.update(numeric_cols)
                            
                            if all_parameters:
                                parameter = st.selectbox("Select Parameter:", options=['all'] + sorted(list(all_parameters)))
                                
                                # Winch data controls
                                st.subheader("🔧 Winch Data")
                                enable_winch = st.checkbox("Enable Winch Data", value=False)
                                
                                if enable_winch:
                                    # Load winch files for this cruise
                                    with get_connection() as conn:
                                        query = text("""
                                            SELECT winch_file_id, file_name, start_time, end_time 
                                            FROM winch_data WHERE cruise_id = :cruise_id ORDER BY file_name
                                        """)
                                        winch_df = pd.read_sql(query, conn, params={"cruise_id": cruise_id})
                                    
                                    if not winch_df.empty:
                                        winch_options = {row['file_name']: row['winch_file_id'] for _, row in winch_df.iterrows()}
                                        selected_winch = st.selectbox("Winch File:", options=list(winch_options.keys()))
                                        
                                        if selected_winch:
                                            winch_file_id = winch_options[selected_winch]
                                            
                                            # Get actual winch parameters from the file
                                            winch_params = get_winch_parameters(winch_file_id)
                                            if winch_params:
                                                winch_parameter = st.selectbox("Winch Parameter:", options=winch_params)
                                            else:
                                                st.error("No parameters found in winch file")
                                                enable_winch = False

                            # Additional plot window controls
                            st.subheader("📈 Additional Plot Windows")
                            additional_sensor_plot = st.checkbox("Enable Additional Sensor Plot", value=False)
                            additional_winch_plot = st.checkbox("Enable Additional Winch Plot", value=False)
                            
                            # If additional sensor plot is enabled, allow parameter and file selection
                            if additional_sensor_plot:
                                st.write("**Additional Sensor Plot Configuration:**")
                                
                                # Independent file selection for additional sensor plot
                                additional_sensor_files = st.multiselect(
                                    "Additional Sensor Files:", 
                                    options=list(sensor_options.keys()),
                                    key="additional_sensor_files"
                                )
                                
                                if additional_sensor_files:
                                    additional_sensor_file_ids = [sensor_options[s] for s in additional_sensor_files]
                                    
                                    # Get parameters from the selected additional files
                                    additional_all_parameters = set()
                                    for file_id in additional_sensor_file_ids:
                                        df, _ = load_sensor_data(file_id)
                                        if df is not None:
                                            numeric_cols = [col for col in df.select_dtypes(include=['number']).columns 
                                                          if col.lower() not in ['id', 'index']]
                                            additional_all_parameters.update(numeric_cols)
                                    
                                    if additional_all_parameters:
                                        additional_sensor_parameter = st.selectbox(
                                            "Additional Sensor Parameter:", 
                                            options=['all'] + sorted(list(additional_all_parameters)),
                                            key="additional_sensor_param"
                                        )
                                    else:
                                        additional_sensor_parameter = None
                                        st.warning("No numeric parameters found in selected additional sensor files")
                                else:
                                    additional_sensor_file_ids = []
                                    additional_sensor_parameter = None
                                    st.info("Select files for additional sensor plot")
                            else:
                                additional_sensor_files = []
                                additional_sensor_file_ids = []
                                additional_sensor_parameter = None

                            # If additional winch plot is enabled, allow parameter selection
                            if additional_winch_plot and enable_winch and 'winch_params' in locals() and winch_params:
                                additional_winch_parameter = st.selectbox(
                                    "Additional Winch Parameter:", 
                                    options=[p for p in winch_params if p != winch_parameter],
                                    key="additional_winch_param"
                                )
                            else:
                                additional_winch_parameter = None

        # Add cache control section after sensor selection
        if 'selected_sensors' in locals() and selected_sensors:
            st.divider()
            st.subheader("🔄 Cache Control")
            
            col_cache1, col_cache2 = st.columns(2)
            
            with col_cache1:
                if st.button("Clear Data Cache", help="Clear cached sensor data to reload fresh from database"):
                    st.cache_data.clear()
                    st.success("✅ Cache cleared!")
                    st.rerun()
            
            with col_cache2:
                if st.button("Clear All Cache", help="Clear all cached data including parameters"):
                    st.cache_data.clear()
                    st.cache_resource.clear()
                    st.success("✅ All cache cleared!")
                    st.rerun()
            
            st.caption("💡 Use after updating sensor metadata in database")

    # Main plotting area
    if 'selected_sensors' in locals() and selected_sensors:
        
        col1, col2 = st.columns([3, 1])
        
        with col2:
            st.subheader("🔧 Plot Controls")
            
            # Zoom mode controls
            st.subheader("🔍 Zoom Mode")
            
            # Get time range from first sensor file (with offsets applied) - always calculate this
            first_df, _ = load_sensor_data(sensor_file_ids[0])
            if first_df is not None:
                # Apply offsets to get the actual time range
                cols_to_plot = find_columns_to_plot(first_df, parameter)
                if sensor_file_ids[0] in st.session_state.get('file_offsets', {}):
                    first_df_offset = apply_offsets(
                        first_df,
                        st.session_state['file_offsets'][sensor_file_ids[0]]['x'],
                        st.session_state['file_offsets'][sensor_file_ids[0]]['y'],
                        st.session_state.get('global_x_offset', 0.0),
                        st.session_state.get('global_y_offset', 0.0),
                        cols_to_plot
                    )
                else:
                    first_df_offset = first_df
                
                min_time = first_df_offset['datetime'].min()
                max_time = first_df_offset['datetime'].max()
                
                # Time window selection - ALWAYS visible
                st.write("**Select Zoom Time Window:**")
                st.caption("💡 Use the overview plot to identify time window, then adjust here")
                
                col_start, col_end = st.columns(2)
                
                with col_start:
                    st.write("**Start Time**")
                    default_start = min_time
                    start_date = st.date_input("Date:", value=default_start.date(), key="zoom_start_date")
                    start_hour = st.number_input("Hour:", min_value=0, max_value=23, value=default_start.hour, key="zoom_start_hour")
                    start_minute = st.number_input("Minute:", min_value=0, max_value=59, value=default_start.minute, key="zoom_start_minute")
                    start_second = st.number_input("Second:", min_value=0, max_value=59, value=default_start.second, key="zoom_start_second")
                
                with col_end:
                    st.write("**End Time**")
                    default_end = min_time + pd.Timedelta(minutes=10)
                    end_date = st.date_input("Date:", value=default_end.date(), key="zoom_end_date")
                    end_hour = st.number_input("Hour:", min_value=0, max_value=23, value=default_end.hour, key="zoom_end_hour")
                    end_minute = st.number_input("Minute:", min_value=0, max_value=59, value=default_end.minute, key="zoom_end_minute")
                    end_second = st.number_input("Second:", min_value=0, max_value=59, value=default_end.second, key="zoom_end_second")
                
                # Combine into datetime objects
                zoom_start = pd.to_datetime(f"{start_date} {start_hour:02d}:{start_minute:02d}:{start_second:02d}")
                zoom_end = pd.to_datetime(f"{end_date} {end_hour:02d}:{end_minute:02d}:{end_second:02d}")
                zoom_range = [zoom_start, zoom_end]
                
                # Show time span
                time_span_seconds = (zoom_end - zoom_start).total_seconds()
                time_span_minutes = time_span_seconds / 60
                st.info(f"⏰ Selected window: {time_span_minutes:.1f} minutes ({time_span_seconds:.0f} seconds)")
                
                # Zoom mode checkbox AFTER time selection
                zoom_mode = st.checkbox("🔍 Enable Zoom Mode (Plot All Points in Window)", value=False)
                
                if zoom_mode:
                    st.success("✅ Zoom mode active - plotting all points in selected window")
                    st.warning("⚠️ Large time windows may be slow to render")
                else:
                    # Downsampling controls (only in overview mode)
                    max_points = st.number_input(
                        "Max Points per File:", 
                        min_value=100, 
                        max_value=50000, 
                        value=5000, 
                        step=500
                    )
                    st.info(f"📊 Overview mode: Max {max_points:,} points per file")
            else:
                zoom_range = None
                zoom_mode = False
                st.error("Could not load data to determine time range")
                max_points = st.number_input(
                    "Max Points per File:", 
                    min_value=100, 
                    max_value=50000, 
                    value=5000, 
                    step=500
                )

            # Trace Offsets
            st.subheader("⚡ Trace Offsets")
            
            # Global offset controls
            st.write("**Global Offsets:**")
            global_x_offset = st.number_input("Global X Offset (seconds):", value=0.0, step=0.1, format="%.2f", key="widget_global_x_offset")
            global_y_offset = st.number_input("Global Y Offset:", value=0.0, step=0.1, format="%.2f", key="widget_global_y_offset")
            
            # Store in session state with different keys (for use in zoom mode calculation)
            st.session_state['global_x_offset'] = global_x_offset
            st.session_state['global_y_offset'] = global_y_offset
            
            # Individual file offsets
            st.write("**Individual Sensor File Offsets:**")
            file_offsets = {}
            
            # Initialize session state for file offsets if not exists
            if 'file_offsets' not in st.session_state:
                st.session_state['file_offsets'] = {}
            
            # Main sensor files
            st.write("*Main Sensor Files:*")
            for i, file_id in enumerate(sensor_file_ids):
                df, info = load_sensor_data(file_id)
                if df is not None:
                    st.write(f"📊 {info.file_name}")
                    col_x, col_y = st.columns(2)
                    
                    with col_x:
                        x_offset = st.number_input(
                            f"X (sec):",
                            value=0.0,
                            step=0.01,
                            format="%.3f",
                            key=f"sensor_x_{file_id}"
                        )
                    
                    with col_y:
                        y_offset = st.number_input(
                            f"Y:",
                            value=0.0,
                            step=0.01,
                            format="%.3f",
                            key=f"sensor_y_{file_id}"
                        )
                    
                    file_offsets[file_id] = {'x': x_offset, 'y': y_offset}
                    st.session_state['file_offsets'][file_id] = {'x': x_offset, 'y': y_offset}
            
            # Additional sensor files offsets
            if additional_sensor_plot and 'additional_sensor_file_ids' in locals() and additional_sensor_file_ids:
                st.write("*Additional Sensor Files:*")
                for i, file_id in enumerate(additional_sensor_file_ids):
                    df, info = load_sensor_data(file_id)
                    if df is not None:
                        st.write(f"📊 {info.file_name} (Additional)")
                        col_x, col_y = st.columns(2)
                        
                        with col_x:
                            x_offset = st.number_input(
                                f"X (sec):",
                                value=0.0,
                                step=0.01,
                                format="%.3f",
                                key=f"additional_sensor_x_{file_id}"
                            )
                        
                        with col_y:
                            y_offset = st.number_input(
                                f"Y:",
                                value=0.0,
                                step=0.01,
                                format="%.3f",
                                key=f"additional_sensor_y_{file_id}"
                            )
                        
                        file_offsets[file_id] = {'x': x_offset, 'y': y_offset}
                        st.session_state['file_offsets'][file_id] = {'x': x_offset, 'y': y_offset}

            # Winch offset controls
            if enable_winch and 'winch_file_id' in locals():
                st.write("**Winch Offsets:**")
                col_wx, col_wy = st.columns(2)
                
                with col_wx:
                    winch_x_offset = st.number_input(
                        "Winch X (sec):",
                        value=0.0,
                        step=0.01,
                        format="%.3f",
                        key="winch_x_offset"
                    )
                
                with col_wy:
                    winch_y_offset = st.number_input(
                        "Winch Y:",
                        value=0.0,
                        step=0.01,
                        format="%.3f",
                        key="winch_y_offset"
                    )
            else:
                winch_x_offset = 0.0
                winch_y_offset = 0.0

            # Export functionality
            st.subheader("💾 Export Data")
            
            # Create export metadata info
            export_info_text = f"""
            **Export will include:**
            - 📅 Datetime column (common time axis)
            - 📊 Main sensor files: {len(sensor_file_ids)} files, parameter: {parameter}
            """
            
            if additional_sensor_plot and 'additional_sensor_file_ids' in locals() and additional_sensor_file_ids:
                export_info_text += f"\n- 📊 Additional sensor files: {len(additional_sensor_file_ids)} files, parameter: {additional_sensor_parameter}"
            
            if enable_winch and 'winch_parameter' in locals():
                export_info_text += f"\n- 🔧 Winch data: {winch_parameter}"
                
            if additional_winch_plot and 'additional_winch_parameter' in locals() and additional_winch_parameter:
                export_info_text += f"\n- 🔧 Additional winch data: {additional_winch_parameter}"
            
            export_info_text += f"\n- ⚡ Both original and offset values for all traces"
            
            if zoom_mode:
                export_info_text += f"\n- 🔍 Zoom mode: All points in selected window"
            else:
                export_info_text += f"\n- 📊 Overview mode: Max {max_points:,} points per file"
            
            st.info(export_info_text)
            
            # Export button
            if st.button("📊 Generate Export Data", type="primary"):
                with st.spinner("Preparing export data..."):
                    try:
                        # Create the export dataframe
                        export_df, metadata = create_export_dataframe(
                            sensor_file_ids=sensor_file_ids,
                            additional_sensor_file_ids=additional_sensor_file_ids if additional_sensor_plot else [],
                            parameter=parameter,
                            additional_sensor_parameter=additional_sensor_parameter if additional_sensor_plot else None,
                            winch_file_id=winch_file_id if enable_winch else None,
                            winch_parameter=winch_parameter if enable_winch else None,
                            additional_winch_parameter=additional_winch_parameter if additional_winch_plot else None,
                            file_offsets=file_offsets,
                            global_x_offset=global_x_offset,
                            global_y_offset=global_y_offset,
                            winch_x_offset=winch_x_offset,
                            winch_y_offset=winch_y_offset,
                            max_points=max_points if not zoom_mode else 1000000,
                            enable_winch=enable_winch,
                            additional_winch_plot=additional_winch_plot,
                            zoom_mode=zoom_mode,
                            zoom_range=zoom_range if zoom_mode else None
                        )
                        
                        if not export_df.empty:
                            # Store in session state
                            st.session_state['export_df'] = export_df
                            st.session_state['export_metadata'] = metadata
                            st.success(f"✅ Export data ready!")
                            st.success(f"📊 **{len(export_df):,} rows** × **{len(export_df.columns):,} columns**")
                            
                            # Show metadata info
                            st.info(f"📈 **Offset-adjusted data** (as seen in plot)")
                            
                        else:
                            st.error("❌ No data to export. Check your selections.")
                            
                    except Exception as e:
                        st.error(f"❌ Export failed: {str(e)}")
            
            # Download section
            if 'export_df' in st.session_state and not st.session_state['export_df'].empty:
                export_df = st.session_state['export_df']
                metadata = st.session_state.get('export_metadata', {})
                
                # Generate filename with metadata
                timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
                core_name = selected_core.replace(' ', '_') if 'selected_core' in locals() else 'unknown'
                cruise_name = selected_cruise.split(' - ')[0].replace(' ', '_') if 'selected_cruise' in locals() else 'unknown'
                
                filename = f"sensor_export_{cruise_name}_{core_name}_{parameter}_{timestamp}.csv"
                
                # Create CSV with metadata header
                import io
                csv_buffer = io.StringIO()
                
                # Write metadata as comments
                csv_buffer.write(f"# Export from Sediment App - {timestamp}\n")
                csv_buffer.write(f"# Cruise: {selected_cruise}\n")
                csv_buffer.write(f"# Core: {selected_core}\n")
                csv_buffer.write(f"# Parameter: {parameter}\n")
                if zoom_mode:
                    csv_buffer.write(f"# Mode: Zoom (all points in window)\n")
                    csv_buffer.write(f"# Zoom range: {zoom_range[0]} to {zoom_range[1]}\n")
                else:
                    csv_buffer.write(f"# Mode: Overview (downsampled to max {max_points} points)\n")
                csv_buffer.write(f"# Global X offset: {metadata['global_x_offset_seconds']} seconds\n")
                csv_buffer.write(f"# Global Y offset: {metadata['global_y_offset']}\n")
                csv_buffer.write(f"# Winch X offset: {metadata['winch_x_offset_seconds']} seconds\n")
                csv_buffer.write(f"# Winch Y offset: {metadata['winch_y_offset']}\n")
                if metadata['file_offsets']:
                    csv_buffer.write(f"# Individual file offsets:\n")
                    for fname, offsets in metadata['file_offsets'].items():
                        csv_buffer.write(f"#   {fname}: X={offsets['x_seconds']}s, Y={offsets['y']}\n")
                csv_buffer.write(f"# NOTE: All data is OFFSET-ADJUSTED (as displayed in plot)\n")
                csv_buffer.write("#\n")
                
                # Write the actual data
                export_df.to_csv(csv_buffer, index=False, float_format='%.6f')
                csv_data = csv_buffer.getvalue()
                
                # Download button
                st.download_button(
                    label="📥 Download CSV Export",
                    data=csv_data,
                    file_name=filename,
                    mime="text/csv",
                    type="primary"
                )
                
                # Show preview in expandable section
                with st.expander("👀 Preview Export Data"):
                    st.write(f"**Shape:** {export_df.shape[0]:,} rows × {export_df.shape[1]:,} columns")
                    st.write(f"**Time range:** {export_df['datetime'].min()} to {export_df['datetime'].max()}")
                    
                    # Show column names organized by type
                    data_cols = [col for col in export_df.columns if col != 'datetime']
                    original_cols = [col for col in data_cols if col.endswith('_original')]
                    offset_cols = [col for col in data_cols if col.endswith('_offset')]
                    
                    col_preview1, col_preview2 = st.columns(2)
                    with col_preview1:
                        st.write("**Original Data Columns:**")
                        for col in original_cols:
                            st.write(f"- {col}")
                    
                    with col_preview2:
                        st.write("**Offset Data Columns:**")
                        for col in offset_cols:
                            st.write(f"- {col}")
                    
                    # Show first few rows
                    st.write("**First 10 rows:**")
                    st.dataframe(export_df.head(10), use_container_width=True)
                    
                    # Show data statistics
                    st.write("**Data Summary:**")
                    numeric_cols = export_df.select_dtypes(include=['number']).columns
                    if len(numeric_cols) > 0:
                        summary_stats = export_df[numeric_cols].describe()
                        st.dataframe(summary_stats, use_container_width=True)
        
        with col1:
            # Determine subplot configuration
            subplot_count = 1  # Main sensor plot
            
            if enable_winch and 'selected_winch' in locals() and 'winch_parameter' in locals():
                subplot_count += 1  # Main winch plot
            
            if additional_sensor_plot and 'additional_sensor_file_ids' in locals() and additional_sensor_file_ids and 'additional_sensor_parameter' in locals() and additional_sensor_parameter:
                subplot_count += 1  # Additional sensor plot
                
            if additional_winch_plot and 'additional_winch_parameter' in locals() and additional_winch_parameter:
                subplot_count += 1  # Additional winch plot
            
            # Get core name for main title
            if 'selected_core' in locals() and selected_core:
                main_title = selected_core
            else:
                main_title = "Sensor Data Plot"
            
            # Create subplots
            if subplot_count == 1:
                # Single plot
                fig = go.Figure()
                
                colors = ['blue', 'red', 'green', 'orange', 'purple', 'brown', 'pink', 'gray']
                for i, file_id in enumerate(sensor_file_ids):
                    df, info = load_sensor_data(file_id)
                    if df is not None:
                        # Get columns to plot
                        cols_to_plot = find_columns_to_plot(df, parameter)
                        
                        # Apply offsets
                        if file_id in file_offsets:
                            df = apply_offsets(df, 
                                             file_offsets[file_id]['x'], 
                                             file_offsets[file_id]['y'],
                                             global_x_offset,
                                             global_y_offset,
                                             cols_to_plot)
        
                        # Apply zoom filter if in zoom mode
                        if zoom_mode and zoom_range:
                            df = apply_zoom_filter(df, zoom_range)
        
                        # Apply downsampling if not in zoom mode
                        if not zoom_mode and len(df) > max_points:
                            step = max(1, len(df) // max_points)
                            df = df.iloc[::step]
                        elif zoom_mode and len(df) > 200000:  # Safety limit for zoom mode
                            st.warning(f"⚠️ Large dataset in zoom mode ({len(df):,} points). Consider narrowing time window.")
                            df = df.iloc[::2]
                        
                        color = colors[i % len(colors)]  # MOVED OUTSIDE the cols_to_plot loop

                        for col in cols_to_plot:
                            if col in df.columns and not df[col].isna().all():
                                if info.sensor_location:
                                    legend_name = f"{info.sensor_location}: {col}"
                                else:
                                    legend_name = f"{info.file_name}: {col}"
                            
                            fig.add_trace(
                                go.Scatter(
                                    x=df['datetime'], y=df[col],
                                    name=legend_name,
                                    line=dict(color=color, width=2),
                                    opacity=0.8
                                )
                            )
                
                fig.update_layout(
                    height=600,
                    hovermode='x unified',
                    showlegend=True,
                    title=main_title,
                    template="plotly_white",
                    xaxis_title="Time",
                    yaxis_title=f"{parameter}"
                )
                
                if parameter and 'depth' in parameter.lower():
                    fig.update_yaxes(autorange="reversed")
            
            else:
                # Multiple subplots
                if subplot_count == 2:
                    row_heights = [0.6, 0.4]
                elif subplot_count == 3:
                    row_heights = [0.4, 0.3, 0.3]
                elif subplot_count == 4:
                    row_heights = [0.3, 0.25, 0.25, 0.2]
                else:
                    row_heights = [1.0/subplot_count] * subplot_count
                
                fig = make_subplots(
                    rows=subplot_count, cols=1,
                    shared_xaxes=True,
                    vertical_spacing=0.02,
                    row_heights=row_heights
                )
                
                current_row = 1
                
                # Main sensor plot
                colors = ['blue', 'red', 'green', 'orange', 'purple', 'brown', 'pink', 'gray']
                for i, file_id in enumerate(sensor_file_ids):
                    df, info = load_sensor_data(file_id)
                    if df is not None:
                        cols_to_plot = find_columns_to_plot(df, parameter)
                        
                        if file_id in file_offsets:
                            df = apply_offsets(df, 
                                             file_offsets[file_id]['x'], 
                                             file_offsets[file_id]['y'],
                                             global_x_offset,
                                             global_y_offset,
                                             cols_to_plot)
                        
                        # Apply zoom filter if in zoom mode
                        if zoom_mode and zoom_range:
                            df = apply_zoom_filter(df, zoom_range)
                        
                        # Apply downsampling if not in zoom mode
                        if not zoom_mode and len(df) > max_points:
                            step = max(1, len(df) // max_points)
                            df = df.iloc[::step]
                        elif zoom_mode and len(df) > 200000:  # Safety limit
                            df = df.iloc[::2]

                        color = colors[i % len(colors)]

                        for col in cols_to_plot:
                            if col in df.columns and not df[col].isna().all():
                                if info.sensor_location:
                                    legend_name = f"{info.sensor_location}: {col}"
                                else:
                                    legend_name = f"{info.file_name}: {col}"
                            
                                fig.add_trace(
                                    go.Scatter(
                                        x=df['datetime'], y=df[col],
                                        name=legend_name,
                                        line=dict(color=color, width=2),
                                        opacity=0.8,
                                        legendgroup="main_sensor"
                                    ), row=current_row, col=1
                                )
                
                fig.update_yaxes(title_text=f"{parameter}", row=current_row, col=1)
                if parameter and 'depth' in parameter.lower():
                    fig.update_yaxes(autorange="reversed", row=current_row, col=1)
                
                current_row += 1
                
                # Main winch plot
                if enable_winch and 'selected_winch' in locals() and 'winch_parameter' in locals():
                    winch_df, winch_info = load_winch_data(winch_file_id)
                    if winch_df is not None and winch_parameter in winch_df.columns:
                        winch_df = apply_offsets(winch_df, winch_x_offset, winch_y_offset, 0, 0, [winch_parameter])
                        
                        # Apply zoom filter if in zoom mode
                        if zoom_mode and zoom_range:
                            winch_df = apply_zoom_filter(winch_df, zoom_range)
                        
                        # Apply downsampling if not in zoom mode
                        if not zoom_mode and len(winch_df) > max_points:
                            step = max(1, len(winch_df) // max_points)
                            winch_df = winch_df.iloc[::step]
                        elif zoom_mode and len(winch_df) > 200000:  # Safety limit
                            winch_df = winch_df.iloc[::2]

                        fig.add_trace(
                            go.Scatter(
                                x=winch_df['datetime'], y=winch_df[winch_parameter],
                                name=f"Winch: {winch_parameter}",
                                line=dict(color='purple', width=2),
                                opacity=0.8,
                                legendgroup="main_winch"
                            ), row=current_row, col=1
                        )
                    
                    fig.update_yaxes(title_text=f"{winch_parameter}", row=current_row, col=1)
                    current_row += 1
                
                # Additional sensor plot
                if additional_sensor_plot and 'additional_sensor_file_ids' in locals() and additional_sensor_file_ids and 'additional_sensor_parameter' in locals() and additional_sensor_parameter:
                    additional_colors = ['darkblue', 'darkred', 'darkgreen', 'darkorange', 'indigo', 'maroon', 'hotpink', 'dimgray']
                    for i, file_id in enumerate(additional_sensor_file_ids):
                        df, info = load_sensor_data(file_id)
                        if df is not None:
                            cols_to_plot = find_columns_to_plot(df, additional_sensor_parameter)
                            
                            if file_id in file_offsets:
                                df = apply_offsets(df, 
                                                 file_offsets[file_id]['x'], 
                                                 file_offsets[file_id]['y'],
                                                 global_x_offset,
                                                 global_y_offset,
                                                 cols_to_plot)
            
                            # Apply zoom filter if in zoom mode
                            if zoom_mode and zoom_range:
                                df = apply_zoom_filter(df, zoom_range)
        
                            # Apply downsampling if not in zoom mode
                            if not zoom_mode and len(df) > max_points:
                                step = max(1, len(df) // max_points)
                                df = df.iloc[::step]
                            elif zoom_mode and len(df) > 200000:  # Safety limit
                                df = df.iloc[::2]

                            color = additional_colors[i % len(additional_colors)]

                            for col in cols_to_plot:
                                if col in df.columns and not df[col].isna().all():
                                    if info.sensor_location:
                                        legend_name = f"Add. {info.sensor_location}: {col}"
                                    else:
                                        legend_name = f"Add. {info.file_name}: {col}"
                
                                    fig.add_trace(
                                        go.Scatter(
                                            x=df['datetime'], y=df[col],
                                            name=legend_name,
                                            line=dict(color=color, width=2),
                                            opacity=0.8,
                                            legendgroup="additional_sensor"
                                        ), row=current_row, col=1
                                    )
                    
                    fig.update_yaxes(title_text=f"{additional_sensor_parameter}", row=current_row, col=1)
                    if additional_sensor_parameter and 'depth' in additional_sensor_parameter.lower():
                        fig.update_yaxes(autorange="reversed", row=current_row, col=1)
                    
                    current_row += 1
                
                # Additional winch plot
                if additional_winch_plot and 'additional_winch_parameter' in locals() and additional_winch_parameter:
                    winch_df, winch_info = load_winch_data(winch_file_id)
                    if winch_df is not None and additional_winch_parameter in winch_df.columns:
                        winch_df = apply_offsets(winch_df, winch_x_offset, winch_y_offset, 0, 0, [additional_winch_parameter])
                        
                        # Apply zoom filter if in zoom mode
                        if zoom_mode and zoom_range:
                            winch_df = apply_zoom_filter(winch_df, zoom_range)
                        
                        # Apply downsampling if not in zoom mode
                        if not zoom_mode and len(winch_df) > max_points:
                            step = max(1, len(winch_df) // max_points)
                            winch_df = winch_df.iloc[::step]
                        elif zoom_mode and len(winch_df) > 200000:  # Safety limit
                            winch_df = winch_df.iloc[::2]

                        fig.add_trace(
                            go.Scatter(
                                x=winch_df['datetime'], y=winch_df[additional_winch_parameter],
                                name=f"Add. Winch: {additional_winch_parameter}",
                                line=dict(color='darkmagenta', width=2),
                                opacity=0.8,
                                legendgroup="additional_winch"
                            ), row=current_row, col=1
                        )
                    
                    fig.update_yaxes(title_text=f"{additional_winch_parameter}", row=current_row, col=1)
                
                plot_height = 400 + (subplot_count * 150)
                fig.update_layout(
                    height=plot_height,
                    hovermode='x unified',
                    showlegend=True,
                    template="plotly_white",
                    title=main_title
                )
                
                fig.update_xaxes(title_text="Time", row=subplot_count, col=1)
            
            st.plotly_chart(fig, use_container_width=True)
        
        # Data info
        st.subheader("📊 Data Information")
        info_col1, info_col2, info_col3 = st.columns(3)
        
        with info_col1:
            st.metric("Parameter", parameter)
            st.metric("Sensor Files", len(selected_sensors))
            if additional_sensor_plot and 'additional_sensor_file_ids' in locals() and additional_sensor_file_ids:
                st.metric("Additional Sensor Files", len(additional_sensor_file_ids))
                st.metric("Additional Sensor Param", additional_sensor_parameter)
        
        with info_col2:
            if zoom_mode:
                st.metric("Mode", "🔍 Zoom (All Points)")
                if zoom_range:
                    time_span = (zoom_range[1] - zoom_range[0]).total_seconds() / 60
                    st.metric("Time Window", f"{time_span:.1f} min")
            else:
                st.metric("Mode", f"📊 Overview (max {max_points:,})")
            
            if enable_winch and 'selected_winch' in locals():
                st.metric("Winch Data", "Enabled")
                if additional_winch_plot and 'additional_winch_parameter' in locals() and additional_winch_parameter:
                    st.metric("Additional Winch Param", additional_winch_parameter)
            else:
                st.metric("Winch Data", "Disabled")
        
        with info_col3:
            total_points = 0
            for file_id in sensor_file_ids:
                df, _ = load_sensor_data(file_id)
                if df is not None:
                    total_points += len(df)
            
            st.metric("Total Data Points", f"{total_points:,}")
            
            subplot_info = f"{subplot_count} subplot(s)"
            if (additional_sensor_plot and 'additional_sensor_file_ids' in locals() and additional_sensor_file_ids) or (additional_winch_plot and 'additional_winch_parameter' in locals() and additional_winch_parameter):
                subplot_info += " (with additional plots)"
            st.metric("Plot Configuration", subplot_info)

    else:
        st.info("👆 Select cruise, core, and sensor files from the sidebar to begin plotting")
        
        with st.expander("ℹ️ About this application"):
            st.write("""
            This application allows you to:
            
            - **📊 Plot sensor data** from multiple files simultaneously
            - **🔗 Plot multiple windows with overlays of sensor data for a core or dredge
            - **🔧 Add winch data** for correlation analysis
            - **⚡ Apply offsets** to align data traces
            - **📉 Downsample data** for performance in overview mode
            - **🔍 Zoom mode** to view all points in a selected time window
            - **💾 Export aligned data** to CSV
            
            **Getting Started:**
            1. Select a cruise from the dropdown
            2. Choose a core or dredge containing sensor data
            3. Select one or more sensor files
            4. Pick a parameter to plot
            5. Adjust global/individual offsets as needed in overview mode
            6. Optionally enable zoom mode to see all points in a time window
            7. Optionally enable winch data overlay
            """)

# Run standalone
if __name__ == "__main__":
    st.set_page_config(page_title="Sensor Data Plotter", layout="wide")
    multiplot_sensor_data()