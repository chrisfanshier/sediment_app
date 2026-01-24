import streamlit as st
import pandas as pd
from db_util import get_connection
from sqlalchemy import text

st.title("Cruises with USBL Data")

with get_connection() as conn:
    cruises = pd.read_sql(
        text("SELECT DISTINCT c.cruise_id, c.cruise_name "
             "FROM cruises c JOIN usbl_files u ON c.cruise_id = u.cruise_id "
             "ORDER BY c.cruise_name"),
        conn
    )

if cruises.empty:
    st.info("No cruises with USBL files found.")
else:
    cruise_map = {row.cruise_name: row.cruise_id for _, row in cruises.iterrows()}
    selected = st.selectbox("Select cruise", ["-- choose --"] + list(cruise_map.keys()), key="cruise_with_usbl_select")
    if selected and selected != "-- choose --":
        cruise_id = cruise_map[selected]

        # load cores for cruise
        with get_connection() as conn:
            cores = pd.read_sql(
                text("SELECT * FROM cores WHERE cruise_id = :cruise_id ORDER BY core_name"),
                conn,
                params={"cruise_id": cruise_id}
            )

            usbl_df = pd.read_sql(
                text("SELECT usbl_file_id, file_name, start_time, end_time, file_path FROM usbl_files WHERE cruise_id = :cruise_id"),
                conn,
                params={"cruise_id": cruise_id}
            )

        if cores.empty:
            st.info("No cores for selected cruise.")
        else:
            df_dredge = cores.copy()

            # coerce times to timedeltas (treat invalid/missing as 0) and dates safely
            launch_td = pd.to_timedelta(df_dredge["time_launched"].astype(str), errors="coerce").fillna(pd.Timedelta(0))
            recover_td = pd.to_timedelta(df_dredge["time_recovered"].astype(str), errors="coerce").fillna(pd.Timedelta(0))

            df_dredge["start_datetime"] = pd.to_datetime(df_dredge["date"], errors="coerce") + launch_td
            df_dredge["end_datetime"] = pd.to_datetime(df_dredge["date"], errors="coerce") + recover_td

            # drop rows where date parsing failed
            bad = df_dredge[["start_datetime", "end_datetime"]].isna().any(axis=1)
            if bad.any():
                st.warning(f"Dropped {bad.sum()} core rows with invalid date/time")
                df_dredge = df_dredge.loc[~bad].copy()

            # handle midnight rollover
            df_dredge.loc[df_dredge["end_datetime"] < df_dredge["start_datetime"], "end_datetime"] += pd.Timedelta(days=1)

            # prepare USBL times
            if not usbl_df.empty:
                usbl_df["start_time"] = pd.to_datetime(usbl_df["start_time"], errors="coerce")
                usbl_df["end_time"] = pd.to_datetime(usbl_df["end_time"], errors="coerce")
            else:
                usbl_df["start_time"] = pd.Series(dtype="datetime64[ns]")
                usbl_df["end_time"] = pd.Series(dtype="datetime64[ns]")

            # --- build per-USBL-file table that lists associated core (if any) ---
            results = []
            for _, dredge in df_dredge.iterrows():
                mask = (
                    (usbl_df["start_time"] <= dredge["end_datetime"]) &
                    (usbl_df["end_time"] >= dredge["start_datetime"])
                )
                usbl_matches = usbl_df.loc[mask].copy()
                if not usbl_matches.empty:
                    usbl_matches["dredge_core"] = dredge.get("core_name")
                    usbl_matches["dredge_start"] = dredge["start_datetime"]
                    usbl_matches["dredge_end"] = dredge["end_datetime"]
                    results.append(usbl_matches)

            if results:
                matched_all = pd.concat(results, ignore_index=True)
                # include any USBL files that had no match (show core empty)
                unmatched = usbl_df[~usbl_df["usbl_file_id"].isin(matched_all["usbl_file_id"])].copy()
                if not unmatched.empty:
                    unmatched["dredge_core"] = ""
                    unmatched["dredge_start"] = pd.NaT
                    unmatched["dredge_end"] = pd.NaT
                out = pd.concat([matched_all, unmatched], ignore_index=True, sort=False)
            else:
                # no matches at all: show all usbl files with empty core columns
                out = usbl_df.copy()
                out["dredge_core"] = ""
                out["dredge_start"] = pd.NaT
                out["dredge_end"] = pd.NaT

            # pick and display relevant columns
            display_cols = ["file_name", "start_time", "end_time", "dredge_core", "dredge_start", "dredge_end"]
            st.subheader(f"USBL files and associated cores for cruise: {selected}")
            st.dataframe(out[display_cols].sort_values(["dredge_core", "start_time"]).reset_index(drop=True), use_container_width=True)
