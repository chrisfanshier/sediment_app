import streamlit as st
import pandas as pd
from db_util import get_connection
from sqlalchemy import text
import os
from config import get_full_path
from utils import load_usbl_file
from utils import add_utm_coords
from utils import ellipse_polygon  
import geopandas as gpd
import tempfile

st.title("Cores and associated USBL files (Cruise → Core)")

with get_connection() as conn:
    cruises = pd.read_sql(
        text("SELECT DISTINCT c.cruise_id, c.cruise_name "
             "FROM cruises c JOIN usbl_files u ON c.cruise_id = u.cruise_id "
             "ORDER BY c.cruise_name"),
        conn
    )

if cruises.empty:
    st.info("No cruises with USBL files found.")
    st.stop()

cruise_map = {row.cruise_name: row.cruise_id for _, row in cruises.iterrows()}
selected = st.selectbox("Select cruise", ["-- choose --"] + list(cruise_map.keys()), key="cruise_with_usbl_select")
if not selected or selected == "-- choose --":
    st.stop()

cruise_id = cruise_map[selected]

with get_connection() as conn:
    cores = pd.read_sql(
        text("SELECT * FROM cores WHERE cruise_id = :cruise_id ORDER BY core_name"),
        conn,
        params={"cruise_id": cruise_id}
    )
    usbl_df = pd.read_sql(
        text("SELECT usbl_file_id, file_name, file_path, start_time, end_time FROM usbl_files WHERE cruise_id = :cruise_id"),
        conn,
        params={"cruise_id": cruise_id}
    )

if cores.empty:
    st.info("No cores for selected cruise.")
    st.stop()

if usbl_df.empty:
    st.info("No USBL files for selected cruise.")
    st.stop()

# normalize/parse core start/end datetimes using the simple convention
date_col = next((c for c in ("date", "core_date") if c in cores.columns), None)
launch_col = next((c for c in ("time_launched", "time_launch", "time_launched_utc") if c in cores.columns), None)
recover_col = next((c for c in ("time_recovered", "time_recover", "time_recovered_utc") if c in cores.columns), None)

if not (date_col and launch_col and recover_col):
    st.error("Cores missing required date/time columns (date + time_launched + time_recovered).")
    st.write("Available core columns:", list(cores.columns))
    st.stop()

df_dredge = cores.copy()
df_dredge[launch_col] = df_dredge[launch_col].astype(str)
df_dredge[recover_col] = df_dredge[recover_col].astype(str)

# safe parsing (invalid -> NaT)
df_dredge["start_datetime"] = pd.to_datetime(df_dredge[date_col], errors="coerce") + pd.to_timedelta(df_dredge[launch_col], errors="coerce")
df_dredge["end_datetime"] = pd.to_datetime(df_dredge[date_col], errors="coerce") + pd.to_timedelta(df_dredge[recover_col], errors="coerce")

bad = df_dredge[["start_datetime", "end_datetime"]].isna().any(axis=1)
if bad.any():
    st.warning(f"Dropped {bad.sum()} core rows with invalid date/time")
    df_dredge = df_dredge.loc[~bad].copy()

# midnight rollover
df_dredge.loc[df_dredge["end_datetime"] < df_dredge["start_datetime"], "end_datetime"] += pd.Timedelta(days=1)

# parse USBL file datetimes
usbl_df["start_time"] = pd.to_datetime(usbl_df["start_time"], errors="coerce")
usbl_df["end_time"] = pd.to_datetime(usbl_df["end_time"], errors="coerce")

# build one-row-per-core output listing matched USBL filenames
results = []
for _, core in df_dredge.iterrows():
    mask = (usbl_df["start_time"] <= core["end_datetime"]) & (usbl_df["end_time"] >= core["start_datetime"])
    matched = usbl_df.loc[mask, "file_name"].astype(str).tolist()
    results.append({
        "core_name": core.get("core_name"),
        "start_datetime": core["start_datetime"],
        "end_datetime": core["end_datetime"],
        "usbl_files": ", ".join(matched) if matched else ""
    })

