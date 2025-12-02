import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import os
from config import get_full_path
from db_util import get_connection
from sqlalchemy import text
import datetime

st.set_page_config(page_title="Winch Data Plotter", layout="wide")

@st.cache_data
def load_winch_data(winch_file_id):
    """Load winch data from database and file"""
    try:
        from utils import parse_winch_dat
        import json
        
        # Get file info from winch_data table
        with get_connection() as conn:
            query = text("SELECT file_name, file_path, settings, cruise_id FROM winch_data WHERE winch_file_id = :winch_file_id")
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

def apply_offsets(df, x_offset, y_offset, parameter_cols):
    """Apply time and value offsets to dataframe"""
    df_offset = df.copy()
    
    # Apply time offset (x-axis)
    if x_offset != 0:
        df_offset['datetime'] = df_offset['datetime'] + pd.Timedelta(seconds=x_offset)
    
    # Apply value offset (y-axis) to specified columns
    if y_offset != 0:
        for col in parameter_cols:
            if col in df_offset.columns:
                df_offset[col] = df_offset[col] + y_offset
    
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
def create_export_dataframe(winch_file_id, parameters, x_offset, y_offset, 
                           max_points, zoom_mode, zoom_range):
    """Create export dataframe with exactly what's being plotted"""
    
    df, info = load_winch_data(winch_file_id)
    if df is None:
        return pd.DataFrame(), {}
    
    # Apply offsets
    df = apply_offsets(df, x_offset, y_offset, parameters)
    
    # Apply zoom filter if in zoom mode
    if zoom_mode and zoom_range:
        df = apply_zoom_filter(df, zoom_range)
    
    # Apply downsampling if not in zoom mode
    if not zoom_mode and len(df) > max_points:
        step = max(1, len(df) // max_points)
        df = df.iloc[::step]
    
    # Select only datetime and the chosen parameters
    export_cols = ['datetime'] + [p for p in parameters if p in df.columns]
    export_df = df[export_cols].copy()
    
    metadata = {
        'winch_file': info.file_name,
        'x_offset_seconds': x_offset,
        'y_offset': y_offset,
        'parameters': parameters,
        'zoom_mode': zoom_mode
    }
    
    return export_df, metadata

st.title("🔧 Winch Data Plotter")
st.write("Plot and analyze winch data from sediment coring operations")

# Sidebar for controls
with st.sidebar:
    st.header("📊 Data Selection")
    
    # Cruise selection
    with get_connection() as conn:
        query = text("""
            SELECT DISTINCT c.cruise_id, c.cruise_name, v.vessel_name
            FROM cruises c
            JOIN winch_data w ON c.cruise_id = w.cruise_id
            JOIN vessels v ON c.vessel_id = v.vessel_id
            ORDER BY c.cruise_name
        """)
        cruises_with_winch = pd.read_sql(query, conn)
    
    if cruises_with_winch.empty:
        st.warning("No cruises found with winch data")
        st.stop()
    
    cruise_options = {
        f"{row['cruise_name']} - {row['vessel_name']}": row['cruise_id'] 
        for _, row in cruises_with_winch.iterrows()
    }
    selected_cruise = st.selectbox("Select Cruise:", options=list(cruise_options.keys()))
    
    if selected_cruise:
        cruise_id = cruise_options[selected_cruise]
        
        # Winch file selection
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
                
                # Get parameters
                winch_params = get_winch_parameters(winch_file_id)
                if winch_params:
                    # Allow multiple parameter selection
                    selected_parameters = st.multiselect(
                        "Select Parameters to Plot:",
                        options=winch_params,
                        default=[winch_params[0]] if winch_params else []
                    )
                    
                    if selected_parameters:
                        st.divider()
                        
                        # Plot controls
                        st.header("🔧 Plot Controls")
                        
                        # Get time range
                        df, _ = load_winch_data(winch_file_id)
                        if df is not None:
                            min_time = df['datetime'].min()
                            max_time = df['datetime'].max()
                            
                            # Zoom controls
                            st.subheader("🔍 Zoom Mode")
                            
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
                            
                            zoom_start = pd.to_datetime(f"{start_date} {start_hour:02d}:{start_minute:02d}:{start_second:02d}")
                            zoom_end = pd.to_datetime(f"{end_date} {end_hour:02d}:{end_minute:02d}:{end_second:02d}")
                            zoom_range = [zoom_start, zoom_end]
                            
                            time_span_seconds = (zoom_end - zoom_start).total_seconds()
                            time_span_minutes = time_span_seconds / 60
                            st.info(f"⏰ Selected window: {time_span_minutes:.1f} minutes ({time_span_seconds:.0f} seconds)")
                            
                            zoom_mode = st.checkbox("🔍 Enable Zoom Mode (Plot All Points)", value=False)
                            
                            if not zoom_mode:
                                max_points = st.number_input(
                                    "Max Points:", 
                                    min_value=100, 
                                    max_value=50000, 
                                    value=5000, 
                                    step=500
                                )
                            else:
                                max_points = 1000000
                            
                            # Offset controls
                            st.subheader("⚡ Offsets")
                            x_offset = st.number_input("Time Offset (seconds):", value=0.0, step=0.1, format="%.2f")
                            y_offset = st.number_input("Value Offset:", value=0.0, step=0.1, format="%.2f")
                            
                            # Export controls
                            st.divider()
                            st.subheader("💾 Export Data")
                            
                            if st.button("📊 Generate Export Data", type="primary"):
                                with st.spinner("Preparing export data..."):
                                    export_df, metadata = create_export_dataframe(
                                        winch_file_id=winch_file_id,
                                        parameters=selected_parameters,
                                        x_offset=x_offset,
                                        y_offset=y_offset,
                                        max_points=max_points,
                                        zoom_mode=zoom_mode,
                                        zoom_range=zoom_range if zoom_mode else None
                                    )
                                    
                                    if not export_df.empty:
                                        st.session_state['export_df'] = export_df
                                        st.session_state['export_metadata'] = metadata
                                        st.success(f"✅ {len(export_df):,} rows ready!")
                            
                            if 'export_df' in st.session_state and not st.session_state['export_df'].empty:
                                export_df = st.session_state['export_df']
                                metadata = st.session_state['export_metadata']
                                
                                timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
                                cruise_name = selected_cruise.split(' - ')[0].replace(' ', '_')
                                filename = f"winch_export_{cruise_name}_{timestamp}.csv"
                                
                                import io
                                csv_buffer = io.StringIO()
                                csv_buffer.write(f"# Winch Data Export - {timestamp}\n")
                                csv_buffer.write(f"# Cruise: {selected_cruise}\n")
                                csv_buffer.write(f"# Winch File: {metadata['winch_file']}\n")
                                csv_buffer.write(f"# Parameters: {', '.join(metadata['parameters'])}\n")
                                csv_buffer.write(f"# Time offset: {metadata['x_offset_seconds']} seconds\n")
                                csv_buffer.write(f"# Value offset: {metadata['y_offset']}\n")
                                csv_buffer.write("#\n")
                                export_df.to_csv(csv_buffer, index=False, float_format='%.6f')
                                
                                st.download_button(
                                    label="📥 Download CSV",
                                    data=csv_buffer.getvalue(),
                                    file_name=filename,
                                    mime="text/csv",
                                    type="primary"
                                )

# Main plotting area
if 'selected_parameters' in locals() and selected_parameters:
    # Create figure
    num_params = len(selected_parameters)
    
    if num_params == 1:
        fig = go.Figure()
        subplot_titles = None
    else:
        fig = make_subplots(
            rows=num_params, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.02,
            subplot_titles=selected_parameters
        )
    
    # Load and plot data
    df, info = load_winch_data(winch_file_id)
    if df is not None:
        # Apply offsets
        df = apply_offsets(df, x_offset, y_offset, selected_parameters)
        
        # Apply zoom/downsample
        if zoom_mode and zoom_range:
            df = apply_zoom_filter(df, zoom_range)
        elif not zoom_mode and len(df) > max_points:
            step = max(1, len(df) // max_points)
            df = df.iloc[::step]
        
        # Plot each parameter
        colors = ['blue', 'red', 'green', 'orange', 'purple', 'brown', 'pink', 'gray']
        
        for idx, param in enumerate(selected_parameters):
            if param in df.columns:
                color = colors[idx % len(colors)]
                
                if num_params == 1:
                    fig.add_trace(
                        go.Scatter(
                            x=df['datetime'],
                            y=df[param],
                            name=param,
                            line=dict(color=color, width=2)
                        )
                    )
                else:
                    fig.add_trace(
                        go.Scatter(
                            x=df['datetime'],
                            y=df[param],
                            name=param,
                            line=dict(color=color, width=2),
                            showlegend=False
                        ),
                        row=idx+1, col=1
                    )
                    fig.update_yaxes(title_text=param, row=idx+1, col=1)
        
        # Update layout
        plot_height = 600 if num_params == 1 else 300 + (num_params * 150)
        
        fig.update_layout(
            height=plot_height,
            hovermode='x unified',
            template="plotly_white",
            title=f"Winch Data: {selected_cruise}",
            showlegend=(num_params == 1)
        )
        
        if num_params > 1:
            fig.update_xaxes(title_text="Time", row=num_params, col=1)
        else:
            fig.update_xaxes(title_text="Time")
            fig.update_yaxes(title_text=selected_parameters[0])
        
        st.plotly_chart(fig, use_container_width=True)
        
        # Data info
        st.subheader("📊 Data Information")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Winch File", info.file_name)
            st.metric("Parameters", len(selected_parameters))
        
        with col2:
            if zoom_mode:
                st.metric("Mode", "🔍 Zoom")
                time_span = (zoom_range[1] - zoom_range[0]).total_seconds() / 60
                st.metric("Window", f"{time_span:.1f} min")
            else:
                st.metric("Mode", f"📊 Overview")
                st.metric("Max Points", f"{max_points:,}")
        
        with col3:
            st.metric("Total Points", f"{len(df):,}")
            st.metric("Time Range", f"{(df['datetime'].max() - df['datetime'].min()).total_seconds() / 60:.1f} min")

else:
    st.info("👆 Select cruise and winch file from the sidebar to begin plotting")
    
    with st.expander("ℹ️ About this application"):
        st.write("""
        This application allows you to:
        
        - **📊 Plot winch data** from sediment coring operations
        - **📈 Multiple parameters** on separate subplots
        - **⚡ Apply offsets** to align data
        - **🔍 Zoom mode** to view all points in a time window
        - **💾 Export data** to CSV
        
        **Getting Started:**
        1. Select a cruise
        2. Choose a winch file
        3. Select one or more parameters to plot
        4. Adjust zoom and offsets as needed
        5. Export aligned data if needed
        """)