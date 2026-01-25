import streamlit as st
import pandas as pd
from db_util import get_connection
from sqlalchemy import text
import os
from config import get_full_path
from utils import load_usbl_file  # Assumes you have a function to load a USBL file as DataFrame

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
    else:
        st.info("No USBL data found for this core.")
