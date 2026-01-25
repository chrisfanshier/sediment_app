import streamlit as st
import pandas as pd
from db_util import get_connection
from sqlalchemy import text
from pathlib import Path
import json
import os
from utils import process_star_oddi_data, parse_winch_dat
from config import get_full_path

st.title("Export Dredge Sensor + USBL + Winch Data")

# ============================================================================
# 1. GET CRUISE SELECTION
# ============================================================================
with get_connection() as conn:
    cruises = pd.read_sql(
        text("SELECT DISTINCT c.cruise_id, c.cruise_name "
             "FROM cruises c JOIN cores co ON c.cruise_id = co.cruise_id "
             "ORDER BY c.cruise_name"),
        conn
    )

if cruises.empty:
    st.info("No cruises with cores found.")
    st.stop()

cruise_map = {row.cruise_name: row.cruise_id for _, row in cruises.iterrows()}
selected = st.selectbox("Select cruise", ["-- choose --"] + list(cruise_map.keys()))
if not selected or selected == "-- choose --":
    st.stop()

cruise_id = cruise_map[selected]

# ============================================================================
# 2. GET ALL CORES FOR THE CRUISE
# ============================================================================
with get_connection() as conn:
    cores = pd.read_sql(
        text("SELECT * FROM cores WHERE cruise_id = :cruise_id ORDER BY core_name"),
        conn,
        params={"cruise_id": cruise_id}
    )

if cores.empty:
    st.info("No cores for selected cruise.")
    st.stop()

# ============================================================================
# 3. SELECT A SPECIFIC CORE TO PROCESS
# ============================================================================
core_map = {row.core_name: row.core_id for _, row in cores.iterrows()}
selected_core = st.selectbox("Select core/dredge", ["-- choose --"] + list(core_map.keys()))
if not selected_core or selected_core == "-- choose --":
    st.stop()

core_id = core_map[selected_core]

# ============================================================================
# 4. PARSE CORE START/END TIMES WITH MIDNIGHT ROLLOVER HANDLING
# ============================================================================
core_info = cores[cores['core_id'] == core_id].iloc[0]

date_col = next((c for c in ("date", "core_date") if c in cores.columns), None)
launch_col = next((c for c in ("time_launched", "time_launch", "time_launched_utc") if c in cores.columns), None)
recover_col = next((c for c in ("time_recovered", "time_recover", "time_recovered_utc") if c in cores.columns), None)

if not (date_col and launch_col and recover_col):
    st.error("Cores missing required date/time columns (date + time_launched + time_recovered).")
    st.stop()

start_datetime = pd.to_datetime(core_info[date_col]) + pd.to_timedelta(str(core_info[launch_col]))
end_datetime = pd.to_datetime(core_info[date_col]) + pd.to_timedelta(str(core_info[recover_col]))

# Handle midnight rollover
if end_datetime < start_datetime:
    end_datetime += pd.Timedelta(days=1)

# Make timezone-aware (UTC) to match USBL data
start_datetime = start_datetime.tz_localize('UTC')
end_datetime = end_datetime.tz_localize('UTC')

st.subheader(f"Processing: {selected_core}")
st.write(f"**Deployment window:**")
st.write(f"- Start: {start_datetime}")
st.write(f"- End: {end_datetime}")
st.write(f"- Duration: {end_datetime - start_datetime}")

# ============================================================================
# 5. LOAD SENSOR FILES (Star Oddi)
# ============================================================================
st.subheader("Loading sensor data...")

with get_connection() as conn:
    sensor_files = pd.read_sql(
        text("""
            SELECT file_id, file_name, file_path, sensor_type
            FROM sensor_files 
            WHERE core_id = :core_id
            ORDER BY sensor_type, file_name
        """),
        conn,
        params={"core_id": core_id}
    )

