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

            # compute associated usbl files per core row
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

            out = pd.DataFrame(results)
            st.subheader(f"Cores and associated USBL files for cruise: {selected}")
            st.dataframe(out, use_container_width=True)
