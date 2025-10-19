import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
import streamlit as st
import pandas as pd
from sqlalchemy import text
from db_util import get_connection
from config import ROOT_DIRECTORY, SUBDIRECTORIES

# --- Settings ---
st.title("CT Crawler (Streamlit Version)")

# Use config for base directory
BASE_DIR = os.path.join(ROOT_DIRECTORY, SUBDIRECTORIES["CT Data"])
cruise_folders = sorted([
    name for name in os.listdir(BASE_DIR)
    if os.path.isdir(os.path.join(BASE_DIR, name))
])
if "CT_ROOT" not in st.session_state:
    st.session_state["CT_ROOT"] = os.path.join(BASE_DIR, cruise_folders[0]) if cruise_folders else ""

selected_cruise = st.selectbox("Select Cruise Folder", cruise_folders)
if st.button("Set Cruise Folder"):
    st.session_state["CT_ROOT"] = os.path.join(BASE_DIR, selected_cruise)
st.write(f"**Current CT Root:** {st.session_state['CT_ROOT']}")

def get_ct_root():
    return st.session_state["CT_ROOT"]

# --- XML Parsing ---
def parse_ct_xml(xml_path):
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        root_tag = root.tag

        def get_text(*tags):
            for tag in tags:
                el = root.find(f".//{tag}")
                if el is not None and el.text:
                    return el.text.strip()
            return None

        section_id = get_text("Section-ID", "section-id", "sectionID")
        if not section_id:
            section_id = get_text("Section-Number", "section-number")

        data = {
            "core_name": get_text("Core-ID", "coreID"),
            "scan_id": get_text("Scan-ID", "scanID"),
            "section_id": section_id,
            "image_type": get_text("Image-Type", "image-type"),
            "processing_stage": get_text("Processing-Stage", "processing-stage"),
            "section_number": section_id,
            "xml_root_tag": root_tag
        }
        # Force core_name to uppercase if present
        if data["core_name"]:
            data["core_name"] = data["core_name"].upper()
        return data

    except Exception as e:
        st.warning(f"Error parsing XML {xml_path}: {e}")
        return None

# --- Folder scanning ---
def scan_ct_folders():
    found = []
    ct_root = get_ct_root()
    ct_data_parent = os.path.dirname(ct_root.rstrip(os.sep))
    for root, dirs, files in os.walk(ct_root):
        xmls = [f for f in files if f.lower().endswith(".xml")]
        for xml_file in xmls:
            xml_path = os.path.join(root, xml_file)
            meta = parse_ct_xml(xml_path)
            if meta and meta["core_name"]:
                rel_xml_path = os.path.relpath(xml_path, ct_data_parent)
                rel_tiff_folder = os.path.relpath(root, ct_data_parent)
                record = {
                    **meta,
                    "xml_path": rel_xml_path,
                    "tiff_folder": rel_tiff_folder,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                found.append(record)
    return found

def save_ct_folders_to_staging(records):
    with get_connection() as conn:
        existing_xmls = set(
            row[0] for row in conn.execute(text("SELECT xml_path FROM ct_xml_staging"))
        )
        new_records = []
        for r in records:
            reason = None
            if r["xml_path"] in existing_xmls:
                reason = "Already in staging"
            elif not r["core_name"]:
                reason = "Missing core_name"
            if reason:
                st.info(f"SKIPPED: {r['xml_path']} | Reason: {reason}")
                continue

            core_name = r["core_name"].strip() if r["core_name"] else None
            core_row = conn.execute(
                text("SELECT core_id FROM cores WHERE TRIM(core_name) = :core_name"),
                {"core_name": core_name}
            ).fetchone()
            core_id = core_row[0] if core_row else None

            section_id = None
            section_number = r["section_number"]
            try:
                section_number_int = int(section_number)
            except (TypeError, ValueError):
                section_number_int = None

            if core_id and section_number_int is not None:
                section_row = conn.execute(
                    text("SELECT section_id FROM sections WHERE core_id = :core_id AND section_number = :section_number"),
                    {"core_id": core_id, "section_number": section_number_int}
                ).fetchone()
                section_id = section_row[0] if section_row else None

            conn.execute(
                text("""
                    INSERT INTO ct_xml_staging (
                        core_id, core_name, section_id, scan_id, image_type,
                        processing_stage, section_number,
                        xml_path, tiff_folder, xml_root_tag, timestamp
                    ) VALUES (
                        :core_id, :core_name, :section_id, :scan_id, :image_type,
                        :processing_stage, :section_number,
                        :xml_path, :tiff_folder, :xml_root_tag, :timestamp
                    )
                """),
                dict(
                    core_id=core_id, core_name=r["core_name"], section_id=section_id,
                    scan_id=r["scan_id"], image_type=r["image_type"],
                    processing_stage=r["processing_stage"], section_number=section_number,
                    xml_path=r["xml_path"], tiff_folder=r["tiff_folder"],
                    xml_root_tag=r["xml_root_tag"], timestamp=r["timestamp"]
                )
            )
            new_records.append(r)
        return new_records

def approve_and_import_staging():
    with get_connection() as conn:
        conn.execute(text("""
            INSERT INTO ct_xml (
                core_id, core_name, section_id, scan_id, image_type,
                processing_stage, section_number, xml_path, tiff_folder, xml_root_tag, timestamp
            )
            SELECT
                core_id, core_name, section_id, scan_id, image_type,
                processing_stage, section_number, xml_path, tiff_folder, xml_root_tag, timestamp
            FROM ct_xml_staging
        """))
        conn.execute(text("DELETE FROM ct_xml_staging"))

# --- Streamlit Tabs ---
tab1, tab2, tab3 = st.tabs(["Crawl CT Folders", "View Staging Records", "Assign Unmapped Sections"])

with tab1:
    st.header("Crawl CT Folders")
    if st.button("Scan and Import CT XML Files"):
        records = scan_ct_folders()
        new_records = save_ct_folders_to_staging(records)
        st.success(f"Found {len(records)} XML files. Imported {len(new_records)} new records. Skipped {len(records) - len(new_records)} already in staging.")
        if new_records:
            st.write(pd.DataFrame(new_records))
    else:
        st.info("Click the button to scan and import CT XML files.")

with tab2:
    st.header("CT Scan Records (Staging)")
    with get_connection() as conn:
        result = conn.execute(text("SELECT * FROM ct_xml_staging ORDER BY timestamp DESC"))
        rows = [dict(row._mapping) for row in result.fetchall()]
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df)
    else:
        st.info("No CT records found in staging.")

