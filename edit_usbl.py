import streamlit as st
import pandas as pd
import os
from sqlalchemy import text
from db_util import get_connection, fetch_cruise_options
from config import ROOT_DIRECTORY

st.title("✏️ Edit USBL Files")

def row_val(row, idx, key):
    try:
        return row[key]
    except Exception:
        try:
            return row[idx]
        except Exception:
            return None

cruises = fetch_cruise_options()
if not cruises:
    st.warning("No cruises found. Please add a cruise first.")
else:
    cruise_options = {}
    for r in cruises:
        cid = row_val(r, 0, "cruise_id")
        cname = row_val(r, 1, "cruise_name") or "Unnamed cruise"
        vname = row_val(r, 2, "vessel_name") or ""
        label = f"{cname} - {vname} (ID: {cid})" if vname else f"{cname} (ID: {cid})"
        cruise_options[label] = cid

    selected_cruise_label = st.selectbox("Select Cruise", [""] + list(cruise_options.keys()), key="edit_usbl_select_cruise")
    if not selected_cruise_label:
        st.info("Select a cruise to see associated USBL files.")
    else:
        selected_cruise_id = cruise_options[selected_cruise_label]

        with get_connection() as conn:
            query_str = """
                SELECT usbl_file_id, file_name, file_path, sampling_device, transponder_type, remarks
                FROM usbl_files
                WHERE cruise_id = :cruise_id
                ORDER BY file_name
            """
            usbl_files = pd.read_sql(text(query_str), conn, params={"cruise_id": selected_cruise_id})

        if usbl_files.empty:
            st.info(f"No USBL files found for cruise: {selected_cruise_label}")
        else:
            options = {}
            for _, row in usbl_files.iterrows():
                fname = row.get("file_name") or "unknown"
                device = row.get("sampling_device") or "Unknown device"
                label = f"📡 {fname} ({device})"
                options[label] = int(row["usbl_file_id"])

            selected_label = st.selectbox("Select USBL File to Edit", list(options.keys()), key="edit_usbl_select_file")
            selected_usbl_id = options[selected_label]

            with get_connection() as conn:
                query = text("SELECT * FROM usbl_files WHERE usbl_file_id = :id")
                file_data = conn.execute(query, {"id": selected_usbl_id}).fetchone()

            if file_data:
                # robust access to Row
                def get(fd, key, idx):
                    try:
                        return fd[key]
                    except Exception:
                        try:
                            return fd[idx]
                        except Exception:
                            return None

                file_name = get(file_data, "file_name", 2) or "unknown"
                file_path = get(file_data, "file_path", 3) or ""

                st.subheader("USBL File Metadata")
                st.write(f"**File Name:** {file_name}")
                try:
                    full_path = os.path.join(ROOT_DIRECTORY, file_path, file_name) if file_path else os.path.join(ROOT_DIRECTORY, file_name)
                except Exception:
                    full_path = file_path or ""
                st.write(f"**File Path:** {full_path}")

                sampling_device = get(file_data, "sampling_device", 4) or ""
                transponder_type = get(file_data, "transponder_type", 5) or ""
                remarks = get(file_data, "remarks", 6) or ""

                new_sampling_device = st.text_input("Sampling Device", value=sampling_device, key="edit_usbl_sampling_device")
                new_transponder_type = st.text_input("Transponder Type", value=transponder_type, key="edit_usbl_transponder_type")
                new_remarks = st.text_area("Remarks", value=remarks, key="edit_usbl_remarks")

                if st.button("Update USBL File", key="edit_usbl_update"):
                    with get_connection() as conn:
                        update_q = text("""
                            UPDATE usbl_files
                            SET sampling_device = :sampling_device,
                                transponder_type = :transponder_type,
                                remarks = :remarks
                            WHERE usbl_file_id = :id
                        """)
                        conn.execute(update_q, {
                            "sampling_device": new_sampling_device or None,
                            "transponder_type": new_transponder_type or None,
                            "remarks": new_remarks or None,
                            "id": selected_usbl_id
                        })
                        conn.commit()
                    st.success("USBL file updated successfully.")