if not sensor_files.empty:
    st.write(f"**Sensor files ({len(sensor_files)}):**")
    st.dataframe(sensor_files[['file_name', 'sensor_type']], use_container_width=True)
    
    # Load all sensor files
    sensor_dfs = {}
    for _, row in sensor_files.iterrows():
        # Combine file_path (subdirectory) and file_name
        relative_path = os.path.join(row['file_path'], row['file_name'])
        file_path = get_full_path(relative_path)
        sensor_type = row['sensor_type']
        
        try:
            df = process_star_oddi_data(file_path)
            
            if df is not None:
                # Set Timestamp as index and make timezone-aware
                df.set_index('Timestamp', inplace=True)
                if df.index.tz is None:
                    df.index = df.index.tz_localize('UTC')
                
                # Store with descriptive key
                key = f"{sensor_type}_{row['file_id']}"
                sensor_dfs[key] = df
                
                st.success(f"✓ Loaded {row['file_name']}: {len(df)} rows, {df.index[0]} to {df.index[-1]}")
                st.write(f"**Preview of {row['file_name']} ({sensor_type}):**")
                st.dataframe(df.head(10), use_container_width=True)
                st.write("Columns:", list(df.columns))
            else:
                st.error(f"✗ Failed to parse {row['file_name']}")
                
        except Exception as e:
            st.error(f"✗ Error loading {row['file_name']}: {e}")
    
    # Merge all sensor DataFrames on timestamp
    if sensor_dfs:
        # Start with first DataFrame
        combined_sensors = list(sensor_dfs.values())[0].copy()
        
        # Join the rest (outer join to keep all timestamps)
        for key, df in list(sensor_dfs.items())[1:]:
            combined_sensors = combined_sensors.join(df, how='outer', rsuffix=f'_{key}')
        
        # Sort by timestamp
        combined_sensors.sort_index(inplace=True)
        
        st.write(f"**Combined sensor data:**")
        st.write(f"- Shape: {combined_sensors.shape}")
        st.write(f"- Time range: {combined_sensors.index[0]} to {combined_sensors.index[-1]}")
        st.write(f"- Columns: {list(combined_sensors.columns)}")
        st.dataframe(combined_sensors.head(10), use_container_width=True)
        
        # Check sampling rate
        time_diffs = combined_sensors.index.to_series().diff()
        median_interval = time_diffs.median()
        st.write(f"- Median sampling interval: {median_interval}")
        if median_interval and median_interval.total_seconds() > 0:
            st.write(f"- Approximate frequency: {1 / median_interval.total_seconds():.2f} Hz")
    else:
        combined_sensors = None
else:
    st.info("No sensor files found for this core")
    combined_sensors = None

# ============================================================================
# 6. LOAD USBL FILES
# ============================================================================
st.subheader("Loading USBL data...")

def load_usbl_file(file_path):
    """Load a USBL file and return DataFrame with datetime index"""
    try:
        # Read the CSV
        df = pd.read_csv(
            file_path,
            header=None,
            names=[
                "ID","utc_time","beacon_name","fix_status","latitude_deg","longitude_deg",
                "depth_m","northing_error_m","easting_error_m","vertical_error_m",
                "quality","reserved_1","reserved_2","reserved_3","checksum",
            ],
            dtype={"utc_time": str},
        )
        st.write(f"Loaded USBL file: {file_path}")
        st.write("Columns:", list(df.columns))
        st.dataframe(df.head(10), use_container_width=True)
        
        # Extract date from filename
        file_name = Path(file_path).name
        date_str = file_name.split("_")[1]  # "PSONLLD_20251018_000000.txt" -> "20251018"
        
        # Build UTC datetime
        df["datetime"] = pd.to_datetime(
            date_str + " " + df["utc_time"].astype(str),
            format="%Y%m%d %H%M%S.%f",
            utc=True
        )
        
        # Handle midnight rollover
        time_values = pd.to_datetime(df["utc_time"], format="%H%M%S.%f", errors="coerce")
        if len(time_values) > 1:
            first_time = time_values.iloc[0]
            last_time = time_values.iloc[-1]
            if not pd.isna(first_time) and not pd.isna(last_time):
                if first_time.time() > last_time.time():
                    # Find the rollover point
                    rollover_idx = (time_values.diff() < pd.Timedelta(0)).idxmax()
                    if rollover_idx > 0:
                        df.loc[:rollover_idx-1, "datetime"] -= pd.Timedelta(days=1)
        
        # Set datetime as index
        df.set_index("datetime", inplace=True)
        
        # Keep only the columns we need
        usbl_df = df[["latitude_deg", "longitude_deg", "depth_m", "beacon_name", 
                      "fix_status", "quality", "northing_error_m", "easting_error_m", 
                      "vertical_error_m"]].copy()
        
        st.write(f"Preview of parsed USBL data from {file_name}:")
        st.dataframe(usbl_df.head(10), use_container_width=True)
        st.write("Index dtype:", usbl_df.index.dtype)
        st.write("Non-null latitude_deg:", usbl_df['latitude_deg'].notna().sum())
        
        return usbl_df
        
    except Exception as e:
        st.error(f"Error loading USBL file: {e}")
        return None

# Get USBL files for the cruise
with get_connection() as conn:
    usbl_files = pd.read_sql(
        text("""
            SELECT usbl_file_id, file_name, file_path, start_time, end_time
            FROM usbl_files 
            WHERE cruise_id = :cruise_id
        """),
        conn,
        params={"cruise_id": cruise_id}
    )

