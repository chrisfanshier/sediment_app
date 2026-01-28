import streamlit as st
import pandas as pd
from db_util import get_connection
from sqlalchemy import text
import os
from config import get_full_path
from utils import load_usbl_file  # Assumes you have a function to load a USBL file as DataFrame
from utils import add_utm_coords  # Make sure this is imported
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
    usbl_file_list = out_df.loc[out_df["core_name"] == selected_core_export, "usbl_files"].values[0]
    usbl_file_list = [f.strip() for f in usbl_file_list.split(",") if f.strip()]
    usbl_dfs = []
    for fname in usbl_file_list:
        row = usbl_df[usbl_df["file_name"] == fname]
        if not row.empty:
            file_path = row.iloc[0].get("file_path", "")
            # Correct: join file_path and fname to make the relative path
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
        all_usbl = all_usbl[~all_usbl.index.duplicated(keep='first')]
        all_usbl = all_usbl.sort_index()
        csv = all_usbl.reset_index().to_csv(index=False)
        st.download_button(
            label=f"💾 Download all USBL data for {selected_core_export}",
            data=csv,
            file_name=f"{selected_core_export}_usbl.csv",
            mime="text/csv"
        )

        # --- UTM Ellipse Export Button ---
        st.markdown("### Export USBL Error Ellipses with UTM Coordinates for ArcGIS Pro")
        utm_zone = st.number_input("UTM Zone", min_value=1, max_value=60, value=33)
        northern = st.radio("Hemisphere", ["Northern", "Southern"]) == "Northern"
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
        st.markdown("### Export USBL Error Ellipses as Polygon Layer (QGIS & ArcGIS Pro)")

        if st.button("Download Ellipse Polygons (Shapefile, ZIP)"):
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
            # Save to a temporary Shapefile (as a zip for download)
            import zipfile
            with tempfile.TemporaryDirectory() as tmpdir:
                shp_path = os.path.join(tmpdir, "usbl_ellipses.shp")
                gdf.to_file(shp_path, driver="ESRI Shapefile")
                zip_path = os.path.join(tmpdir, f"{selected_core_export}_usbl_ellipses.zip")
                with zipfile.ZipFile(zip_path, "w") as zipf:
                    for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
                        file = os.path.join(tmpdir, f"usbl_ellipses{ext}")
                        if os.path.exists(file):
                            zipf.write(file, arcname=f"usbl_ellipses{ext}")
                with open(zip_path, "rb") as f:
                    st.download_button(
                        label="💾 Download Ellipse Polygons (Shapefile, ZIP)",
                        data=f.read(),
                        file_name=f"{selected_core_export}_usbl_ellipses.zip",
                        mime="application/zip"
                    )
    else:
        st.info("No USBL data found for this core.")
    
    # --- Sensor files for the selected core ---
    st.markdown("---")
    st.subheader(f"Sensor files for core: {selected_core_export}")
    
    # Get core_id for the selected core
    selected_core_row = df_dredge[df_dredge["core_name"] == selected_core_export].iloc[0]
    selected_core_id = int(selected_core_row["core_id"])
    
    # Query sensor files
    with get_connection() as conn:
        sensor_query = text("""
            SELECT file_id, file_name, file_path, sensor_type, sensor_location
            FROM sensor_files
            WHERE core_id = :core_id
            ORDER BY file_name
        """)
        sensor_files_df = pd.read_sql(sensor_query, conn, params={"core_id": selected_core_id})
    
    if sensor_files_df.empty:
        st.info("No sensor files found for this core.")
    else:
        st.write(f"Found {len(sensor_files_df)} sensor file(s)")
        
        # Display each sensor file with preview
        for idx, sensor_row in sensor_files_df.iterrows():
            file_name = sensor_row['file_name']
            file_path = sensor_row['file_path']
            sensor_type = sensor_row['sensor_type'] if sensor_row['sensor_type'] else "Unknown"
            sensor_location = sensor_row['sensor_location'] if sensor_row['sensor_location'] else "N/A"
            
            with st.expander(f"📊 {file_name} ({sensor_type} - {sensor_location})"):
                relative_path = os.path.join(file_path, file_name)
                file_ext = os.path.splitext(file_name)[1].lower()
                sensor_type_lower = sensor_type.lower()
                
                try:
                    # Load the file
                    from utils import process_rsk_data, process_star_oddi_data
                    
                    if file_ext == '.rsk' or 'rbr' in sensor_type_lower:
                        df = process_rsk_data(relative_path)
                    elif file_ext in ['.dat', '.acc'] or 'star-oddi' in sensor_type_lower or 'staroddi' in sensor_type_lower:
                        df = process_star_oddi_data(relative_path)
                    else:
                        st.warning(f"⚠️ Unsupported file type: {file_ext}")
                        continue
                    
                    if df is not None:
                        # Ensure datetime column exists
                        if 'datetime' not in df.columns:
                            if 'Timestamp' in df.columns:
                                df['datetime'] = df['Timestamp']
                            else:
                                st.error("❌ No datetime column found in data")
                                continue
                        
                        # Show preview
                        st.write(f"**Records:** {len(df):,}")
                        st.write(f"**Time range:** {df['datetime'].min()} to {df['datetime'].max()}")
                        st.dataframe(df.head(10), use_container_width=True)
                    else:
                        st.error("❌ Failed to load data from file")
                        
                except Exception as e:
                    st.error(f"❌ Error loading file: {str(e)}")
    
    # --- Merge sensor data with USBL data ---
    if not sensor_files_df.empty and usbl_dfs:
        st.markdown("---")
        st.subheader("Merge Sensor Data with USBL")
        
        # Collect all sensor data and available columns
        sensor_data_dict = {}  # {file_name: dataframe}
        all_sensor_columns = {}  # {file_name: [list of numeric columns]}
        
        for idx, sensor_row in sensor_files_df.iterrows():
            file_name = sensor_row['file_name']
            file_path = sensor_row['file_path']
            sensor_type = sensor_row['sensor_type'] if sensor_row['sensor_type'] else "Unknown"
            
            relative_path = os.path.join(file_path, file_name)
            file_ext = os.path.splitext(file_name)[1].lower()
            sensor_type_lower = sensor_type.lower()
            
            try:
                from utils import process_rsk_data, process_star_oddi_data
                
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
                    
                    # Get numeric columns (exclude datetime, timestamp, index)
                    numeric_cols = [col for col in df.select_dtypes(include=['number']).columns 
                                   if col.lower() not in ['index', 'datetime']]
                    
                    if numeric_cols:
                        sensor_data_dict[file_name] = df
                        all_sensor_columns[file_name] = numeric_cols
                        
            except Exception as e:
                st.warning(f"Could not load {file_name} for merging: {str(e)}")
        
        if sensor_data_dict:
            st.write(f"Found {len(sensor_data_dict)} sensor file(s) available for merging")
            
            # Let user select columns and aggregation method
            st.write("**Select columns to merge with USBL data:**")
            
            merge_configs = []  # List of {file_name, column, method, threshold}
            
            for file_name, columns in all_sensor_columns.items():
                with st.expander(f"📊 {file_name}"):
                    for col in columns:
                        col1, col2, col3 = st.columns([3, 2, 2])
                        
                        with col1:
                            include = st.checkbox(f"{col}", key=f"merge_{file_name}_{col}")
                        
                        if include:
                            with col2:
                                method = st.selectbox(
                                    "Method",
                                    ["mean", "count > threshold", "count < threshold"],
                                    key=f"method_{file_name}_{col}"
                                )
                            
                            with col3:
                                if "threshold" in method:
                                    threshold = st.number_input(
                                        "Threshold",
                                        value=0.0,
                                        step=0.1,
                                        key=f"threshold_{file_name}_{col}"
                                    )
                                else:
                                    threshold = None
                            
                            merge_configs.append({
                                'file_name': file_name,
                                'column': col,
                                'method': method,
                                'threshold': threshold
                            })
            
            if merge_configs and st.button("Generate Merged USBL Data"):
                with st.spinner("Merging sensor data with USBL..."):
                    try:
                        # Start with the concatenated USBL data
                        merged_usbl = all_usbl.reset_index()
                        
                        # Remove timezone from USBL datetime
                        merged_usbl['datetime'] = pd.to_datetime(merged_usbl['datetime']).dt.tz_localize(None)
                        
                        # Get unique beacon names
                        beacon_names = merged_usbl['beacon_name'].unique()
                        
                        # For each beacon, calculate time intervals and merge sensor data
                        for beacon in beacon_names:
                            beacon_mask = merged_usbl['beacon_name'] == beacon
                            beacon_times = merged_usbl.loc[beacon_mask, 'datetime'].sort_values()
                            
                            # For each selected column, create a new column in merged_usbl
                            for config in merge_configs:
                                file_name = config['file_name']
                                column = config['column']
                                method = config['method']
                                threshold = config['threshold']
                                
                                # Get sensor data
                                sensor_df = sensor_data_dict[file_name].copy()
                                sensor_df['datetime'] = pd.to_datetime(sensor_df['datetime']).dt.tz_localize(None)
                                
                                # Create column name (without beacon name - GIS can filter by beacon_name)
                                method_str = method.replace(' ', '_').replace('>', 'gt').replace('<', 'lt')
                                new_col_name = f"{column}_{method_str}"
                                
                                # Initialize column with NaN if it doesn't exist
                                if new_col_name not in merged_usbl.columns:
                                    merged_usbl[new_col_name] = float('nan')
                                
                                # For each USBL measurement for this beacon
                                beacon_indices = merged_usbl[beacon_mask].index
                                for i, idx in enumerate(beacon_indices):
                                    current_time = merged_usbl.loc[idx, 'datetime']
                                    
                                    # Find next time for this beacon to define interval
                                    if i < len(beacon_indices) - 1:
                                        next_idx = beacon_indices[i + 1]
                                        next_time = merged_usbl.loc[next_idx, 'datetime']
                                    else:
                                        # Last measurement - use a small window
                                        next_time = current_time + pd.Timedelta(seconds=1)
                                    
                                    # Find sensor measurements in this interval
                                    interval_mask = (sensor_df['datetime'] >= current_time) & (sensor_df['datetime'] < next_time)
                                    interval_data = sensor_df.loc[interval_mask, column]
                                    
                                    # Apply aggregation method
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
                        
                        # Show preview
                        st.success(f"✅ Merged data created with {len(merge_configs)} sensor column(s)")
                        st.write("**Preview of merged data:**")
                        st.dataframe(merged_usbl.head(20), use_container_width=True)
                        
                        # Download button
                        merged_csv = merged_usbl.to_csv(index=False)
                        st.download_button(
                            label=f"💾 Download Merged USBL + Sensor Data",
                            data=merged_csv,
                            file_name=f"{selected_core_export}_usbl_sensor_merged.csv",
                            mime="text/csv"
                        )
                        
                    except Exception as e:
                        st.error(f"❌ Error during merge: {str(e)}")
                        import traceback
                        st.code(traceback.format_exc())
        else:
            st.info("No sensor files with numeric columns available for merging.")
    
    # --- Winch data for this cruise ---
    if usbl_dfs:
        st.markdown("---")
        st.subheader("Winch Data")
        
        # Get the time range from USBL data
        usbl_times = all_usbl.reset_index()
        usbl_times['datetime'] = pd.to_datetime(usbl_times['datetime']).dt.tz_localize(None)
        usbl_start = usbl_times['datetime'].min()
        usbl_end = usbl_times['datetime'].max()
        
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
        
        if winch_files_df.empty:
            st.info("No winch files found for this cruise.")
        else:
            # Parse timestamps row by row AND remove timezone in one step
            def parse_and_strip_tz(x):
                dt = pd.to_datetime(x, errors="coerce")
                if dt is pd.NaT:
                    return dt
                # Remove timezone if present
                if hasattr(dt, 'tz') and dt.tz is not None:
                    return dt.tz_localize(None)
                return dt
            
            winch_files_df["start_time"] = winch_files_df["start_time"].apply(parse_and_strip_tz)
            winch_files_df["end_time"] = winch_files_df["end_time"].apply(parse_and_strip_tz)
            
            # Show all winch files
            st.write(f"**Found {len(winch_files_df)} winch file(s) for this cruise:**")
            st.dataframe(winch_files_df[['file_name', 'start_time', 'end_time']], use_container_width=True)
            
            # Find overlapping winch files
            overlap_mask = (
                (winch_files_df['start_time'] <= usbl_end) & 
                (winch_files_df['end_time'] >= usbl_start)
            )
            overlapping_winch = winch_files_df[overlap_mask]
            
            if overlapping_winch.empty:
                st.info("No winch files overlap with USBL time range.")
            else:
                st.write(f"Found {len(overlapping_winch)} winch file(s) overlapping with USBL data:")
                st.dataframe(overlapping_winch[['file_name', 'start_time', 'end_time']], use_container_width=True)
                
                # Load and parse winch files
                winch_dfs = []
                for idx, winch_row in overlapping_winch.iterrows():
                    file_name = winch_row['file_name']
                    file_path = winch_row['file_path']
                    settings = winch_row['settings']
                    
                    try:
                        from utils import parse_winch_dat
                        import json
                        
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
                                st.error(f"❌ No datetime column in {file_name}")
                                continue
                            
                            winch_dfs.append(df)
                            st.success(f"✅ Loaded {file_name}: {len(df):,} records")
                        else:
                            st.error(f"❌ Failed to parse {file_name}")
                            
                    except Exception as e:
                        st.error(f"❌ Error loading {file_name}: {str(e)}")
                
                if winch_dfs:
                    # Concatenate if multiple files
                    if len(winch_dfs) > 1:
                        all_winch = pd.concat(winch_dfs, ignore_index=True)
                        all_winch = all_winch.sort_values('datetime').reset_index(drop=True)
                        st.write(f"**Concatenated {len(winch_dfs)} winch files**")
                    else:
                        all_winch = winch_dfs[0]
                    
                    # Remove timezone if present
                    all_winch['datetime'] = pd.to_datetime(all_winch['datetime']).dt.tz_localize(None)
                    
                    # Trim to USBL time range
                    trim_mask = (all_winch['datetime'] >= usbl_start) & (all_winch['datetime'] <= usbl_end)
                    trimmed_winch = all_winch[trim_mask].copy()
                    
                    st.write(f"**Trimmed to USBL time range:** {len(all_winch):,} → {len(trimmed_winch):,} records")
                    st.write(f"**Time range:** {trimmed_winch['datetime'].min()} to {trimmed_winch['datetime'].max()}")
                    
                    # Get numeric columns
                    exclude_cols = ['index', 'datetime', 'date', 'time', 'year', 'month', 'day', 'hour', 'minute', 'second']
                    numeric_cols = [col for col in trimmed_winch.select_dtypes(include=['number']).columns 
                                   if col.lower() not in exclude_cols]
                    st.write(f"**Available parameters:** {', '.join(numeric_cols)}")
                    
                    # Preview
                    with st.expander("Preview Winch Data"):
                        st.dataframe(trimmed_winch.head(20), use_container_width=True)
                else:
                    st.info("No winch data could be loaded.")