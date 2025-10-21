import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import os
from db_util import get_connection, fetch_cruise_options
from sqlalchemy import text
from utils import process_rsk_data, process_star_oddi_data
import datetime

st.set_page_config(page_title="Sensor Data Plotter", layout="wide")

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
        full_file_path = os.path.join(file_info.file_path, file_info.file_name)
        
        # Use the settings from the database
        if settings:
            parsing_settings = {
                "delimiter": settings.get("delimiter", ","),
                "header_lines": settings.get("header_lines", 0),
                "columns": settings.get("columns", []),
                "datetime_code": settings.get("datetime_code", "pd.to_datetime(df['datetime'])")
            }
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

def apply_zoom_filter(df, zoom_range):
    """Apply zoom time range to filter dataframe"""
    if zoom_range and len(zoom_range) == 2:
        start_time, end_time = zoom_range
        if start_time and end_time:
            # Convert to pandas datetime if they're strings
            if isinstance(start_time, str):
                start_time = pd.to_datetime(start_time)
            if isinstance(end_time, str):
                end_time = pd.to_datetime(end_time)
            
            # Filter dataframe to zoom range
            df = df[(df['datetime'] >= start_time) & (df['datetime'] <= end_time)]
            
    return df

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

@st.cache_data
def create_export_dataframe(sensor_file_ids, additional_sensor_file_ids, parameter, additional_sensor_parameter, 
                           winch_file_id, winch_parameter, additional_winch_parameter, 
                           file_offsets, global_x_offset, global_y_offset, winch_x_offset, winch_y_offset,
                           detail_mode, zoom_range, max_points, enable_winch, additional_winch_plot):
    """Create export dataframe with all plotted data including original and offset values"""
    
    export_data = []
    
    # Collect main sensor data
    for file_id in sensor_file_ids:
        df, info = load_sensor_data(file_id)
        if df is not None:
            # Apply same filters as plotting
            if detail_mode and zoom_range:
                df = apply_zoom_filter(df, zoom_range)
            
            # Get columns to plot
            cols_to_plot = find_columns_to_plot(df, parameter)
            
            # Create original data columns
            for col in cols_to_plot:
                if col in df.columns and not df[col].isna().all():
                    df_export = df[['datetime', col]].copy()
                    
                    # Apply downsampling if not in detail mode
                    if not detail_mode and len(df_export) > max_points:
                        step = max(1, len(df_export) // max_points)
                        df_export = df_export.iloc[::step]
                    
                    # Rename column with file info
                    original_col_name = f"{info.file_name}_{col}_original"
                    df_export.rename(columns={col: original_col_name}, inplace=True)
                    export_data.append(df_export)
            
            # Create offset data columns
            if file_id in file_offsets:
                df_offset = apply_offsets(df, 
                                        file_offsets[file_id]['x'], 
                                        file_offsets[file_id]['y'],
                                        global_x_offset,
                                        global_y_offset,
                                        cols_to_plot)
                
                for col in cols_to_plot:
                    if col in df_offset.columns and not df_offset[col].isna().all():
                        df_export_offset = df_offset[['datetime', col]].copy()
                        
                        # Apply same downsampling
                        if not detail_mode and len(df_export_offset) > max_points:
                            step = max(1, len(df_export_offset) // max_points)
                            df_export_offset = df_export_offset.iloc[::step]
                        
                        # Rename column with offset info
                        offset_col_name = f"{info.file_name}_{col}_offset"
                        df_export_offset.rename(columns={col: offset_col_name}, inplace=True)
                        export_data.append(df_export_offset)
    
    # Collect additional sensor data
    if additional_sensor_file_ids and additional_sensor_parameter:
        for file_id in additional_sensor_file_ids:
            df, info = load_sensor_data(file_id)
            if df is not None:
                # Apply same filters as plotting
                if detail_mode and zoom_range:
                    df = apply_zoom_filter(df, zoom_range)
                
                # Get columns to plot
                cols_to_plot = find_columns_to_plot(df, additional_sensor_parameter)
                
                # Create original data columns
                for col in cols_to_plot:
                    if col in df.columns and not df[col].isna().all():
                        df_export = df[['datetime', col]].copy()
                        
                        # Apply downsampling if not in detail mode
                        if not detail_mode and len(df_export) > max_points:
                            step = max(1, len(df_export) // max_points)
                            df_export = df_export.iloc[::step]
                        
                        # Rename column with additional file info
                        original_col_name = f"ADD_{info.file_name}_{col}_original"
                        df_export.rename(columns={col: original_col_name}, inplace=True)
                        export_data.append(df_export)
                
                # Create offset data columns
                if file_id in file_offsets:
                    df_offset = apply_offsets(df, 
                                            file_offsets[file_id]['x'], 
                                            file_offsets[file_id]['y'],
                                            global_x_offset,
                                            global_y_offset,
                                            cols_to_plot)
                    
                    for col in cols_to_plot:
                        if col in df_offset.columns and not df_offset[col].isna().all():
                            df_export_offset = df_offset[['datetime', col]].copy()
                            
                            # Apply same downsampling
                            if not detail_mode and len(df_export_offset) > max_points:
                                step = max(1, len(df_export_offset) // max_points)
                                df_export_offset = df_export_offset.iloc[::step]
                            
                            # Rename column with offset info
                            offset_col_name = f"ADD_{info.file_name}_{col}_offset"
                            df_export_offset.rename(columns={col: offset_col_name}, inplace=True)
                            export_data.append(df_export_offset)
    
    # Collect winch data
    if enable_winch and winch_file_id and winch_parameter:
        winch_df, winch_info = load_winch_data(winch_file_id)
        if winch_df is not None and winch_parameter in winch_df.columns:
            # Apply same filters as plotting
            if detail_mode and zoom_range:
                winch_df = apply_zoom_filter(winch_df, zoom_range)
            
            # Original winch data
            df_winch_export = winch_df[['datetime', winch_parameter]].copy()
            
            # Apply downsampling if not in detail mode
            if not detail_mode and len(df_winch_export) > max_points:
                step = max(1, len(df_winch_export) // max_points)
                df_winch_export = df_winch_export.iloc[::step]
            
            # Rename column
            original_winch_col = f"WINCH_{winch_parameter}_original"
            df_winch_export.rename(columns={winch_parameter: original_winch_col}, inplace=True)
            export_data.append(df_winch_export)
            
            # Offset winch data
            winch_df_offset = apply_offsets(winch_df, winch_x_offset, winch_y_offset, 0, 0, [winch_parameter])
            df_winch_export_offset = winch_df_offset[['datetime', winch_parameter]].copy()
            
            # Apply same downsampling
            if not detail_mode and len(df_winch_export_offset) > max_points:
                step = max(1, len(df_winch_export_offset) // max_points)
                df_winch_export_offset = df_winch_export_offset.iloc[::step]
            
            # Rename column
            offset_winch_col = f"WINCH_{winch_parameter}_offset"
            df_winch_export_offset.rename(columns={winch_parameter: offset_winch_col}, inplace=True)
            export_data.append(df_winch_export_offset)
    
    # Collect additional winch data
    if additional_winch_plot and winch_file_id and additional_winch_parameter:
        winch_df, winch_info = load_winch_data(winch_file_id)
        if winch_df is not None and additional_winch_parameter in winch_df.columns:
            # Apply same filters as plotting
            if detail_mode and zoom_range:
                winch_df = apply_zoom_filter(winch_df, zoom_range)
            
            # Original additional winch data
            df_winch_export = winch_df[['datetime', additional_winch_parameter]].copy()
            
            # Apply downsampling if not in detail mode
            if not detail_mode and len(df_winch_export) > max_points:
                step = max(1, len(df_winch_export) // max_points)
                df_winch_export = df_winch_export.iloc[::step]
            
            # Rename column
            original_winch_col = f"WINCH_ADD_{additional_winch_parameter}_original"
            df_winch_export.rename(columns={additional_winch_parameter: original_winch_col}, inplace=True)
            export_data.append(df_winch_export)
            
            # Offset additional winch data
            winch_df_offset = apply_offsets(winch_df, winch_x_offset, winch_y_offset, 0, 0, [additional_winch_parameter])
            df_winch_export_offset = winch_df_offset[['datetime', additional_winch_parameter]].copy()
            
            # Apply same downsampling
            if not detail_mode and len(df_winch_export_offset) > max_points:
                step = max(1, len(df_winch_export_offset) // max_points)
                df_winch_export_offset = df_winch_export_offset.iloc[::step]
            
            # Rename column
            offset_winch_col = f"WINCH_ADD_{additional_winch_parameter}_offset"
            df_winch_export_offset.rename(columns={additional_winch_parameter: offset_winch_col}, inplace=True)
            export_data.append(df_winch_export_offset)
    
    # Merge all data on datetime
    if export_data:
        final_export = export_data[0]
        for df_next in export_data[1:]:
            final_export = pd.merge(final_export, df_next, on='datetime', how='outer')
        
        # Sort by datetime
        final_export = final_export.sort_values('datetime').reset_index(drop=True)
        
        return final_export
    else:
        return pd.DataFrame()

st.title("🌡️ Sensor Data Plotter")
st.write("Overlay multiple sensor measurements with winch data")

# Sidebar for controls
with st.sidebar:
    st.header("📊 Data Selection")
    
    # Cruise selection
    cruises = fetch_cruise_options()
    cruise_options = {f"{c.cruise_name} - {c.vessel_name}": c.cruise_id for c in cruises}
    selected_cruise = st.selectbox("Select Cruise:", options=list(cruise_options.keys()))
    
    if selected_cruise:
        cruise_id = cruise_options[selected_cruise]
        
        # Core selection
        with get_connection() as conn:
            query = text("SELECT core_id, core_name FROM cores WHERE cruise_id = :cruise_id ORDER BY core_name")
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
                            
                            # Time controls
                            st.subheader("⏰ Time Controls")
                            detail_mode = st.checkbox("🔍 Detail Mode (All Points)", value=False)
                            
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

# Main plotting area
if 'selected_sensors' in locals() and selected_sensors:
    
    # Add time range controls in main area
    col1, col2 = st.columns([3, 1])
    
    with col2:
        st.subheader("🔧 Plot Controls")
        
        # Detail mode controls
        if detail_mode:
            st.info("🔍 Detail mode: Focused view around max depth")
            
            # Find max depth automatically
            max_depth_time = None
            max_depth_value = None
            
            # Look for depth data in the selected files
            for file_id in sensor_file_ids:
                df, info = load_sensor_data(file_id)
                if df is not None:
                    # Find depth columns
                    depth_cols = [col for col in df.columns if 'depth' in col.lower()]
                    
                    for depth_col in depth_cols:
                        if not df[depth_col].isna().all():
                            max_idx = df[depth_col].idxmax()
                            if pd.notna(max_idx):
                                depth_val = df.loc[max_idx, depth_col]
                                depth_time = df.loc[max_idx, 'datetime']
                                
                                if max_depth_value is None or depth_val > max_depth_value:
                                    max_depth_value = depth_val
                                    max_depth_time = depth_time
                                    st.success(f"Found max depth: {depth_val:.2f} at {depth_time.strftime('%H:%M:%S')}")
            
            if max_depth_time is not None:
                # Default to 5 minutes before and after max depth
                default_start = max_depth_time - pd.Timedelta(minutes=5)
                default_end = max_depth_time + pd.Timedelta(minutes=5)
                
                # Manual time inputs with precise control
                st.write("**Adjust time window around max depth:**")
                
                col_start, col_end = st.columns(2)
                
                with col_start:
                    st.write("**Start Time**")
                    start_hour = st.number_input("Hour:", min_value=0, max_value=23, value=default_start.hour, key="start_hour")
                    start_minute = st.number_input("Minute:", min_value=0, max_value=59, value=default_start.minute, key="start_minute")
                    start_second = st.number_input("Second:", min_value=0, max_value=59, value=default_start.second, key="start_second")
                
                with col_end:
                    st.write("**End Time**")
                    end_hour = st.number_input("Hour:", min_value=0, max_value=23, value=default_end.hour, key="end_hour")
                    end_minute = st.number_input("Minute:", min_value=0, max_value=59, value=default_end.minute, key="end_minute")
                    end_second = st.number_input("Second:", min_value=0, max_value=59, value=default_end.second, key="end_second")
                
                # Combine into datetime objects
                start_date = default_start.date()
                end_date = default_end.date()
                
                detail_start = pd.to_datetime(f"{start_date} {start_hour:02d}:{start_minute:02d}:{start_second:02d}")
                detail_end = pd.to_datetime(f"{end_date} {end_hour:02d}:{end_minute:02d}:{end_second:02d}")
                zoom_range = [detail_start, detail_end]
                
                # Show the selected window
                time_span_seconds = (detail_end - detail_start).total_seconds()
                time_span_minutes = time_span_seconds / 60
                st.info(f"⏰ Time window: {time_span_minutes:.1f} minutes ({time_span_seconds:.0f} seconds)")
                st.info(f"🎯 Centered on max depth at {max_depth_time.strftime('%H:%M:%S')}")
                
            else:
                # Fallback if no depth data found
                st.warning("No depth data found. Using manual time selection.")
                
                # Get overall time range for fallback
                first_df, _ = load_sensor_data(sensor_file_ids[0])
                if first_df is not None:
                    min_time = first_df['datetime'].min()
                    max_time = first_df['datetime'].max()
                    
                    # Default to first 10 minutes
                    default_start = min_time
                    default_end = min_time + pd.Timedelta(minutes=10)
                    
                    col_start, col_end = st.columns(2)
                    
                    with col_start:
                        st.write("**Start Time**")
                        start_hour = st.number_input("Hour:", min_value=0, max_value=23, value=default_start.hour, key="manual_start_hour")
                        start_minute = st.number_input("Minute:", min_value=0, max_value=59, value=default_start.minute, key="manual_start_minute")
                        start_second = st.number_input("Second:", min_value=0, max_value=59, value=default_start.second, key="manual_start_second")
                    
                    with col_end:
                        st.write("**End Time**")
                        end_hour = st.number_input("Hour:", min_value=0, max_value=23, value=default_end.hour, key="manual_end_hour")
                        end_minute = st.number_input("Minute:", min_value=0, max_value=59, value=default_end.minute, key="manual_end_minute")
                        end_second = st.number_input("Second:", min_value=0, max_value=59, value=default_end.second, key="manual_end_second")
                    
                    # Combine into datetime objects
                    start_date = default_start.date()
                    end_date = default_end.date()
                    
                    detail_start = pd.to_datetime(f"{start_date} {start_hour:02d}:{start_minute:02d}:{start_second:02d}")
                    detail_end = pd.to_datetime(f"{end_date} {end_hour:02d}:{end_minute:02d}:{end_second:02d}")
                    zoom_range = [detail_start, detail_end]
                    
                    # Show time span
                    time_span_seconds = (detail_end - detail_start).total_seconds()
                    time_span_minutes = time_span_seconds / 60
                    st.info(f"⏰ Time window: {time_span_minutes:.1f} minutes ({time_span_seconds:.0f} seconds)")
                else:
                    zoom_range = None
        else:
            # Overview mode
            zoom_range = None
            max_points = st.number_input(
                "Max Points per File (Overview):", 
                min_value=100, 
                max_value=50000, 
                value=5000, 
                step=500
            )
            st.info(f"📊 Overview mode: Max {max_points:,} points per file")

        # Trace Offsets
        st.subheader("⚡ Trace Offsets")
        
        # Global offset controls
        st.write("**Global Offsets:**")
        global_x_offset = st.number_input("Global X Offset (seconds):", value=0.0, step=0.1, format="%.2f")
        global_y_offset = st.number_input("Global Y Offset:", value=0.0, step=0.1, format="%.2f")
        
        # Individual file offsets
        st.write("**Individual Sensor File Offsets:**")
        file_offsets = {}
        
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
        
        if detail_mode and 'zoom_range' in locals() and zoom_range:
            time_span_minutes = (zoom_range[1] - zoom_range[0]).total_seconds() / 60
            export_info_text += f"\n- ⏰ Time range: {time_span_minutes:.1f} minutes (detail mode)"
        else:
            export_info_text += f"\n- ⏰ Overview mode: max {max_points:,} points per file"
        
        st.info(export_info_text)
        
        # Export button
        if st.button("📊 Generate Export Data", type="primary"):
            with st.spinner("Preparing export data..."):
                try:
                    # Create the export dataframe
                    export_df = create_export_dataframe(
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
                        detail_mode=detail_mode,
                        zoom_range=zoom_range if detail_mode else None,
                        max_points=max_points if not detail_mode else 1000000,
                        enable_winch=enable_winch,
                        additional_winch_plot=additional_winch_plot
                    )
                    
                    if not export_df.empty:
                        # Store in session state
                        st.session_state['export_df'] = export_df
                        st.success(f"✅ Export data ready!")
                        st.success(f"📊 **{len(export_df):,} rows** × **{len(export_df.columns):,} columns**")
                        
                        # Show column summary
                        data_cols = [col for col in export_df.columns if col != 'datetime']
                        original_cols = [col for col in data_cols if col.endswith('_original')]
                        offset_cols = [col for col in data_cols if col.endswith('_offset')]
                        
                        st.info(f"📈 **{len(original_cols)} original** + **{len(offset_cols)} offset** data columns")
                        
                    else:
                        st.error("❌ No data to export. Check your selections.")
                        
                except Exception as e:
                    st.error(f"❌ Export failed: {str(e)}")
        
        # Download section
        if 'export_df' in st.session_state and not st.session_state['export_df'].empty:
            export_df = st.session_state['export_df']
            
            # Generate filename with metadata
            timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
            core_name = selected_core.replace(' ', '_') if 'selected_core' in locals() else 'unknown'
            cruise_name = selected_cruise.split(' - ')[0].replace(' ', '_') if 'selected_cruise' in locals() else 'unknown'
            
            filename = f"sensor_export_{cruise_name}_{core_name}_{parameter}_{timestamp}.csv"
            
            # Convert to CSV
            csv_data = export_df.to_csv(index=False, float_format='%.6f')
            
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
        
        # Create subplot titles
        subplot_titles = []
        subplot_titles.append(f"Sensor Data: {parameter}")
        
        if enable_winch and 'selected_winch' in locals():
            subplot_titles.append(f"Winch Data: {winch_parameter}")
            
        if additional_sensor_plot and 'additional_sensor_file_ids' in locals() and additional_sensor_file_ids and 'additional_sensor_parameter' in locals() and additional_sensor_parameter:
            subplot_titles.append(f"Additional Sensor: {additional_sensor_parameter}")
            
        if additional_winch_plot and 'additional_winch_parameter' in locals() and additional_winch_parameter:
            subplot_titles.append(f"Additional Winch: {additional_winch_parameter}")
        
        # Create subplots
        if subplot_count == 1:
            # Single plot
            fig = go.Figure()
            
            colors = ['blue', 'red', 'green', 'orange', 'purple', 'brown', 'pink', 'gray']
            for i, file_id in enumerate(sensor_file_ids):
                df, info = load_sensor_data(file_id)
                if df is not None:
                    # Apply zoom filter first if in detail mode
                    if detail_mode and 'zoom_range' in locals() and zoom_range:
                        df = apply_zoom_filter(df, zoom_range)
                    
                    # Get columns to plot
                    cols_to_plot = find_columns_to_plot(df, parameter)
                    
                    # Apply offsets BEFORE downsampling
                    if file_id in file_offsets:
                        df = apply_offsets(df, 
                                         file_offsets[file_id]['x'], 
                                         file_offsets[file_id]['y'],
                                         global_x_offset,
                                         global_y_offset,
                                         cols_to_plot)
                    
                    # Apply downsampling if not in detail mode
                    if not detail_mode and len(df) > max_points:
                        step = max(1, len(df) // max_points)
                        df = df.iloc[::step]
                    elif detail_mode and len(df) > 200000:  # Safety limit even in detail mode
                        st.warning(f"⚠️ Large dataset in detail mode. Sampling for performance.")
                        df = df.iloc[::2]
                        
                    color = colors[i % len(colors)]

                    for col in cols_to_plot:
                        if col in df.columns and not df[col].isna().all():
                            fig.add_trace(
                                go.Scatter(
                                    x=df['datetime'], y=df[col],
                                    name=f"{info.file_name}: {col}",
                                    line=dict(color=color, width=2),
                                    opacity=0.8
                                )
                            )
            
            # Configure layout for single plot
            fig.update_layout(
                height=600,
                hovermode='x unified',
                showlegend=True,
                title=f"Sensor Data: {parameter}",
                template="plotly_white",
                xaxis_title="Time",
                yaxis_title=f"Sensor: {parameter}"
            )
            
            # Invert y-axis if depth parameter
            if parameter and 'depth' in parameter.lower():
                fig.update_yaxes(autorange="reversed")
        
        else:
            # Multiple subplots
            # Calculate row heights based on subplot count
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
                row_heights=row_heights,
                subplot_titles=subplot_titles
            )
            
            current_row = 1
            
            # Main sensor plot (always first)
            colors = ['blue', 'red', 'green', 'orange', 'purple', 'brown', 'pink', 'gray']
            for i, file_id in enumerate(sensor_file_ids):
                df, info = load_sensor_data(file_id)
                if df is not None:
                    # Apply zoom filter first if in detail mode
                    if detail_mode and 'zoom_range' in locals() and zoom_range:
                        df = apply_zoom_filter(df, zoom_range)
                    
                    # Get columns to plot
                    cols_to_plot = find_columns_to_plot(df, parameter)
                    
                    # Apply offsets BEFORE downsampling
                    if file_id in file_offsets:
                        df = apply_offsets(df, 
                                         file_offsets[file_id]['x'], 
                                         file_offsets[file_id]['y'],
                                         global_x_offset,
                                         global_y_offset,
                                         cols_to_plot)
                    
                    # Apply downsampling if not in detail mode
                    if not detail_mode and len(df) > max_points:
                        step = max(1, len(df) // max_points)
                        df = df.iloc[::step]
                    elif detail_mode and len(df) > 200000:  # Safety limit even in detail mode
                        df = df.iloc[::2]

                    color = colors[i % len(colors)]

                    for col in cols_to_plot:
                        if col in df.columns and not df[col].isna().all():
                            fig.add_trace(
                                go.Scatter(
                                    x=df['datetime'], y=df[col],
                                    name=f"{info.file_name}: {col}",
                                    line=dict(color=color, width=2),
                                    opacity=0.8,
                                    legendgroup="main_sensor"
                                ), row=current_row, col=1
                            )
            
            fig.update_yaxes(title_text=f"Sensor: {parameter}", row=current_row, col=1)
            if parameter and 'depth' in parameter.lower():
                fig.update_yaxes(autorange="reversed", row=current_row, col=1)
            
            current_row += 1
            
            # Main winch plot
            if enable_winch and 'selected_winch' in locals() and 'winch_parameter' in locals():
                winch_df, winch_info = load_winch_data(winch_file_id)
                if winch_df is not None and winch_parameter in winch_df.columns:
                    # Apply zoom filter first if in detail mode
                    if detail_mode and 'zoom_range' in locals() and zoom_range:
                        winch_df = apply_zoom_filter(winch_df, zoom_range)
                    
                    # Apply winch offsets BEFORE downsampling
                    winch_df = apply_offsets(winch_df, winch_x_offset, winch_y_offset, 0, 0, [winch_parameter])
                    
                    # Apply downsampling if not in detail mode
                    if not detail_mode and len(winch_df) > max_points:
                        step = max(1, len(winch_df) // max_points)
                        winch_df = winch_df.iloc[::step]
                    elif detail_mode and len(winch_df) > 200000:  # Safety limit
                        winch_df = winch_df.iloc[::2]

                    fig.add_trace(
                        go.Scatter(
                            x=winch_df['datetime'], y=winch_df[winch_parameter],
                            name=f"🔧 Winch: {winch_parameter}",
                            line=dict(color='purple', width=2),
                            opacity=0.8,
                            legendgroup="main_winch"
                        ), row=current_row, col=1
                    )
                
                fig.update_yaxes(title_text=f"Winch: {winch_parameter}", row=current_row, col=1)
                current_row += 1
            
            # Additional sensor plot
            if additional_sensor_plot and 'additional_sensor_file_ids' in locals() and additional_sensor_file_ids and 'additional_sensor_parameter' in locals() and additional_sensor_parameter:
                additional_colors = ['darkblue', 'darkred', 'darkgreen', 'darkorange', 'indigo', 'maroon', 'hotpink', 'dimgray']
                for i, file_id in enumerate(additional_sensor_file_ids):
                    df, info = load_sensor_data(file_id)
                    if df is not None:
                        # Apply zoom filter first if in detail mode
                        if detail_mode and 'zoom_range' in locals() and zoom_range:
                            df = apply_zoom_filter(df, zoom_range)
                        
                        # Get columns to plot for additional parameter
                        cols_to_plot = find_columns_to_plot(df, additional_sensor_parameter)
                        
                        # Apply offsets BEFORE downsampling
                        if file_id in file_offsets:
                            df = apply_offsets(df, 
                                             file_offsets[file_id]['x'], 
                                             file_offsets[file_id]['y'],
                                             global_x_offset,
                                             global_y_offset,
                                             cols_to_plot)
                        
                        # Apply downsampling if not in detail mode
                        if not detail_mode and len(df) > max_points:
                            step = max(1, len(df) // max_points)
                            df = df.iloc[::step]
                        elif detail_mode and len(df) > 200000:  # Safety limit even in detail mode
                            df = df.iloc[::2]

                        color = additional_colors[i % len(additional_colors)]

                        for col in cols_to_plot:
                            if col in df.columns and not df[col].isna().all():
                                fig.add_trace(
                                    go.Scatter(
                                        x=df['datetime'], y=df[col],
                                        name=f"Add. {info.file_name}: {col}",
                                        line=dict(color=color, width=2),
                                        opacity=0.8,
                                        legendgroup="additional_sensor"
                                    ), row=current_row, col=1
                                )
                
                fig.update_yaxes(title_text=f"Add. Sensor: {additional_sensor_parameter}", row=current_row, col=1)
                if additional_sensor_parameter and 'depth' in additional_sensor_parameter.lower():
                    fig.update_yaxes(autorange="reversed", row=current_row, col=1)
                
                current_row += 1
            
            # Additional winch plot
            if additional_winch_plot and 'additional_winch_parameter' in locals() and additional_winch_parameter:
                winch_df, winch_info = load_winch_data(winch_file_id)
                if winch_df is not None and additional_winch_parameter in winch_df.columns:
                    # Apply zoom filter first if in detail mode
                    if detail_mode and 'zoom_range' in locals() and zoom_range:
                        winch_df = apply_zoom_filter(winch_df, zoom_range)
                    
                    # Apply winch offsets BEFORE downsampling
                    winch_df = apply_offsets(winch_df, winch_x_offset, winch_y_offset, 0, 0, [additional_winch_parameter])
                    
                    # Apply downsampling if not in detail mode
                    if not detail_mode and len(winch_df) > max_points:
                        step = max(1, len(winch_df) // max_points)
                        winch_df = winch_df.iloc[::step]
                    elif detail_mode and len(winch_df) > 200000:  # Safety limit
                        winch_df = winch_df.iloc[::2]

                    fig.add_trace(
                        go.Scatter(
                            x=winch_df['datetime'], y=winch_df[additional_winch_parameter],
                            name=f"🔧 Add. Winch: {additional_winch_parameter}",
                            line=dict(color='darkmagenta', width=2),
                            opacity=0.8,
                            legendgroup="additional_winch"
                        ), row=current_row, col=1
                    )
                
                fig.update_yaxes(title_text=f"Add. Winch: {additional_winch_parameter}", row=current_row, col=1)
            
            # Configure layout for multiple subplots
            plot_height = 400 + (subplot_count * 150)  # Dynamic height based on subplot count
            fig.update_layout(
                height=plot_height,
                hovermode='x unified',
                showlegend=True,
                template="plotly_white"
            )
            
            # Update x-axis title only on bottom subplot
            fig.update_xaxes(title_text="Time", row=subplot_count, col=1)
        
        # Display the plot
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
        if detail_mode:
            st.metric("Mode", "Detail (all points)")
        else:
            st.metric("Mode", f"Overview (max {max_points:,})")
        
        if enable_winch and 'selected_winch' in locals():
            st.metric("Winch Data", "Enabled")
            if additional_winch_plot and 'additional_winch_parameter' in locals() and additional_winch_parameter:
                st.metric("Additional Winch Param", additional_winch_parameter)
        else:
            st.metric("Winch Data", "Disabled")
    
    with info_col3:
        # Show data ranges
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
    
    # Show sample data structure
    with st.expander("ℹ️ About this application"):
        st.write("""
        This application allows you to:
        
        - **📊 Plot sensor data** from multiple files simultaneously
        - **🔗 Overlay companion data** from related cores
        - **🔧 Add winch data** for correlation analysis
        - **⏰ Control time ranges** and data density
        - **🎯 Synchronized crosshairs** across multiple plots
        
        **Getting Started:**
        1. Select a cruise from the dropdown
        2. Choose a core containing sensor data
        3. Select one or more sensor files
        4. Pick a parameter to plot
        5. Optionally enable winch data overlay
        """)