out_df = pd.DataFrame(results)
st.subheader(f"Cores and associated USBL files for cruise: {selected}")
st.dataframe(out_df, use_container_width=True)

# --- Export all USBL data for a selected core ---
core_names = out_df["core_name"].tolist()
selected_core_export = st.selectbox("Select core to export all USBL data", ["-- choose --"] + core_names)

if selected_core_export and selected_core_export != "-- choose --":
    # Get core details
    selected_core_row = df_dredge[df_dredge["core_name"] == selected_core_export].iloc[0]
    selected_core_id = int(selected_core_row["core_id"])
    
    # Load USBL files
    usbl_file_list = out_df.loc[out_df["core_name"] == selected_core_export, "usbl_files"].values[0]
    usbl_file_list = [f.strip() for f in usbl_file_list.split(",") if f.strip()]
    usbl_dfs = []
    
    for fname in usbl_file_list:
        row = usbl_df[usbl_df["file_name"] == fname]
        if not row.empty:
            file_path = row.iloc[0].get("file_path", "")
            relative_path = os.path.join(file_path, fname)
            full_path = get_full_path(relative_path)
            try:
                df = load_usbl_file(full_path)
                if df is not None:
                    usbl_dfs.append(df)
            except Exception as e:
                st.error(f"Error loading USBL file: {e}")
    
    if usbl_dfs:
        all_usbl = pd.concat(usbl_dfs)
        # Keep ALL data points - no removal
        all_usbl = all_usbl.sort_index()
        
        # Get USBL time range for later use
        usbl_times = all_usbl.reset_index()
        usbl_times['datetime'] = pd.to_datetime(usbl_times['datetime']).dt.tz_localize(None)
        usbl_start = usbl_times['datetime'].min()
        usbl_end = usbl_times['datetime'].max()
        
        # ========== SECTION 1: Basic USBL Export ==========
        st.markdown("---")
        st.subheader("💾 Basic USBL Export")
        
        csv = all_usbl.reset_index().to_csv(index=False)
        st.download_button(
            label=f"📍 Download all USBL data for {selected_core_export}",
            data=csv,
            file_name=f"{selected_core_export}_usbl.csv",
            mime="text/csv"
        )
        
        # ========== SECTION 2: UTM Ellipse Exports ==========
        st.markdown("---")
        st.subheader("🗺️ Export USBL Error Ellipses (for GIS)")
        
        utm_zone = st.number_input("UTM Zone", min_value=1, max_value=60, value=33)
        northern = st.radio("Hemisphere", ["Northern", "Southern"]) == "Northern"
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("Download Error Ellipse Table with UTM"):
                ellipse_df = add_utm_coords(
                    all_usbl,
                    lat_col="latitude_deg",
                    lon_col="longitude_deg",
                    utm_zone=utm_zone,
                    northern=northern
                )
                export_cols = ["X_Center", "Y_Center", "hor_err_major", "hor_err_minor", "hor_err_dir"]
                arcgis_df = ellipse_df[export_cols].rename(columns={
                    "hor_err_major": "Semi_Major",
                    "hor_err_minor": "Semi_Minor",
                    "hor_err_dir": "Azimuth"
                })
                ellipse_csv = arcgis_df.to_csv(index=False)
                st.download_button(
                    label="💾 Download Ellipse Table (ArcGIS, UTM)",
                    data=ellipse_csv,
                    file_name=f"{selected_core_export}_usbl_ellipses_utm.csv",
                    mime="text/csv"
                )
        
        with col2:
            if st.button("Download Ellipse Polygons (GeoPackage)"):
                # Ensure UTM coordinates exist
                if "X_Center" not in all_usbl.columns or "Y_Center" not in all_usbl.columns:
                    ellipse_df = add_utm_coords(
                        all_usbl,
                        lat_col="latitude_deg",
                        lon_col="longitude_deg",
                        utm_zone=utm_zone,
                        northern=northern
                    )
                else:
                    ellipse_df = all_usbl

                # Build polygons
                gdf = gpd.GeoDataFrame(
                    ellipse_df,
                    geometry=[
                        ellipse_polygon(row.X_Center, row.Y_Center, row.hor_err_major, row.hor_err_minor, row.hor_err_dir)
                        for idx, row in ellipse_df.iterrows()
                    ],
                    crs=f"EPSG:326{utm_zone:02d}" if northern else f"EPSG:327{utm_zone:02d}"
                )

                # Add ISO datetime string column for export (preserves full datetime info)
                if 'datetime' in gdf.columns:
                    gdf['datetime_str'] = pd.to_datetime(gdf['datetime']).astype(str)

                # Save to GeoPackage
                with tempfile.TemporaryDirectory() as tmpdir:
                    gpkg_path = os.path.join(tmpdir, "usbl_ellipses.gpkg")
                    gdf.to_file(gpkg_path, layer="usbl_ellipses", driver="GPKG")
                    with open(gpkg_path, "rb") as f:
                        st.download_button(
                            label="💾 Download Ellipse Polygons (GeoPackage)",
                            data=f.read(),
                            file_name=f"{selected_core_export}_usbl_ellipses.gpkg",
                            mime="application/octet-stream"
                        )
        
        # ========== SECTION 3: Load Sensor Files ==========
        st.markdown("---")
        st.subheader("📊 Sensor Files")
        
        # Query sensor files
        with get_connection() as conn:
            sensor_query = text("""
                SELECT file_id, file_name, file_path, sensor_type, sensor_location
                FROM sensor_files
                WHERE core_id = :core_id
                ORDER BY file_name
            """)
            sensor_files_df = pd.read_sql(sensor_query, conn, params={"core_id": selected_core_id})
        
        # Cache function for loading sensor data
        @st.cache_data
        def load_and_parse_sensor_files(sensor_rows_tuple):
            """Load and parse sensor files, returning dict of dataframes"""
            from utils import process_rsk_data, process_star_oddi_data
            
            sensor_data_dict = {}
            for sensor_row in sensor_rows_tuple:
                file_name = sensor_row['file_name']
                file_path = sensor_row['file_path']
                sensor_type = sensor_row['sensor_type'] if sensor_row['sensor_type'] else "Unknown"
                
                relative_path = os.path.join(file_path, file_name)
                file_ext = os.path.splitext(file_name)[1].lower()
                sensor_type_lower = sensor_type.lower()
                
                try:
                    if file_ext == '.rsk' or 'rbr' in sensor_type_lower:
                        df = process_rsk_data(relative_path)
                    elif file_ext in ['.dat', '.acc'] or 'star-oddi' in sensor_type_lower or 'staroddi' in sensor_type_lower:
                        df = process_star_oddi_data(relative_path)
                    else:
                        continue
                    
                    if df is not None:
                        if 'datetime' not in df.columns:
                            if 'Timestamp' in df.columns:
                                df['datetime'] = df['Timestamp']
                            else:
                                continue
                        
                        # Remove timezone
                        df['datetime'] = pd.to_datetime(df['datetime']).dt.tz_localize(None)
                        
                        sensor_data_dict[file_name] = df
                        
                except Exception as e:
                    st.warning(f"Could not load {file_name}: {str(e)}")
            
            return sensor_data_dict
        
        sensor_data_dict = {}
        if not sensor_files_df.empty:
            st.write(f"Found {len(sensor_files_df)} sensor file(s)")
            
            # Load sensor data with caching
            with st.spinner("Loading sensor data..."):
                sensor_rows_tuple = tuple(sensor_files_df.to_dict('records'))
                sensor_data_dict = load_and_parse_sensor_files(sensor_rows_tuple)
            
            # Display preview of each sensor file
            for file_name, df in sensor_data_dict.items():
                sensor_row = sensor_files_df[sensor_files_df['file_name'] == file_name].iloc[0]
                sensor_type = sensor_row['sensor_type'] if sensor_row['sensor_type'] else "Unknown"
                sensor_location = sensor_row['sensor_location'] if sensor_row['sensor_location'] else "N/A"
                
                with st.expander(f"📊 {file_name} ({sensor_type} - {sensor_location})"):
                    st.write(f"**Records:** {len(df):,}")
                    st.write(f"**Time range:** {df['datetime'].min()} to {df['datetime'].max()}")
                    st.dataframe(df.head(10), use_container_width=True)
        else:
            st.info("No sensor files found for this core.")
        
        # ========== SECTION 4: Load Winch Data ==========
        st.markdown("---")
        st.subheader("⚙️ Winch Data")
        
        st.write(f"**USBL time range:** {usbl_start} to {usbl_end}")
        
        # Query winch files for this cruise
        with get_connection() as conn:
            winch_query = text("""
                SELECT winch_file_id, file_name, file_path, start_time, end_time, settings
                FROM winch_data
                WHERE cruise_id = :cruise_id
                ORDER BY start_time
            """)
            winch_files_df = pd.read_sql(winch_query, conn, params={"cruise_id": cruise_id})
        
        # Cache function for loading winch data
        @st.cache_data
        def load_and_parse_winch_files(winch_rows_tuple, usbl_start_ts, usbl_end_ts):
            """Load and parse winch files, returning combined dataframe"""
            from utils import parse_winch_dat
            import json
            
            winch_dfs = []
            for winch_row in winch_rows_tuple:
                file_name = winch_row['file_name']
                file_path = winch_row['file_path']
                settings = winch_row['settings']
                
                try:
                    # Parse settings
                    try:
                        settings_dict = json.loads(settings) if settings else {}
                    except json.JSONDecodeError:
                        settings_dict = {}
                    
                    # Construct full file path
                    relative_path = os.path.join(file_path, file_name)
                    full_file_path = get_full_path(relative_path)
                    
                    # Use the settings from the database
                    if settings_dict:
                        parsing_settings = {
                            "delimiter": settings_dict.get("delimiter", ","),
                            "header_lines": settings_dict.get("header_lines", 0),
                            "columns": settings_dict.get("columns", []),
                            "datetime_code": settings_dict.get("datetime_code", "pd.to_datetime(df['datetime'])")
                        }
                        if "numeric_columns" in settings_dict:
                            parsing_settings["numeric_columns"] = settings_dict["numeric_columns"]
                    else:
                        # Fallback settings
                        file_ext = os.path.splitext(file_name)[1].lower()
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
                    
                    # Parse the file
                    df = parse_winch_dat(full_file_path, parsing_settings)
                    
                    if df is not None:
                        # Ensure datetime column exists
                        if 'datetime' not in df.columns:
                            continue
                        
                        # Add source file column
                        df['source_file'] = file_name
                        winch_dfs.append(df)
                        
                except Exception as e:
                    st.warning(f"Could not load {file_name}: {str(e)}")
            
            if winch_dfs:
                # Concatenate if multiple files
                all_winch = pd.concat(winch_dfs, ignore_index=True)
                all_winch = all_winch.sort_values('datetime').reset_index(drop=True)
                
                # Remove timezone if present
                all_winch['datetime'] = pd.to_datetime(all_winch['datetime']).dt.tz_localize(None)
                
                # Trim to USBL time range
                trim_mask = (all_winch['datetime'] >= pd.Timestamp(usbl_start_ts)) & \
                           (all_winch['datetime'] <= pd.Timestamp(usbl_end_ts))
                trimmed_winch = all_winch[trim_mask].copy()
                
                return trimmed_winch
            return None
        
        winch_data_available = False
        trimmed_winch = None
        winch_numeric_cols = []
        
        if not winch_files_df.empty:
            # Parse timestamps
            def parse_and_strip_tz(x):
                dt = pd.to_datetime(x, errors="coerce")
                if dt is pd.NaT:
                    return dt
                if hasattr(dt, 'tz') and dt.tz is not None:
                    return dt.tz_localize(None)
                return dt
            
            winch_files_df["start_time"] = winch_files_df["start_time"].apply(parse_and_strip_tz)
            winch_files_df["end_time"] = winch_files_df["end_time"].apply(parse_and_strip_tz)
            
            # Find overlapping winch files
            overlap_mask = (
                (winch_files_df['start_time'] <= usbl_end) & 
                (winch_files_df['end_time'] >= usbl_start)
            )
            overlapping_winch = winch_files_df[overlap_mask]
            
            if not overlapping_winch.empty:
                st.write(f"Found {len(overlapping_winch)} winch file(s) overlapping with USBL data")
                
                # Load winch data with caching
                with st.spinner("Loading winch data..."):
                    winch_rows_tuple = tuple(overlapping_winch.to_dict('records'))
                    trimmed_winch = load_and_parse_winch_files(
                        winch_rows_tuple, 
                        usbl_start.isoformat(), 
                        usbl_end.isoformat()
                    )
                
                if trimmed_winch is not None:
                    winch_data_available = True
                    
                    # Get numeric columns
                    exclude_cols = ['index', 'datetime', 'date', 'time', 'year', 'month', 'day', 
                                   'hour', 'minute', 'second', 'source_file']
                    winch_numeric_cols = [col for col in trimmed_winch.select_dtypes(include=['number']).columns 
                                         if col.lower() not in exclude_cols]
                    
                    st.write(f"**Winch data loaded:** {len(trimmed_winch):,} records")
                    st.write(f"**Time range:** {trimmed_winch['datetime'].min()} to {trimmed_winch['datetime'].max()}")
                    st.write(f"**Available parameters:** {', '.join(winch_numeric_cols)}")
                    
                    # Preview
                    with st.expander("Preview Winch Data"):
                        st.dataframe(trimmed_winch.head(20), use_container_width=True)
                else:
                    st.info("No winch data could be loaded.")
            else:
                st.info("No winch files overlap with USBL time range.")
        else:
            st.info("No winch files found for this cruise.")
        
        # ========== SECTION 5: DREDGE APP EXPORT ==========
        st.markdown("---")
        st.subheader("🚀 Export for Dredge App (Time Series Analysis)")
        st.write("Create standardized files for interactive time series visualization and region selection")
        
        has_usbl = all_usbl is not None and not all_usbl.empty
        has_sensor = bool(sensor_data_dict)
        has_winch = winch_data_available and trimmed_winch is not None
        
        if has_usbl:
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**USBL Data:**")
                st.write(f"✓ {len(all_usbl)} points")
                if 'beacon_name' in all_usbl.columns:
                    for beacon in all_usbl['beacon_name'].unique():
                        count = (all_usbl['beacon_name'] == beacon).sum()
                        st.write(f"  - {beacon}: {count}")
            
            with col2:
                st.write("**Time Series Data:**")
                if has_sensor:
                    st.write(f"✓ {len(sensor_data_dict)} sensor file(s)")
                if has_winch:
                    st.write(f"✓ Winch data ({len(winch_numeric_cols)} columns)")
                if not has_sensor and not has_winch:
                    st.write("⚠️ No sensor/winch data")
            
            # Export button
            if st.button("📦 Create Dredge App Export Package", type="primary"):
                with st.spinner("Preparing export package..."):
                    try:
                        # === USBL FILE ===
                        usbl_export = all_usbl.reset_index()
                        
                        # Ensure datetime is timezone-aware
                        usbl_export['datetime'] = pd.to_datetime(usbl_export['datetime'])
                        if usbl_export['datetime'].dt.tz is None:
                            usbl_export['datetime'] = usbl_export['datetime'].dt.tz_localize('UTC')
                        
                        # Add UTM coordinates if not present
                        if 'easting' not in usbl_export.columns or 'northing' not in usbl_export.columns:
                            usbl_export = add_utm_coords(
                                usbl_export,
                                lat_col="latitude_deg",
                                lon_col="longitude_deg",
                                utm_zone=utm_zone,
                                northern=northern
                            )
                            # Rename X_Center/Y_Center to easting/northing
                            if 'X_Center' in usbl_export.columns:
                                usbl_export['easting'] = usbl_export['X_Center']
                                usbl_export['northing'] = usbl_export['Y_Center']
                        
                        # Required columns for USBL
                        required_usbl_cols = ['datetime', 'latitude_deg', 'longitude_deg', 
                                             'easting', 'northing', 
                                             'hor_err_major', 'hor_err_minor', 'hor_err_dir']
                        
                        # Optional columns
                        optional_usbl_cols = ['depth_m', 'beacon_name', 'fix_status', 'depth_error']
                        
                        # Check for missing required columns
                        missing_cols = [col for col in required_usbl_cols if col not in usbl_export.columns]
                        if missing_cols:
                            st.error(f"❌ USBL data missing required columns: {', '.join(missing_cols)}")
                            st.stop()
                        
                        # Build final column list
                        usbl_final_cols = required_usbl_cols + [c for c in optional_usbl_cols if c in usbl_export.columns]
                        usbl_export_final = usbl_export[usbl_final_cols]
                        
                        # Format datetime to milliseconds (3 decimals) for CSV export
                        usbl_export_csv = usbl_export_final.copy()
                        usbl_export_csv['datetime'] = usbl_export_csv['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S.%f').str[:-3] + '+00:00'
                        
                        # Convert to CSV and store in session state
                        st.session_state['dredge_usbl_csv'] = usbl_export_csv.to_csv(index=False)
                        st.session_state['dredge_usbl_stats'] = f"{len(usbl_export_final)} points, {len(usbl_final_cols)} columns"
                        
                        st.success(f"✅ USBL file ready: {st.session_state['dredge_usbl_stats']}")
                        
                        # === SENSOR FILE ===
                        if has_sensor or has_winch:
                            # Collect all unique datetimes
                            all_datetimes = []
                            
                            if has_sensor:
                                for df in sensor_data_dict.values():
                                    all_datetimes.append(df['datetime'])
                            
                            if has_winch:
                                all_datetimes.append(trimmed_winch['datetime'])
                            
                            # Combine and get unique sorted datetimes
                            if all_datetimes:
                                combined_times = pd.concat(all_datetimes).drop_duplicates().sort_values()
                                sensor_export = pd.DataFrame({'datetime': combined_times})
                                
                                # Merge sensor files with prefixed columns
                                if has_sensor:
                                    for file_name, df in sensor_data_dict.items():
                                        numeric_cols = [col for col in df.select_dtypes(include=['number']).columns 
                                                       if col.lower() not in ['index', 'datetime']]
                                        
                                        # Create clean prefix from filename
                                        prefix = file_name.replace('.', '_').replace('-', '_').replace(' ', '_')
                                        rename_map = {col: f"{prefix}_{col}" for col in numeric_cols}
                                        
                                        df_to_merge = df[['datetime'] + numeric_cols].rename(columns=rename_map)
                                        sensor_export = pd.merge(sensor_export, df_to_merge, on='datetime', how='outer')
                                
                                # Merge winch data with WINCH_ prefix
                                if has_winch:
                                    rename_map = {col: f"WINCH_{col}" for col in winch_numeric_cols}
                                    winch_to_merge = trimmed_winch[['datetime'] + winch_numeric_cols].rename(columns=rename_map)
                                    sensor_export = pd.merge(sensor_export, winch_to_merge, on='datetime', how='outer')
                                
                                # Sort and ensure timezone-aware
                                sensor_export = sensor_export.sort_values('datetime').reset_index(drop=True)
                                sensor_export['datetime'] = pd.to_datetime(sensor_export['datetime'])
                                if sensor_export['datetime'].dt.tz is None:
                                    sensor_export['datetime'] = sensor_export['datetime'].dt.tz_localize('UTC')
                                
                                # Calculate stats first (before formatting)
                                time_diffs = sensor_export['datetime'].diff().dt.total_seconds()
                                median_dt = time_diffs.median()
                                freq = 1 / median_dt if median_dt > 0 else 0
                                
                                # Format datetime to milliseconds (3 decimals) for CSV export
                                sensor_export_csv = sensor_export.copy()
                                sensor_export_csv['datetime'] = sensor_export_csv['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S.%f').str[:-3] + '+00:00'
                                
                                # Convert to CSV and store in session state
                                st.session_state['dredge_sensor_csv'] = sensor_export_csv.to_csv(index=False)
                                st.session_state['dredge_sensor_stats'] = f"{len(sensor_export):,} records, {len(sensor_export.columns)-1} columns, ~{freq:.1f} Hz"
                                
                                st.success(f"✅ Sensor file ready: {st.session_state['dredge_sensor_stats']}")
                        else:
                            st.session_state['dredge_sensor_csv'] = None
                        
                    except Exception as e:
                        st.error(f"❌ Export failed: {str(e)}")
                        import traceback
                        st.code(traceback.format_exc())
            
            # === DOWNLOAD BUTTONS (always show if data exists in session state) ===
            if 'dredge_usbl_csv' in st.session_state and st.session_state['dredge_usbl_csv']:
                st.markdown("### 📥 Download Files for Dredge App")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.download_button(
                        label="📍 Download USBL Data",
                        data=st.session_state['dredge_usbl_csv'],
                        file_name=f"{selected_core_export}_dredgeapp_usbl.csv",
                        mime="text/csv",
                        help="USBL position data with error ellipses and UTM coordinates"
                    )
                
                with col2:
                    if 'dredge_sensor_csv' in st.session_state and st.session_state['dredge_sensor_csv']:
                        st.download_button(
                            label="📊 Download Sensor Data",
                            data=st.session_state['dredge_sensor_csv'],
                            file_name=f"{selected_core_export}_dredgeapp_sensor.csv",
                            mime="text/csv",
                            help="Combined sensor and winch time series data"
                        )
                    else:
                        st.info("No sensor/winch data to export")
                
                # === USAGE INSTRUCTIONS ===
                with st.expander("ℹ️ How to use in Dredge App"):
                    st.markdown(f"""
                    **Step 1:** Download both files above
                    
                    **Step 2:** Open Dredge App:
                    ```bash
                    cd dredge_app
                    python dredge_app.py
                    ```
                    
                    **Step 3:** Load the files:
                    - Click "Load USBL Data" → select `{selected_core_export}_dredgeapp_usbl.csv`
                    - Click "Load Sensor Data" → select `{selected_core_export}_dredgeapp_sensor.csv`
                    
                    **Step 4:** Analyze:
                    - Select sensor columns from dropdown to plot
                    - Drag red region on time series to highlight location points
                    - Click "Save Selected Region" to name and save regions
                    - Export data with region tags as CSV or shapefile
                    
                    **Features:**
                    - Interactive time series plotting with auto-downsampling
                    - Linked selection between time series and location map
                    - Error ellipse visualization
                    - Multiple region selection and tagging
                    - Export tagged data for further GIS analysis
                    """)
        
        # ========== SECTION 6: Advanced Merge (Original Feature) ==========
        st.markdown("---")
        st.subheader("🔗 Advanced Merge: Aggregate Sensor Data to USBL Points")
        st.write("Merge sensor/winch data with USBL using aggregation methods (for GIS attribute tables)")
        
        if has_sensor or has_winch:
            # Collect available columns
            all_merge_columns = {}
            
            if has_sensor:
                for file_name, df in sensor_data_dict.items():
                    numeric_cols = [col for col in df.select_dtypes(include=['number']).columns 
                                   if col.lower() not in ['index', 'datetime']]
                    for col in numeric_cols:
                        all_merge_columns[f"{file_name}::{col}"] = (df, col, "sensor")
            
            if has_winch:
                for col in winch_numeric_cols:
                    all_merge_columns[f"WINCH::{col}"] = (trimmed_winch, col, "winch")
            
            if all_merge_columns:
                st.write(f"**Available columns:** {len(all_merge_columns)}")
                
                merge_configs = []
                
                for source_key, (df, column, data_type) in all_merge_columns.items():
                    col1, col2, col3 = st.columns([3, 2, 2])
                    
                    with col1:
                        include = st.checkbox(f"{source_key}", key=f"merge_{source_key}")
                    
                    if include:
                        with col2:
                            method = st.selectbox(
                                "Method",
                                ["mean", "count > threshold", "count < threshold"],
                                key=f"method_{source_key}"
                            )
                        
                        with col3:
                            if "threshold" in method:
                                threshold = st.number_input(
                                    "Threshold",
                                    value=0.0,
                                    step=0.1,
                                    key=f"threshold_{source_key}"
                                )
                            else:
                                threshold = None
                        
                        merge_configs.append({
                            'source_key': source_key,
                            'column': column,
                            'method': method,
                            'threshold': threshold,
                            'df': df,
                            'data_type': data_type
                        })
                
                if merge_configs and st.button("Generate Merged USBL + Aggregated Sensor Data"):
                    with st.spinner("Merging data with USBL..."):
                        try:
                            merged_usbl = all_usbl.reset_index()
                            merged_usbl['datetime'] = pd.to_datetime(merged_usbl['datetime']).dt.tz_localize(None)
                            
                            beacon_names = merged_usbl['beacon_name'].unique() if 'beacon_name' in merged_usbl.columns else [None]
                            
                            for beacon in beacon_names:
                                if beacon is not None:
                                    beacon_mask = merged_usbl['beacon_name'] == beacon
                                else:
                                    beacon_mask = pd.Series([True] * len(merged_usbl))
                                
                                beacon_indices = merged_usbl[beacon_mask].index
                                
                                for config in merge_configs:
                                    column = config['column']
                                    method = config['method']
                                    threshold = config['threshold']
                                    source_df = config['df']
                                    
                                    method_str = method.replace(' ', '_').replace('>', 'gt').replace('<', 'lt')
                                    new_col_name = f"{column}_{method_str}"
                                    
                                    if new_col_name not in merged_usbl.columns:
                                        merged_usbl[new_col_name] = float('nan')
                                    
                                    for i, idx in enumerate(beacon_indices):
                                        current_time = merged_usbl.loc[idx, 'datetime']
                                        
                                        if i < len(beacon_indices) - 1:
                                            next_idx = beacon_indices[i + 1]
                                            next_time = merged_usbl.loc[next_idx, 'datetime']
                                        else:
                                            next_time = current_time + pd.Timedelta(seconds=1)
                                        
                                        interval_mask = (source_df['datetime'] >= current_time) & (source_df['datetime'] < next_time)
                                        interval_data = source_df.loc[interval_mask, column]
                                        
                                        if not interval_data.empty:
                                            if method == "mean":
                                                value = interval_data.mean()
                                            elif method == "count > threshold":
                                                value = (interval_data > threshold).sum()
                                            elif method == "count < threshold":
                                                value = (interval_data < threshold).sum()
                                            else:
                                                value = float('nan')
                                            
                                            merged_usbl.loc[idx, new_col_name] = value
                            
                            st.success(f"✅ Merged data created with {len(merge_configs)} aggregated column(s)")
                            st.dataframe(merged_usbl.head(20), use_container_width=True)
                            
                            merged_csv = merged_usbl.to_csv(index=False)
                            st.download_button(
                                label=f"💾 Download Merged USBL + Aggregated Sensor/Winch",
                                data=merged_csv,
                                file_name=f"{selected_core_export}_usbl_merged.csv",
                                mime="text/csv"
                            )
                            
                        except Exception as e:
                            st.error(f"❌ Error during merge: {str(e)}")
                            import traceback
                            st.code(traceback.format_exc())
        else:
            st.info("No sensor or winch data available for merging.")
    
    else:
        st.info("No USBL data found for this core.")