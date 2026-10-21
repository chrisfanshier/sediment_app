import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import os
import json
from config import get_full_path
from db_util import get_connection
from sqlalchemy import text
from utils import parse_winch_dat
import datetime


def _core_window(df):
    """Return (start, end) naive-UTC datetime Series for each core row.

    Uses deploy_utc / recover_utc; falls back to the legacy date + time_launched / time_recovered
    columns (with midnight rollover) for rows that were not backfilled.
    """
    def utc_naive(col):
        if col not in df.columns:
            return pd.Series(pd.NaT, index=df.index)
        return pd.to_datetime(df[col], utc=True, errors="coerce").dt.tz_localize(None)

    start, end = utc_naive("deploy_utc"), utc_naive("recover_utc")

    if {"date", "time_launched", "time_recovered"} <= set(df.columns):
        day = pd.to_datetime(df["date"], errors="coerce")
        legacy_start = day + pd.to_timedelta(df["time_launched"].astype(str), errors="coerce")
        legacy_end = day + pd.to_timedelta(df["time_recovered"].astype(str), errors="coerce")
        legacy_end = legacy_end.where(~(legacy_end < legacy_start), legacy_end + pd.Timedelta(days=1))
        start, end = start.fillna(legacy_start), end.fillna(legacy_end)
    return start, end


@st.cache_data
def get_cores_with_winch(cruise_id):
    """Find all cores/dredges whose deployment window overlaps with at least one winch file."""
    with get_connection() as conn:
        cores = pd.read_sql(
            text("SELECT * FROM cores WHERE cruise_id = :cruise_id ORDER BY core_name"),
            conn,
            params={"cruise_id": cruise_id},
        )
        winch_files = pd.read_sql(
            text("SELECT winch_file_id, file_name, file_path, start_time, end_time, settings "
                 "FROM winch_data WHERE cruise_id = :cruise_id ORDER BY start_time"),
            conn,
            params={"cruise_id": cruise_id},
        )

    if cores.empty or winch_files.empty:
        return pd.DataFrame()

    cores = cores.copy()
    cores["start_datetime"], cores["end_datetime"] = _core_window(cores)

    # Drop rows with invalid times
    cores = cores.dropna(subset=["start_datetime", "end_datetime"])
    if cores.empty:
        return pd.DataFrame()

    # Parse winch file times (strip timezone if present)
    def strip_tz(x):
        dt = pd.to_datetime(x, errors="coerce")
        if dt is not pd.NaT and hasattr(dt, "tz") and dt.tz is not None:
            return dt.tz_localize(None)
        return dt

    winch_files["start_time"] = winch_files["start_time"].apply(strip_tz)
    winch_files["end_time"] = winch_files["end_time"].apply(strip_tz)

    # Keep only cores that overlap with at least one winch file
    matching_ids = []
    for _, core in cores.iterrows():
        overlap = (winch_files["start_time"] <= core["end_datetime"]) & (winch_files["end_time"] >= core["start_datetime"])
        if overlap.any():
            matching_ids.append(core["core_id"])

    return cores[cores["core_id"].isin(matching_ids)]


