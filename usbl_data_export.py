import streamlit as st
import pandas as pd
from db_util import get_connection
from sqlalchemy import text
import os
from config import get_full_path
from utils import load_usbl_file  # Assumes you have a function to load a USBL file as DataFrame
from utils import add_utm_coords  # Make sure this is imported
from utils import ellipse_polygon  
from utils import process_rsk_data, process_star_oddi_data  # For sensor data
import geopandas as gpd
import tempfile

st.title("Cores with USBL and Sensor Data (Cruise → Core)")

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

# safe parsing (invalid → NaT)
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

# --- Core selection for data export ---
core_names = out_df["core_name"].tolist()
selected_core_export = st.selectbox("Select core to view/export data", ["-- choose --"] + core_names)

if selected_core_export and selected_core_export != "-- choose --":
    # Get the core_id for the selected core
    selected_core_row = df_dredge[df_dredge["core_name"] == selected_core_export].iloc[0]
    selected_core_id = selected_core_row.get("core_id")
    
    st.markdown("---")
    st.subheader(f"Data for Core: {selected_core_export}")
    
    # Create tabs for USBL and Sensor data
    tab1, tab2 = st.tabs(["📡 USBL Data", "🌡️ Sensor Data"])
    
    # ==================== USBL DATA TAB ====================
    with tab1:
        usbl_file_list = out_df.loc[out_df["core_name"] == selected_core_export, "usbl_files"].values[0]
        usbl_file_list = [f.strip() for f in usbl_file_list.split(",") if f.strip()]
        
        if not usbl_file_list:
            st.info("No USBL files found for this core.")
        else:
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
                            # Make sure datetime is a column, not index
                            if 'datetime' not in df.columns and df.index.name == 'datetime':
                                df = df.reset_index()
                            usbl_dfs.append(df)
                    except Exception as e:
                        st.error(f"Error loading USBL file {fname}: {e}")
            
            if usbl_dfs:
                # Concatenate all USBL dataframes
                all_usbl = pd.concat(usbl_dfs, ignore_index=True)
                
                # Remove duplicates based on datetime column
                all_usbl = all_usbl.drop_duplicates(subset=['datetime'], keep='first')
                
                # Sort by datetime
                all_usbl = all_usbl.sort_values('datetime').reset_index(drop=True)
                
                # Verify datetime column exists
                if 'datetime' not in all_usbl.columns:
                    st.error("Error: datetime column missing from USBL data")
                else:
                    st.write(f"USBL data loaded: {len(all_usbl)} records")
                    st.write(f"Time range: {all_usbl['datetime'].min()} to {all_usbl['datetime'].max()}")
                    st.write(f"Columns: {list(all_usbl.columns)}")
                    st.dataframe(all_usbl.head(10), use_container_width=True)
                
                # Export CSV with datetime preserved
                csv = all_usbl.to_csv(index=False, date_format='%Y-%m-%d %H:%M:%S.%f')
                st.download_button(
                    label=f"💾 Download all USBL data for {selected_core_export}",
                    data=csv,
                    file_name=f"{selected_core_export}_usbl.csv",
                    mime="text/csv"
                )

                # --- UTM Ellipse Export Button ---
                st.markdown("### Export USBL Error Ellipses with UTM Coordinates for ArcGIS Pro")
                col1, col2 = st.columns(2)
                with col1:
                    utm_zone = st.number_input("UTM Zone", min_value=1, max_value=60, value=33)
                with col2:
                    northern = st.radio("Hemisphere", ["Northern", "Southern"]) == "Northern"
                
                if st.button("Download Error Ellipse Table with UTM"):
                    ellipse_df = add_utm_coords(
                        all_usbl,
                        lat_col="latitude_deg",
                        lon_col="longitude_deg",
                        utm_zone=utm_zone,
                        northern=northern
                    )
                    # Include datetime in export
                    export_cols = ["datetime", "X_Center", "Y_Center", "hor_err_major", "hor_err_minor", "hor_err_dir"]
                    arcgis_df = ellipse_df[export_cols].rename(columns={
                        "hor_err_major": "Semi_Major",
                        "hor_err_minor": "Semi_Minor",
                        "hor_err_dir": "Azimuth"
                    })
                    ellipse_csv = arcgis_df.to_csv(index=False, date_format='%Y-%m-%d %H:%M:%S.%f')
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
                st.info("No USBL data could be loaded for this core.")
    
    # ==================== SENSOR DATA TAB ====================
    with tab2:
        # Query sensor files for this core
        with get_connection() as conn:
            sensor_query = text("""
                SELECT sf.file_id, sf.file_name, sf.file_path, sf.sensor_type, sf.sensor_location,
                       sf.start_time, sf.end_time
                FROM sensor_files sf
                WHERE sf.core_id = :core_id
                ORDER BY sf.file_name
            """)
            sensor_files_df = pd.read_sql(sensor_query, conn, params={"core_id": selected_core_id})
        
        if sensor_files_df.empty:
            st.info("No sensor files found for this core.")
        else:
            st.success(f"✅ Found {len(sensor_files_df)} sensor file(s) for this core")
            
            # Display sensor files info
            st.markdown("### Sensor Files Information")
            st.dataframe(sensor_files_df[['file_name', 'sensor_type', 'sensor_location', 'start_time', 'end_time']], 
                       use_container_width=True)
            
            # Load and display each sensor file separately
            st.markdown("### Sensor Data Previews")
            
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
                        # Determine how to load the file based on extension and sensor type
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
                            
                            # Display metrics
                            st.write(f"**Records:** {len(df):,}")
                            st.write(f"**Time range:** {df['datetime'].min()} to {df['datetime'].max()}")
                            
                            # Display available parameters
                            numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
                            excluded = ['file_id', 'core_id', 'index']
                            available_params = [col for col in numeric_cols if col not in excluded]
                            
                            st.write(f"**Available parameters:** {', '.join(available_params)}")
                            
                            # Preview data
                            st.dataframe(df.head(10), use_container_width=True)
                            
                            # Individual file export
                            csv_data = df.to_csv(index=False, date_format='%Y-%m-%d %H:%M:%S.%f')
                            st.download_button(
                                label=f"💾 Download {file_name}",
                                data=csv_data,
                                file_name=f"{selected_core_export}_{file_name.replace(file_ext, '')}.csv",
                                mime="text/csv",
                                key=f"download_{sensor_row['file_id']}"
                            )
                        else:
                            st.error("❌ Failed to load data from file")
                            
                    except Exception as e:
                        st.error(f"❌ Error loading file: {str(e)}")