if not usbl_files.empty:
    # Filter USBL files by time overlap
    usbl_files["start_time"] = pd.to_datetime(usbl_files["start_time"], errors="coerce", utc=True)
    usbl_files["end_time"] = pd.to_datetime(usbl_files["end_time"], errors="coerce", utc=True)
    
    mask = (usbl_files["start_time"] <= end_datetime) & (usbl_files["end_time"] >= start_datetime)
    matched_usbl = usbl_files[mask]
    
    st.write(f"**Matching USBL files ({len(matched_usbl)}):**")
    st.dataframe(matched_usbl[['file_name', 'start_time', 'end_time']], use_container_width=True)
    
    # Load USBL files
    usbl_dfs = []
    for _, row in matched_usbl.iterrows():
        # Combine file_path (subdirectory) and file_name
        relative_path = os.path.join(row['file_path'], row['file_name'])
        file_path = get_full_path(relative_path)
        
        try:
            df = load_usbl_file(file_path)
            
            if df is not None:
                usbl_dfs.append(df)
                st.success(f"✓ Loaded {row['file_name']}: {len(df)} fixes, {df.index[0]} to {df.index[-1]}")
            else:
                st.error(f"✗ Failed to parse {row['file_name']}")
                
        except Exception as e:
            st.error(f"✗ Error loading {row['file_name']}: {e}")
    
    # Concatenate all USBL files
    if usbl_dfs:
        combined_usbl = pd.concat(usbl_dfs)
        combined_usbl.sort_index(inplace=True)
        
        # Remove duplicates if any (same timestamp)
        combined_usbl = combined_usbl[~combined_usbl.index.duplicated(keep='first')]
        
        st.write(f"**Combined USBL data:**")
        st.write(f"- Total fixes: {len(combined_usbl)}")
        st.write(f"- Time range: {combined_usbl.index[0]} to {combined_usbl.index[-1]}")
        st.write(f"- Unique beacons: {combined_usbl['beacon_name'].unique()}")
        st.dataframe(combined_usbl.head(10), use_container_width=True)
        
        # Calculate approximate ping interval
        time_diffs = combined_usbl.index.to_series().diff()
        median_interval = time_diffs.median()
        st.write(f"- Median ping interval: {median_interval}")
    else:
        combined_usbl = None
else:
    st.info("No USBL files found for this cruise")
    combined_usbl = None

# ============================================================================
# 7. LOAD WINCH FILES
# ============================================================================
st.subheader("Loading winch data...")

# Get winch files that overlap with this core's time window
with get_connection() as conn:
    winch_files = pd.read_sql(
        text("""
            SELECT winch_file_id, file_name, file_path, start_time, end_time, settings
            FROM winch_data 
            WHERE cruise_id = :cruise_id
        """),
        conn,
        params={"cruise_id": cruise_id}
    )

if not winch_files.empty:
    # Parse start/end times (they're stored as text in the database)
    winch_files["start_time"] = pd.to_datetime(winch_files["start_time"], errors="coerce", utc=True)
    winch_files["end_time"] = pd.to_datetime(winch_files["end_time"], errors="coerce", utc=True)
    
    # Filter by time overlap with core deployment
    mask = (winch_files["start_time"] <= end_datetime) & (winch_files["end_time"] >= start_datetime)
    matched_winch = winch_files[mask]
    
    st.write(f"**Matching winch files ({len(matched_winch)}):**")
    st.dataframe(matched_winch[['file_name', 'start_time', 'end_time']], use_container_width=True)
    
    # Load winch files
    winch_dfs = []
    for _, row in matched_winch.iterrows():
        # Combine file_path (subdirectory) and file_name
        relative_path = os.path.join(row['file_path'], row['file_name'])
        file_path = get_full_path(relative_path)
        settings = json.loads(row['settings'])
        
        try:
            df = parse_winch_dat(file_path, settings)
            
            if df is not None and 'datetime' in df.columns:
                # Set datetime as index and make timezone-aware
                df.set_index('datetime', inplace=True)
                if df.index.tz is None:
                    df.index = df.index.tz_localize('UTC')
                
                winch_dfs.append(df)
                st.success(f"✓ Loaded {row['file_name']}: {len(df)} records, {df.index[0]} to {df.index[-1]}")
                st.write(f"**Preview of {row['file_name']}:**")
                st.dataframe(df.head(10), use_container_width=True)
                st.write("Columns:", list(df.columns))
            else:
                st.error(f"✗ Failed to parse {row['file_name']}")
                
        except Exception as e:
            st.error(f"✗ Error loading {row['file_name']}: {e}")
    
    # Concatenate all winch files
    if winch_dfs:
        combined_winch = pd.concat(winch_dfs)
        combined_winch.sort_index(inplace=True)
        
        # Remove duplicates if any
        combined_winch = combined_winch[~combined_winch.index.duplicated(keep='first')]
        
        st.write(f"**Combined winch data:**")
        st.write(f"- Total records: {len(combined_winch)}")
        st.write(f"- Time range: {combined_winch.index[0]} to {combined_winch.index[-1]}")
        st.write(f"- Columns: {list(combined_winch.columns)}")
        st.dataframe(combined_winch.head(10), use_container_width=True)
        
        # Calculate sampling rate
        time_diffs = combined_winch.index.to_series().diff()
        median_interval = time_diffs.median()
        st.write(f"- Median sampling interval: {median_interval}")
        if median_interval and median_interval.total_seconds() > 0:
            st.write(f"- Approximate frequency: {1 / median_interval.total_seconds():.2f} Hz")
    else:
        combined_winch = None
