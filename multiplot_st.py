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

# Add this function to capture and handle zoom state:
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
            cores_df = pd.read_sql(
                "SELECT core_id, core_name FROM cores WHERE cruise_id = %(cruise_id)s ORDER BY core_name",
                conn, params={"cruise_id": cruise_id}
            )
        
        if not cores_df.empty:
            core_options = {row['core_name']: row['core_id'] for _, row in cores_df.iterrows()}
            selected_core = st.selectbox("Select Core:", options=list(core_options.keys()))
            
            if selected_core:
                core_id = core_options[selected_core]
                
                # Sensor files
                with get_connection() as conn:
                    sensor_files_df = pd.read_sql("""
                        SELECT file_id, file_name, sensor_type, sensor_location 
                        FROM sensor_files WHERE core_id = %(core_id)s ORDER BY file_name
                    """, conn, params={"core_id": core_id})
                
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
                                    winch_df = pd.read_sql("""
                                        SELECT winch_file_id, file_name, start_time, end_time 
                                        FROM winch_data WHERE cruise_id = %(cruise_id)s ORDER BY file_name
                                    """, conn, params={"cruise_id": cruise_id})
                                
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

# Main plotting area
if 'selected_sensors' in locals() and selected_sensors:
    
    # Add time range controls in main area
    col1, col2 = st.columns([3, 1])
    
    with col2:
        st.subheader("🔧 Plot Controls")
        
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
                
                # Manual time inputs
                st.write("**Adjust time window around max depth:**")
                
                col_start, col_end = st.columns(2)
                
                with col_start:
                    start_time = st.time_input(
                        "Start time:",
                        value=default_start.time(),
                        key="detail_start"
                    )
                    start_date = default_start.date()
                
                with col_end:
                    end_time = st.time_input(
                        "End time:",
                        value=default_end.time(),
                        key="detail_end"
                    )
                    end_date = default_end.date()
                
                # Combine date and time
                detail_start = pd.to_datetime(f"{start_date} {start_time}")
                detail_end = pd.to_datetime(f"{end_date} {end_time}")
                zoom_range = [detail_start, detail_end]
                
                # Show the selected window
                time_span_minutes = (detail_end - detail_start).total_seconds() / 60
                st.info(f"⏰ Time window: {time_span_minutes:.1f} minutes")
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
                        start_time = st.time_input(
                            "Start time:",
                            value=default_start.time(),
                            key="manual_start"
                        )
                    
                    with col_end:
                        end_time = st.time_input(
                            "End time:",
                            value=default_end.time(),
                            key="manual_end"
                        )
                    
                    detail_start = pd.to_datetime(f"{default_start.date()} {start_time}")
                    detail_end = pd.to_datetime(f"{default_end.date()} {end_time}")
                    zoom_range = [detail_start, detail_end]
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

    with col1:
        # Create the plot
        if enable_winch and 'selected_winch' in locals() and 'winch_parameter' in locals():
            # Two subplots
            fig = make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.02,
                row_heights=[0.6, 0.4],
                subplot_titles=[f"Sensor Data: {parameter}", f"Winch Data: {winch_parameter}"]
            )
            
            # Add sensor traces to top subplot
            colors = ['blue', 'red', 'green', 'orange', 'purple', 'brown', 'pink', 'gray']
            for i, file_id in enumerate(sensor_file_ids):
                df, info = load_sensor_data(file_id)
                if df is not None:
                    # Apply zoom filter first if in detail mode
                    if detail_mode and zoom_range:
                        df = apply_zoom_filter(df, zoom_range)
                        st.write(f"📊 {info.file_name}: {len(df):,} points in zoom range")
                    
                    # Apply downsampling if not in detail mode
                    if not detail_mode and len(df) > max_points:
                        step = max(1, len(df) // max_points)
                        df = df.iloc[::step]
                    elif detail_mode and len(df) > 200000:  # Safety limit even in detail mode
                        st.warning(f"⚠️ {info.file_name}: {len(df):,} points is very large. Sampling every 2nd point.")
                        df = df.iloc[::2]

                    color = colors[i % len(colors)]
                    cols_to_plot = find_columns_to_plot(df, parameter)
                    
                    # Debug info
                    if not cols_to_plot:
                        st.warning(f"No columns found for parameter '{parameter}' in {info.file_name}")
                        st.write(f"Available columns: {list(df.columns)}")

                    for col in cols_to_plot:
                        if col in df.columns and not df[col].isna().all():
                            fig.add_trace(
                                go.Scatter(
                                    x=df['datetime'], y=df[col],
                                    name=f"{info.file_name}: {col}",
                                    line=dict(color=color, width=2),
                                    opacity=0.8
                                ), row=1, col=1
                            )
            
            # Add winch trace to bottom subplot
            winch_df, winch_info = load_winch_data(winch_file_id)
            if winch_df is not None and winch_parameter in winch_df.columns:
                # Apply zoom filter first if in detail mode
                if detail_mode and zoom_range:
                    winch_df = apply_zoom_filter(winch_df, zoom_range)
                
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
                        opacity=0.8
                    ), row=2, col=1
                )
            
            # Configure layout for dual plot
            fig.update_layout(
                height=700,
                hovermode='x unified',
                showlegend=True,
                template="plotly_white"
            )
            
            # Update axes
            fig.update_xaxes(title_text="Time", row=2, col=1)
            fig.update_yaxes(title_text=f"Sensor: {parameter}", row=1, col=1)
            fig.update_yaxes(title_text=f"Winch: {winch_parameter}", row=2, col=1)
            
            # Invert y-axis if depth parameter
            if parameter and 'depth' in parameter.lower():
                fig.update_yaxes(autorange="reversed", row=1, col=1)
                
        else:
            # Single plot
            fig = go.Figure()
            
            colors = ['blue', 'red', 'green', 'orange', 'purple', 'brown', 'pink', 'gray']
            for i, file_id in enumerate(sensor_file_ids):
                df, info = load_sensor_data(file_id)
                if df is not None:
                    # Apply zoom filter first if in detail mode
                    if detail_mode and zoom_range:
                        df = apply_zoom_filter(df, zoom_range)
                    
                    # Apply downsampling if not in detail mode
                    if not detail_mode and len(df) > max_points:
                        step = max(1, len(df) // max_points)
                        df = df.iloc[::step]
                    elif detail_mode and len(df) > 200000:  # Safety limit even in detail mode
                        st.warning(f"⚠️ Large dataset in detail mode. Sampling for performance.")
                        df = df.iloc[::2]
                        
                    color = colors[i % len(colors)]
                    cols_to_plot = find_columns_to_plot(df, parameter)
                    
                    # Debug info
                    if not cols_to_plot:
                        st.warning(f"No columns found for parameter '{parameter}' in {info.file_name}")
                        st.write(f"Available columns: {list(df.columns)}")

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
        
        # Display the plot
        st.plotly_chart(fig, use_container_width=True)
    
    # Data info
    st.subheader("📊 Data Information")
    info_col1, info_col2, info_col3 = st.columns(3)
    
    with info_col1:
        st.metric("Parameter", parameter)
        st.metric("Sensor Files", len(selected_sensors))
    
    with info_col2:
        if detail_mode:
            st.metric("Mode", "Detail (all points)")
        else:
            st.metric("Mode", f"Overview (max {max_points:,})")
        
        if enable_winch and 'selected_winch' in locals():
            st.metric("Winch Data", "Enabled")
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
        
        if enable_winch and 'winch_df' in locals() and winch_df is not None:
            st.metric("Winch Points", f"{len(winch_df):,}")

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