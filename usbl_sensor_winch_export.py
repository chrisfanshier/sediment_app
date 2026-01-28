import streamlit as st
import pandas as pd
from db_util import get_connection
from sqlalchemy import text
from pathlib import Path
import json
import os
from utils import process_star_oddi_data, parse_winch_dat, load_usbl_file  # Now imported from utils
from config import get_full_path
import numpy as np

st.title("Export Dredge Sensor + USBL + Winch Data")

# --- Add these functions at the top of your script ---

@st.cache_data(show_spinner="Loading cruise/core lists...")
def get_cruise_core_lists():
    with get_connection() as conn:
        cruises = pd.read_sql(
            text("SELECT DISTINCT c.cruise_id, c.cruise_name "
                 "FROM cruises c JOIN cores co ON c.cruise_id = co.cruise_id "
                 "ORDER BY c.cruise_name"),
            conn
        )
        cores = pd.read_sql(
            text("SELECT * FROM cores WHERE cruise_id = :cruise_id ORDER BY core_name"),
            conn,
            params={"cruise_id": int(cruises.iloc[0]['cruise_id'])} if not cruises.empty else {}
        )
    return cruises, cores

@st.cache_data(show_spinner="Loading sensor files...")
def load_sensor_files(core_id):
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
    return sensor_files

@st.cache_data(show_spinner="Loading USBL files...")
def load_usbl_files(cruise_id):
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
    return usbl_files

@st.cache_data(show_spinner="Loading winch files...")
def load_winch_files(cruise_id):
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
    return winch_files

# ============================================================================
# 1. GET CRUISE SELECTION
# ============================================================================
cruises, cores = get_cruise_core_lists()

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

# Make timezone-naive UTC (strip tzinfo if present)
start_datetime = start_datetime.tz_localize('UTC').tz_localize(None)
end_datetime = end_datetime.tz_localize('UTC').tz_localize(None)

st.subheader(f"Processing: {selected_core}")
st.write(f"**Deployment window:**")
st.write(f"- Start: {start_datetime}")
st.write(f"- End: {end_datetime}")
st.write(f"- Duration: {end_datetime - start_datetime}")

# ============================================================================
# 5. LOAD SENSOR FILES (Star Oddi)
# ============================================================================
st.subheader("Loading sensor data...")

sensor_files = load_sensor_files(core_id)

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
                # Rename Timestamp to datetime and make timezone-naive
                if 'Timestamp' in df.columns and 'datetime' not in df.columns:
                    df = df.rename(columns={'Timestamp': 'datetime'})
                if pd.api.types.is_datetime64_any_dtype(df['datetime']) and getattr(df['datetime'].dt, 'tz', None) is not None:
                    df['datetime'] = df['datetime'].dt.tz_localize(None)
                sensor_dfs[row['file_name']] = df
                st.success(f"✓ Loaded {row['file_name']}: {len(df)} rows, {df['datetime'].min()} to {df['datetime'].max()}")
                st.write(f"**Preview of {row['file_name']} ({sensor_type}):**")
                st.dataframe(df.head(10), use_container_width=True)
                st.write("Columns:", list(df.columns))
            else:
                st.error(f"✗ Failed to parse {row['file_name']}")
        except Exception as e:
            st.error(f"✗ Error loading {row['file_name']}: {e}")   
    
    # Merge all sensor DataFrames on datetime column
    if sensor_dfs:
        # Start with first DataFrame
        combined_sensors = list(sensor_dfs.values())[0].copy()
        
        # Merge the rest (outer merge to keep all timestamps)
        for key, df in list(sensor_dfs.items())[1:]:
            combined_sensors = pd.merge(
                combined_sensors, 
                df, 
                on='datetime', 
                how='outer', 
                suffixes=('', f'_{key}')
            )
        
        # Sort by datetime
        combined_sensors = combined_sensors.sort_values('datetime').reset_index(drop=True)
        
        st.write(f"**Combined sensor data:**")
        st.write(f"- Shape: {combined_sensors.shape}")
        st.write(f"- Time range: {combined_sensors['datetime'].min()} to {combined_sensors['datetime'].max()}")
        st.write(f"- Columns: {list(combined_sensors.columns)}")
        st.dataframe(combined_sensors.head(10), use_container_width=True)
        
        # Check sampling rate
        time_diffs = combined_sensors['datetime'].sort_values().diff()
        median_interval = time_diffs.median()
        st.write(f"- Median sampling interval: {median_interval}")
        if pd.notnull(median_interval):
            # median_interval is a Timedelta, so .total_seconds() is safe
            seconds = median_interval.total_seconds()
            if seconds > 0:
                st.write(f"- Approximate frequency: {1 / seconds:.2f} Hz")
    else:
        combined_sensors = None