else:
    st.info("No winch files found for this cruise")
    combined_winch = None

# ============================================================================
# 8. COMBINE ALL DATA AND EXPORT TO CSV
# ============================================================================
st.subheader("Combining all data sources...")

# Determine master timeline based on highest frequency data available
# Winch (20 Hz) > Sensors (10 Hz) > USBL (0.033 Hz)

if combined_winch is not None:
    master_df = combined_winch.copy()
    st.write(f"Using winch data as master timeline (~20 Hz): {len(master_df)} records")
    st.write("Preview of master_df (winch):")
    st.dataframe(master_df.head(10), use_container_width=True)
    master_source = "winch"
elif combined_sensors is not None:
    master_df = combined_sensors.copy()
    st.write(f"Using sensor data as master timeline (~10 Hz): {len(master_df)} records")
    st.write("Preview of master_df (sensors):")
    st.dataframe(master_df.head(10), use_container_width=True)
    master_source = "sensors"
else:
    st.error("No high-frequency data (winch or sensors) available!")
    st.stop()

# Add sensor data if winch was master
if master_source == "winch" and combined_sensors is not None:
    master_df = master_df.join(combined_sensors, how='left', rsuffix='_sensor')
    st.write(f"Added sensor data: {len(combined_sensors)} records")
    st.write("Preview after adding sensors:")
    st.dataframe(master_df.head(10), use_container_width=True)

# Add winch data if sensors was master
if master_source == "sensors" and combined_winch is not None:
    master_df = master_df.join(combined_winch, how='left', rsuffix='_winch')
    st.write(f"Added winch data: {len(combined_winch)} records")
    st.write("Preview after adding winch:")
    st.dataframe(master_df.head(10), use_container_width=True)

# Add USBL data (will have NaNs for non-ping times)
if combined_usbl is not None:
    master_df = master_df.join(combined_usbl, how='left', rsuffix='_usbl')
    actual_fixes = master_df['latitude_deg'].notna().sum()
    st.write(f"Added USBL data: {actual_fixes} actual fixes out of {len(master_df)} total records")
    st.write("Preview after adding USBL:")
    st.dataframe(master_df.head(10), use_container_width=True)
else:
    st.warning("No USBL data to add")

# Filter to deployment time window (already calculated with midnight rollover handling)
st.write(f"**Filtering to core deployment window:**")
st.write(f"- Start: {start_datetime}")
st.write(f"- End: {end_datetime}")
st.write(f"- Duration: {end_datetime - start_datetime}")

deployment_df = master_df.loc[start_datetime:end_datetime].copy()

st.write(f"**Final combined dataset (truncated to deployment):**")
st.write(f"- Total records: {len(deployment_df)}")
st.write(f"- Columns: {len(deployment_df.columns)}")
st.write(f"- Time range: {deployment_df.index[0]} to {deployment_df.index[-1]}")
st.write(f"- Master timeline source: {master_source}")
st.write("Preview of deployment_df:")
st.dataframe(deployment_df.head(10), use_container_width=True)

# Show column summary
st.write("**Column summary:**")
col_summary = pd.DataFrame({
    'Column': deployment_df.columns,
    'Non-null count': [deployment_df[col].notna().sum() for col in deployment_df.columns],
    'Null count': [deployment_df[col].isna().sum() for col in deployment_df.columns],
    'Data type': [deployment_df[col].dtype for col in deployment_df.columns]
})
st.dataframe(col_summary, use_container_width=True)

# Preview the data
st.write("**Preview (first 20 rows):**")
st.dataframe(deployment_df.head(20), use_container_width=True)

# Export to CSV
st.subheader("Export to CSV")

output_filename = f"{selected_core}_combined_raw.csv"

if st.button("Download CSV"):
    # Reset index to include timestamp as a column
    export_df = deployment_df.reset_index()
    export_df.rename(columns={'index': 'timestamp'}, inplace=True)
    
    # Convert to CSV
    csv = export_df.to_csv(index=False)
    
    st.download_button(
        label="💾 Download Combined Data CSV",
        data=csv,
        file_name=output_filename,
        mime="text/csv"
    )
    
    st.success(f"Ready to download {output_filename}")
    st.write(f"File will contain {len(export_df)} rows and {len(export_df.columns)} columns")