@st.cache_data
def load_core_winch_data(core_id, cruise_id):
    """Load and concatenate all winch files overlapping a core's deployment window, trimmed to the window."""
    with get_connection() as conn:
        core_row = pd.read_sql(
            text("SELECT * FROM cores WHERE core_id = :core_id"),
            conn,
            params={"core_id": core_id},
        ).iloc[0]
        winch_files = pd.read_sql(
            text("SELECT winch_file_id, file_name, file_path, start_time, end_time, settings "
                 "FROM winch_data WHERE cruise_id = :cruise_id ORDER BY start_time"),
            conn,
            params={"cruise_id": cruise_id},
        )

    # Parse core deployment window
    starts, ends = _core_window(pd.DataFrame([core_row]))
    core_start, core_end = starts.iloc[0], ends.iloc[0]

    # Strip timezone from winch file times
    def strip_tz(x):
        dt = pd.to_datetime(x, errors="coerce")
        if dt is not pd.NaT and hasattr(dt, "tz") and dt.tz is not None:
            return dt.tz_localize(None)
        return dt

    winch_files["start_time"] = winch_files["start_time"].apply(strip_tz)
    winch_files["end_time"] = winch_files["end_time"].apply(strip_tz)

    # Find overlapping winch files
    overlap_mask = (winch_files["start_time"] <= core_end) & (winch_files["end_time"] >= core_start)
    overlapping = winch_files[overlap_mask]

    if overlapping.empty:
        return None, []

    winch_dfs = []
    file_names = []

    for _, wrow in overlapping.iterrows():
        try:
            settings = json.loads(wrow["settings"]) if wrow["settings"] else {}
        except (json.JSONDecodeError, TypeError):
            settings = {}

        relative_path = os.path.join(wrow["file_path"], wrow["file_name"])
        full_path = get_full_path(relative_path)

        if settings:
            parsing_settings = {
                "delimiter": settings.get("delimiter", ","),
                "header_lines": settings.get("header_lines", 0),
                "columns": settings.get("columns", []),
                "datetime_code": settings.get("datetime_code", "pd.to_datetime(df['datetime'])"),
            }
            if "numeric_columns" in settings:
                parsing_settings["numeric_columns"] = settings["numeric_columns"]
        else:
            file_ext = os.path.splitext(wrow["file_name"])[1].lower()
            if file_ext == ".dat":
                parsing_settings = {
                    "delimiter": r"\s+",
                    "header_lines": 0,
                    "datetime_code": "pd.to_datetime(df[['year', 'month', 'day', 'hour', 'minute', 'second']])",
                }
            else:
                parsing_settings = {
                    "delimiter": ",",
                    "header_lines": 0,
                    "datetime_code": "pd.to_datetime(df['datetime'])",
                }

        try:
            df = parse_winch_dat(full_path, parsing_settings)
            if df is not None and "datetime" in df.columns:
                df["datetime"] = pd.to_datetime(df["datetime"]).dt.tz_localize(None)
                winch_dfs.append(df)
                file_names.append(wrow["file_name"])
        except Exception as e:
            st.warning(f"Could not load winch file {wrow['file_name']}: {e}")

    if not winch_dfs:
        return None, []

    # Concatenate and sort
    all_winch = pd.concat(winch_dfs, ignore_index=True).sort_values("datetime").reset_index(drop=True)

    # Trim to core deployment window
    trim_mask = (all_winch["datetime"] >= core_start) & (all_winch["datetime"] <= core_end)
    trimmed = all_winch[trim_mask].copy().reset_index(drop=True)

    if trimmed.empty:
        return None, file_names

    return trimmed, file_names


@st.cache_data
def get_winch_parameters(core_id, cruise_id):
    """Get available numeric parameters from concatenated winch data for a core."""
    df, _ = load_core_winch_data(core_id, cruise_id)
    if df is None:
        return []

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
def create_export_dataframe(core_id, cruise_id, parameters, x_offset, y_offset,
                           max_points, zoom_mode, zoom_range):
    """Create export dataframe with exactly what's being plotted"""

    df, file_names = load_core_winch_data(core_id, cruise_id)
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
        'winch_files': ", ".join(file_names),
        'x_offset_seconds': x_offset,
        'y_offset': y_offset,
        'parameters': parameters,
        'zoom_mode': zoom_mode,
    }

    return export_df, metadata