else:
    st.info("No sensor files found for this core")
    combined_sensors = None

# ============================================================================
# 6. LOAD USBL FILES
# ============================================================================
st.subheader("Loading USBL data...")

usbl_files = load_usbl_files(cruise_id)

if not usbl_files.empty:
    # Filter USBL files by time overlap
    usbl_files["start_time"] = pd.to_datetime(usbl_files["start_time"], errors="coerce", utc=True)
    usbl_files["end_time"] = pd.to_datetime(usbl_files["end_time"], errors="coerce", utc=True)
    # Make naive
    usbl_files["start_time"] = usbl_files["start_time"].dt.tz_localize(None)
    usbl_files["end_time"] = usbl_files["end_time"].dt.tz_localize(None)
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
                # Make datetime column naive if needed
                if 'datetime' in df.columns and pd.api.types.is_datetime64_any_dtype(df['datetime']) and getattr(df['datetime'].dt, 'tz', None) is not None:
                    df['datetime'] = df['datetime'].dt.tz_localize(None)
                usbl_dfs.append(df)
                st.success(f"✓ Loaded {row['file_name']}: {len(df)} fixes, {df['datetime'].min()} to {df['datetime'].max()}")
            else:
                st.error(f"✗ Failed to parse {row['file_name']}")
        except Exception as e:
            st.error(f"✗ Error loading {row['file_name']}: {e}")
    
    # Concatenate all USBL files
    if usbl_dfs:
        combined_usbl = pd.concat(usbl_dfs, ignore_index=True)
        combined_usbl = combined_usbl.sort_values('datetime').reset_index(drop=True)
        
        # Remove duplicates if any (same timestamp)
        combined_usbl = combined_usbl.drop_duplicates(subset=['datetime'], keep='first')
        
        st.write(f"**Combined USBL data:**")
        st.write(f"- Total fixes: {len(combined_usbl)}")
        st.write(f"- Time range: {combined_usbl['datetime'].min()} to {combined_usbl['datetime'].max()}")
        st.write(f"- Unique beacons: {combined_usbl['beacon_name'].unique()}")
        st.dataframe(combined_usbl.head(10), use_container_width=True)
        
        # Calculate approximate ping interval
        time_diffs = combined_usbl['datetime'].diff()
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
winch_files = load_winch_files(cruise_id)

