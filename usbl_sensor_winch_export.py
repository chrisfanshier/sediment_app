import streamlit as st
import pandas as pd
from db_util import get_connection
from sqlalchemy import text
from pathlib import Path
import json
import os
from utils import process_star_oddi_data
from config import get_full_path

st.title("Export Dredge Sensor + USBL Data")

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

sensor_dfs = {}
if not sensor_files.empty:
    for _, row in sensor_files.iterrows():
        relative_path = os.path.join(row['file_path'], row['file_name'])
        file_path = get_full_path(relative_path)
        sensor_type = row['sensor_type']
        try:
            df = process_star_oddi_data(file_path)
            if df is not None:
                df.set_index('Timestamp', inplace=True)
                if df.index.tz is None:
                    df.index = df.index.tz_localize('UTC')
                key = f"{sensor_type}_{row['file_id']}"
                sensor_dfs[key] = df
        except Exception:
            pass

if sensor_dfs:
    combined_sensors = list(sensor_dfs.values())[0].copy()
    for key, df in list(sensor_dfs.items())[1:]:
        combined_sensors = combined_sensors.join(df, how='outer', rsuffix=f'_{key}')
    combined_sensors.sort_index(inplace=True)
else:
    combined_sensors = None

# ============================================================================
# 6. LOAD USBL FILES
# ============================================================================
def load_usbl_file(file_path):
    try:
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
        file_name = Path(file_path).name
        date_str = file_name.split("_")[1]
        df["datetime"] = pd.to_datetime(
            date_str + " " + df["utc_time"].astype(str),
            format="%Y%m%d %H%M%S.%f",
            utc=True
        )
        time_values = pd.to_datetime(df["utc_time"], format="%H%M%S.%f", errors="coerce")
        if len(time_values) > 1:
            first_time = time_values.iloc[0]
            last_time = time_values.iloc[-1]
            if not pd.isna(first_time) and not pd.isna(last_time):
                if first_time.time() > last_time.time():
                    rollover_idx = (time_values.diff() < pd.Timedelta(0)).idxmax()
                    if rollover_idx > 0:
                        df.loc[:rollover_idx-1, "datetime"] -= pd.Timedelta(days=1)
        df.set_index("datetime", inplace=True)
        usbl_df = df[["latitude_deg", "longitude_deg", "depth_m", "beacon_name", 
                      "fix_status", "quality", "northing_error_m", "easting_error_m", 
                      "vertical_error_m"]].copy()
        return usbl_df
    except Exception:
        return None

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

usbl_dfs = []
if not usbl_files.empty:
    usbl_files["start_time"] = pd.to_datetime(usbl_files["start_time"], errors="coerce", utc=True)
    usbl_files["end_time"] = pd.to_datetime(usbl_files["end_time"], errors="coerce", utc=True)
    mask = (usbl_files["start_time"] <= end_datetime) & (usbl_files["end_time"] >= start_datetime)
    matched_usbl = usbl_files[mask]
    for _, row in matched_usbl.iterrows():
        relative_path = os.path.join(row['file_path'], row['file_name'])
        file_path = get_full_path(relative_path)
        try:
            df = load_usbl_file(file_path)
            if df is not None:
                usbl_dfs.append(df)
        except Exception:
            pass

if usbl_dfs:
    combined_usbl = pd.concat(usbl_dfs)
    combined_usbl.sort_index(inplace=True)
    combined_usbl = combined_usbl[~combined_usbl.index.duplicated(keep='first')]
else:
    combined_usbl = None

# ============================================================================
# 7. COMBINE SENSOR AND USBL DATA AND EXPORT TO CSV (outer merge, no interpolation)
# ============================================================================
def prep_for_merge(df):
    df = df.copy()
    if not df.index.name == "datetime":
        df = df.rename_axis("datetime")
    df = df.reset_index()
    df = df.sort_values("datetime")
    return df

dfs = []
if combined_sensors is not None:
    sensors_df = prep_for_merge(combined_sensors)
    dfs.append(sensors_df)
if combined_usbl is not None:
    usbl_df = prep_for_merge(combined_usbl)
    dfs.append(usbl_df)

if not dfs:
    st.error("No sensor or USBL data available for export.")
    st.stop()

merged_df = dfs[0]
for df_next in dfs[1:]:
    merged_df = pd.merge(merged_df, df_next, on="datetime", how="outer", suffixes=('', '_other'))

merged_df = merged_df.sort_values("datetime").reset_index(drop=True)

deployment_df = merged_df[
    (merged_df["datetime"] >= start_datetime) & (merged_df["datetime"] <= end_datetime)
].copy()

output_filename = f"{selected_core}_sensors_usbl_raw.csv"

if st.button("Download CSV"):
    export_df = deployment_df.copy()
    csv = export_df.to_csv(index=False)
    st.download_button(
        label="💾 Download Combined Data CSV",
        data=csv,
        file_name=output_filename,
        mime="text/csv"
    )
    st.success(f"Ready to download {output_filename}")
    st.write(f"File will contain {len(export_df)} rows and {len(export_df.columns)} columns")