def winch_plot():
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

            # Core/dredge selection — only cores with overlapping winch data
            cores_with_winch_df = get_cores_with_winch(cruise_id)

            if cores_with_winch_df.empty:
                st.warning("No cores/dredges with overlapping winch data found for this cruise")
                st.stop()

            core_options = {
                row['core_name']: int(row['core_id'])
                for _, row in cores_with_winch_df.iterrows()
            }
            selected_core = st.selectbox("Select Core/Dredge:", options=list(core_options.keys()))

            if selected_core:
                core_id = core_options[selected_core]

                # Get parameters from the concatenated winch data
                winch_params = get_winch_parameters(core_id, cruise_id)
                if winch_params:
                    selected_parameters = st.multiselect(
                        "Select Parameters to Plot:",
                        options=winch_params,
                        default=[winch_params[0]] if winch_params else [],
                    )

                    if selected_parameters:
                        st.divider()

                        # Plot controls
                        st.header("🔧 Plot Controls")

                        # Get time range from the loaded data
                        df, _file_names = load_core_winch_data(core_id, cruise_id)
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
                                    step=500,
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
                                        core_id=core_id,
                                        cruise_id=cruise_id,
                                        parameters=selected_parameters,
                                        x_offset=x_offset,
                                        y_offset=y_offset,
                                        max_points=max_points,
                                        zoom_mode=zoom_mode,
                                        zoom_range=zoom_range if zoom_mode else None,
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
                                filename = f"winch_export_{cruise_name}_{selected_core}_{timestamp}.csv"

                                import io
                                csv_buffer = io.StringIO()
                                csv_buffer.write(f"# Winch Data Export - {timestamp}\n")
                                csv_buffer.write(f"# Cruise: {selected_cruise}\n")
                                csv_buffer.write(f"# Core: {selected_core}\n")
                                csv_buffer.write(f"# Winch Files: {metadata['winch_files']}\n")
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
                                    type="primary",
                                )

    # Cache control
    st.divider()
    st.subheader("🔄 Cache Control")

    col_cache1, col_cache2 = st.columns(2)

    with col_cache1:
        if st.button("Clear Data Cache", help="Clear cached winch data to reload fresh from database"):
            st.cache_data.clear()
            st.success("✅ Cache cleared!")
            st.rerun()

    with col_cache2:
        if st.button("Clear All Cache", help="Clear all cached data including parameters"):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.success("✅ All cache cleared!")
            st.rerun()

    st.caption("💡 Use after adding or updating data in database")

    # Main plotting area
    if 'selected_parameters' in locals() and selected_parameters:
        # Create figure
        num_params = len(selected_parameters)

        if num_params == 1:
            fig = go.Figure()
        else:
            fig = make_subplots(
                rows=num_params, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.02,
                subplot_titles=selected_parameters,
            )

        # Load and plot data
        df, file_names = load_core_winch_data(core_id, cruise_id)
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
                                line=dict(color=color, width=2),
                            )
                        )
                    else:
                        fig.add_trace(
                            go.Scatter(
                                x=df['datetime'],
                                y=df[param],
                                name=param,
                                line=dict(color=color, width=2),
                                showlegend=False,
                            ),
                            row=idx + 1, col=1,
                        )
                        fig.update_yaxes(title_text=param, row=idx + 1, col=1)

            # Update layout
            plot_height = 600 if num_params == 1 else 300 + (num_params * 150)

            fig.update_layout(
                height=plot_height,
                hovermode='x unified',
                template="plotly_white",
                title=f"Winch Data: {selected_cruise} — {selected_core}",
                showlegend=(num_params == 1),
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
                st.metric("Core / Dredge", selected_core)
                st.metric("Winch Files", len(file_names))
                if file_names:
                    st.caption(", ".join(file_names))

            with col2:
                if zoom_mode:
                    st.metric("Mode", "🔍 Zoom")
                    time_span = (zoom_range[1] - zoom_range[0]).total_seconds() / 60
                    st.metric("Window", f"{time_span:.1f} min")
                else:
                    st.metric("Mode", "📊 Overview")
                    st.metric("Max Points", f"{max_points:,}")

            with col3:
                st.metric("Total Points", f"{len(df):,}")
                st.metric("Time Range", f"{(df['datetime'].max() - df['datetime'].min()).total_seconds() / 60:.1f} min")

    else:
        st.info("👆 Select a cruise and core/dredge from the sidebar to begin plotting")

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
            2. Choose a core/dredge (only those with overlapping winch data are shown)
            3. Select one or more parameters to plot
            4. Adjust zoom and offsets as needed
            5. Export aligned data if needed
            """)