if not winch_files.empty:
    # Parse start/end times (they're stored as text in the database)
    winch_files["start_time"] = pd.to_datetime(winch_files["start_time"], errors="coerce", utc=True)
    winch_files["end_time"] = pd.to_datetime(winch_files["end_time"], errors="coerce", utc=True)
    # Make naive
    winch_files["start_time"] = winch_files["start_time"].dt.tz_localize(None)
    winch_files["end_time"] = winch_files["end_time"].dt.tz_localize(None)
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
                # Make datetime column naive if needed
                if pd.api.types.is_datetime64_any_dtype(df['datetime']) and getattr(df['datetime'].dt, 'tz', None) is not None:
                    df['datetime'] = df['datetime'].dt.tz_localize(None)
                winch_dfs.append(df)
                st.success(f"✓ Loaded {row['file_name']}: {len(df)} records, {df['datetime'].min()} to {df['datetime'].max()}")
                st.write(f"**Preview of {row['file_name']}:**")
                st.dataframe(df.head(10), use_container_width=True)
                st.write("Columns:", list(df.columns))
            else:
                st.error(f"✗ Failed to parse {row['file_name']}")
        except Exception as e:
            st.error(f"✗ Error loading {row['file_name']}: {e}")
    
    # Concatenate all winch files
    if winch_dfs:
        combined_winch = pd.concat(winch_dfs, ignore_index=True)
        combined_winch = combined_winch.sort_values('datetime').reset_index(drop=True)
        
        # Remove duplicates if any
        combined_winch = combined_winch.drop_duplicates(subset=['datetime'], keep='first')
        
        st.write(f"**Combined winch data:**")
        st.write(f"- Total records: {len(combined_winch)}")
        st.write(f"- Time range: {combined_winch['datetime'].min()} to {combined_winch['datetime'].max()}")
        st.write(f"- Columns: {list(combined_winch.columns)}")
        st.dataframe(combined_winch.head(10), use_container_width=True)
        
        # Calculate sampling rate
        time_diffs = combined_winch['datetime'].diff()
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
# 8. COMBINE SENSOR, USBL, AND WINCH DATA AND EXPORT TO CSV (outer merge, no interpolation)
# ============================================================================
st.subheader("Combining sensor, USBL, and winch data (outer merge, no interpolation)...")

def prep_for_merge(df, name):
    df = df.copy()
    # Ensure 'datetime' is a column (not index)
    if 'datetime' not in df.columns and df.index.name == 'datetime':
        df = df.reset_index()
    # Make datetime column naive if needed
    if 'datetime' in df.columns and pd.api.types.is_datetime64_any_dtype(df['datetime']) and getattr(df['datetime'].dt, 'tz', None) is not None:
        df['datetime'] = df['datetime'].dt.tz_localize(None)
    if 'datetime' in df.columns:
        df = df.sort_values("datetime")
    # Debug: show nulls and time range
    st.write(f"--- {name} ---")
    st.write(f"Shape: {df.shape}")
    st.write(f"Null datetimes: {df['datetime'].isna().sum() if 'datetime' in df.columns else 'N/A'}")
    st.write(f"Time range: {df['datetime'].min() if 'datetime' in df.columns else 'N/A'} to {df['datetime'].max() if 'datetime' in df.columns else 'N/A'}")
    st.write(f"Columns: {list(df.columns)}")
    st.dataframe(df.head(10), use_container_width=True)
    return df

dfs = []
if combined_sensors is not None:
    sensors_df = prep_for_merge(combined_sensors, "Sensors")
    dfs.append(sensors_df)
if combined_usbl is not None:
    usbl_df = prep_for_merge(combined_usbl, "USBL")
    dfs.append(usbl_df)
if combined_winch is not None:
    winch_df = prep_for_merge(combined_winch, "Winch")
    dfs.append(winch_df)

if not dfs:
    st.error("No sensor, USBL, or winch data available for export.")
    st.stop()

# Outer merge all DataFrames on 'datetime'
merged_df = dfs[0]
for df_next in dfs[1:]:
    merged_df = pd.merge(merged_df, df_next, on="datetime", how="outer", suffixes=('', '_other'))

merged_df = merged_df.sort_values("datetime").reset_index(drop=True)

# Debug: merged result
st.write("--- Merged DataFrame ---")
st.write(f"Shape: {merged_df.shape}")
st.write(f"Null datetimes: {merged_df['datetime'].isna().sum()}")
st.write(f"Time range: {merged_df['datetime'].min()} to {merged_df['datetime'].max()}")
st.write(f"Columns: {list(merged_df.columns)}")
st.dataframe(merged_df.head(20), use_container_width=True)