with tab3:
    st.header("Assign CT XML Section Associations")
    show_only_unmapped = st.checkbox("Show only unmapped sections", value=True)
    with get_connection() as conn:
        query = """
            SELECT core_id, core_name, section_number, section_id, COUNT(*) as n_xmls
            FROM ct_xml_staging
            GROUP BY core_id, core_name, section_number, section_id
        """
        result = conn.execute(text(query))
        all_sections = [dict(row._mapping) for row in result.fetchall()]

        if show_only_unmapped:
            filtered_sections = [row for row in all_sections if row["section_id"] is None]
        else:
            filtered_sections = all_sections

        core_sections = {}
        for row in filtered_sections:
            sec_result = conn.execute(
                text("SELECT section_id, section_number FROM sections WHERE core_id = :core_id"),
                {"core_id": row["core_id"]}
            )
            core_sections[(row["core_id"], row["section_number"])] = [dict(sec._mapping) for sec in sec_result.fetchall()]

    if filtered_sections:
        with st.form("map_sections_form"):
            updates = []
            for row in filtered_sections:
                col1, col2, col3, col4, col5 = st.columns([2,2,2,1,3])
                col1.write(row["core_name"])
                col2.write(row["section_number"])
                col3.write(str(row["section_id"]) if row["section_id"] else "Unmapped")
                col4.write(row["n_xmls"])
                options = [("", "-- Select Section --")] + [
                    (sec["section_id"], sec["section_number"]) for sec in core_sections[(row["core_id"], row["section_number"])]
                ]
                default_option = ""
                if row["section_id"]:
                    for opt in options:
                        if opt[0] == row["section_id"]:
                            default_option = opt
                            break
                selected = col5.selectbox(
                    "Assign Section",
                    options,
                    index=options.index(default_option) if default_option else 0,
                    format_func=lambda x: str(x[1]) if x else "",
                    key=f"section_id_{row['core_id']}_{row['section_number']}"
                )
                if selected and selected[0]:
                    updates.append((selected[0], row["core_id"], row["section_number"]))
            submitted = st.form_submit_button("Update Section Mappings")
            if submitted and updates:
                with get_connection() as conn2:
                    for section_id, core_id, section_number in updates:
                        conn2.execute(
                            text("""
                                UPDATE ct_xml_staging
                                SET section_id = :section_id
                                WHERE core_id = :core_id AND section_number = :section_number
                            """),
                            {"section_id": section_id, "core_id": core_id, "section_number": section_number}
                        )
                st.success("Section mappings updated.")
    else:
        st.info("No unmapped sections found.")

st.markdown("---")
if st.button("Approve & Import to Main Table"):
    approve_and_import_staging()
    st.success("All staged records imported to main table and staging cleared.")