# Filter to deployment window
deployment_df = merged_df[
    (merged_df["datetime"] >= start_datetime) & (merged_df["datetime"] <= end_datetime)
].copy()

st.write(f"**Final combined dataset (truncated to deployment):**")
st.write(f"- Total records: {len(deployment_df)}")
st.write(f"- Columns: {len(deployment_df.columns)}")
if not deployment_df.empty:
    st.write(f"- Time range: {deployment_df['datetime'].min()} to {deployment_df['datetime'].max()}")
    st.dataframe(deployment_df.head(10), use_container_width=True)
else:
    st.warning("No data in deployment window! Check your start/end times and data time ranges.")

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
    export_df = deployment_df.copy()
    # Make sure datetime column is naive
    if pd.api.types.is_datetime64_any_dtype(export_df['datetime']) and getattr(export_df['datetime'].dt, 'tz', None) is not None:
        export_df['datetime'] = export_df['datetime'].dt.tz_localize(None)
    csv = export_df.to_csv(index=False)
    st.download_button(
        label="💾 Download Combined Data CSV",
        data=csv,
        file_name=output_filename,
        mime="text/csv"
    )
    st.success(f"Ready to download {output_filename}")
    st.write(f"File will contain {len(export_df)} rows and {len(export_df.columns)} columns")

# Custom USBL Aggregated Export

st.subheader("Custom USBL Aggregated Export")

# Only keep rows with a USBL position (e.g., 'latitude_deg' and 'longitude_deg' not null)
usbl_rows = deployment_df[
    deployment_df['latitude_deg'].notnull() & 
    deployment_df['longitude_deg'].notnull() & 
    deployment_df['beacon_name'].notnull()
].copy()

# Let user select columns to aggregate (exclude datetime, lat/lon, beacon_name)
agg_candidates = [
    col for col in deployment_df.columns 
    if col not in ['datetime', 'latitude_deg', 'longitude_deg', 'beacon_name']
]
selected_cols = st.multiselect("Select columns to aggregate", agg_candidates, default=agg_candidates[:3] if len(agg_candidates) >= 3 else agg_candidates)

# Let user choose aggregation method for each selected column
agg_methods = {}
for col in selected_cols:
    method = st.selectbox(
        f"Aggregation for {col}",
        ["mean", "max", "min", "count > threshold", "count < threshold"],
        key=f"agg_{col}"
    )
    if "threshold" in method:
        threshold = st.number_input(f"Threshold for {col}", value=float(deployment_df[col].mean()), key=f"thresh_{col}")
        agg_methods[col] = (method, threshold)
    else:
        agg_methods[col] = (method, None)

# Group by USBL position (timestamp, lat, lon, beacon_name)
group_cols = ['datetime', 'latitude_deg', 'longitude_deg', 'beacon_name']
agg_dict = {}

for col, (method, thresh) in agg_methods.items():
    if method == "mean":
        agg_dict[col] = "mean"
    elif method == "max":
        agg_dict[col] = "max"
    elif method == "min":
        agg_dict[col] = "min"
    elif method == "count > threshold":
        agg_dict[col] = lambda x, t=thresh: np.sum(x > t)
    elif method == "count < threshold":
        agg_dict[col] = lambda x, t=thresh: np.sum(x < t)

# Perform aggregation
if len(usbl_rows) > 0 and len(agg_dict) > 0:
    agg_df = usbl_rows.groupby(group_cols).agg(agg_dict).reset_index()
    
    st.write("**Preview of aggregated export:**")
    st.dataframe(agg_df.head(20), use_container_width=True)
    
    output_filename = f"{selected_core}_usbl_aggregated.csv"
    
    if st.button("Download Aggregated CSV", key="download_agg_1"):
        csv = agg_df.to_csv(index=False)
        st.download_button(
            label="💾 Download Aggregated USBL Data CSV",
            data=csv,
            file_name=output_filename,
            mime="text/csv"
        )
        st.success(f"Ready to download {output_filename}")
        st.write(f"File will contain {len(agg_df)} rows and {len(agg_df.columns)} columns")
else:
    st.info("No USBL data available for aggregation")

# Aggregate by USBL windows
st.subheader("Aggregate by USBL windows")

def aggregate_by_usbl_windows(usbl_df, sensor_df, winch_df, selected_cols, agg_methods):
    # Ensure datetime is a column, not index
    if 'datetime' not in usbl_df.columns:
        usbl_df = usbl_df.reset_index()
    if sensor_df is not None and 'datetime' not in sensor_df.columns:
        sensor_df = sensor_df.reset_index()
    if winch_df is not None and 'datetime' not in winch_df.columns:
        winch_df = winch_df.reset_index()
    
    usbl_df = usbl_df.sort_values("datetime").reset_index(drop=True)
    result_rows = []
    for i, row in usbl_df.iterrows():
        t0 = row["datetime"]
        # Define window: halfway to previous and next USBL fix
        if i == 0:
            t_start = t0
        else:
            t_start = t0 - (t0 - usbl_df.loc[i-1, "datetime"]) / 2
        if i == len(usbl_df) - 1:
            t_end = t0
        else:
            t_end = t0 + (usbl_df.loc[i+1, "datetime"] - t0) / 2

        # Use boolean masks on the 'datetime' column
        sensor_window = sensor_df[(sensor_df['datetime'] >= t_start) & (sensor_df['datetime'] < t_end)] if sensor_df is not None else pd.DataFrame()
        winch_window = winch_df[(winch_df['datetime'] >= t_start) & (winch_df['datetime'] < t_end)] if winch_df is not None else pd.DataFrame()

        agg_row = row.to_dict()
        for col, (method, thresh) in agg_methods.items():
            if not sensor_window.empty and col in sensor_window.columns:
                data = sensor_window[col].dropna()
            elif not winch_window.empty and col in winch_window.columns:
                data = winch_window[col].dropna()
            else:
                agg_row[col] = np.nan
                continue

            if len(data) == 0:
                agg_row[col] = np.nan
            elif method == "mean":
                agg_row[col] = data.mean()
            elif method == "max":
                agg_row[col] = data.max()
            elif method == "min":
                agg_row[col] = data.min()
            elif method == "count > threshold":
                agg_row[col] = np.sum(data > thresh)
            elif method == "count < threshold":
                agg_row[col] = np.sum(data < thresh)
        result_rows.append(agg_row)
    return pd.DataFrame(result_rows)

if combined_usbl is not None and (combined_sensors is not None or combined_winch is not None):
    # Only run if user has selected columns and methods
    if len(selected_cols) > 0 and len(agg_methods) > 0:
        st.write("Aggregating by USBL windows...")
        agg_df = aggregate_by_usbl_windows(combined_usbl, combined_sensors, combined_winch, selected_cols, agg_methods)
        st.write("**Preview of aggregated export:**")
        st.dataframe(agg_df.head(20), use_container_width=True)

        output_filename = f"{selected_core}_usbl_aggregated_windows.csv"

        if st.button("Download Aggregated CSV (Windows)", key="download_agg_2"):
            csv = agg_df.to_csv(index=False)
            st.download_button(
                label="💾 Download Aggregated USBL Data CSV",
                data=csv,
                file_name=output_filename,
                mime="text/csv",
                key="download_agg_windows"
            )
            st.success(f"Ready to download {output_filename}")
            st.write(f"File will contain {len(agg_df)} rows and {len(agg_df.columns)} columns")
    else:
        st.info("Select columns to aggregate in the section above to enable USBL window aggregation")
else:
    st.info("No data available for USBL window aggregation")