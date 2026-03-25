import streamlit as st
import pandas as pd
from db_util import get_connection  # Use shared DB connection
from PIL import Image
import numpy as np
import os
from config import ROOT_DIRECTORY, SUBDIRECTORIES
import glob

def ct_explorer():
    # st.set_page_config(layout="wide")  # <-- Remove or comment out this line

    st.title("CT Data Explorer")

    # --- Add key to sidebar ---
    st.sidebar.markdown("### Key")
    st.sidebar.markdown("""
    - **giXRayImage**: full section x ray image  
    - **giCTOrthogonalView**: full section ct image  
    - **CT Volume**: circular ct scan directory  
    - **Helical**: helical scan directory  
    - **Laminography**: orthogonal x ray directory  
    - **Acquired**: raw data exists  
    - **Recon**: processed directory exists
    """)

    def get_full_table():
        with get_connection() as conn:
            query = """
                SELECT ct_xml.id,
                       ct_xml.section_id,
                       ct_xml.xml_path,
                       ct_xml.image_type,
                       ct_xml.processing_stage,
                       ct_xml.tiff_folder,
                       sections.section_number AS section_number_from_sections, 
                       sections.core_id as section_core_id,
                       cores.core_name,
                       cruises.cruise_name
                FROM ct_xml
                LEFT JOIN sections ON ct_xml.section_id = sections.section_id
                LEFT JOIN cores ON sections.core_id = cores.core_id
                LEFT JOIN cruises ON cores.cruise_id = cruises.cruise_id
            """
            df = pd.read_sql_query(query, conn)
        return df

    def get_summary_table(df):
        # Directory types and their labels
        directory_types = ["CT Volume", "Helical", "Laminography"]
        image_types = ["giXRayImage", "giCTOrthogonalView"]

        summary_rows = []
        all_pairs = df[["core_name", "section_number_from_sections"]].drop_duplicates()

        for _, row in all_pairs.iterrows():
            core = row["core_name"]
            section = row["section_number_from_sections"]
            subdf = df[(df["core_name"] == core) & (df["section_number_from_sections"] == section)]

            # Directories column
            directories = []
            for dtype in directory_types:
                stages = subdf.loc[subdf["image_type"] == dtype, "processing_stage"].dropna().unique()
                if len(stages) > 0:
                    stage_list = ", ".join(sorted(stages))
                    directories.append(f"{dtype} ({stage_list})")
            directories_str = "; ".join(directories)

            # Images column
            images = []
            for itype in image_types:
                if (subdf["image_type"] == itype).any():
                    images.append(itype)
            images_str = ", ".join(images)

            summary_rows.append({
                "core_name": core,
                "section_number_from_sections": section,
                "directories": directories_str,
                "images": images_str
            })

        summary = pd.DataFrame(summary_rows)
        return summary

    try:
        df = get_full_table()
        summary = get_summary_table(df)

        # --- Summary Table ---
        st.header("Summary View")
        search_cruise_summary = st.text_input("Search Cruise (Summary):", value="", key="search_cruise_summary")
        search_core_summary = st.text_input("Search Core (Summary):", value="", key="search_core_summary")

        filtered_summary = summary.copy()
        if search_cruise_summary:
            filtered_summary = filtered_summary[filtered_summary['core_name'].astype(str).str.contains(search_cruise_summary, case=False)]
        if search_core_summary:
            filtered_summary = filtered_summary[filtered_summary['core_name'].astype(str).str.contains(search_core_summary, case=False)]

        st.dataframe(filtered_summary, use_container_width=True)

        # --- Full CT XML Table (with Section Number from Sections) ---
        st.header("Full CT XML Table (with Section Number from Sections)")
        search_cruise_full = st.text_input("Search Cruise (Full Table):", value="", key="search_cruise_full")
        search_core_full = st.text_input("Search Core (Full Table):", value="", key="search_core_full")

        filtered_df = df.copy()
        if search_cruise_full:
            filtered_df = filtered_df[filtered_df['core_name'].astype(str).str.contains(search_cruise_full, case=False)]
        if search_core_full:
            filtered_df = filtered_df[filtered_df['core_name'].astype(str).str.contains(search_core_full, case=False)]

        # Add TIFF link column for giXRayImage and giCTOrthogonalView
        def make_tiff_link(row):
            if row["image_type"] in ["giXRayImage", "giCTOrthogonalView"]:
                tiff_path = row["xml_path"].replace(".xml", ".tif")
                base_dir = ROOT_DIRECTORY
                tiff_full_path = os.path.join(base_dir, tiff_path)
                # Try exact match first
                if os.path.exists(tiff_full_path):
                    return tiff_path
                # Try .TIF (uppercase)
                tiff_path_upper = tiff_path[:-4] + ".TIF"
                tiff_full_path_upper = os.path.join(base_dir, tiff_path_upper)
                if os.path.exists(tiff_full_path_upper):
                    return tiff_path_upper
                # Try any .tif/.TIF with the same base name
                folder = os.path.dirname(tiff_full_path)
                base = os.path.splitext(os.path.basename(tiff_full_path))[0]
                matches = glob.glob(os.path.join(folder, base + ".*"))
                for match in matches:
                    if match.lower().endswith(".tif"):
                        # Return relative path
                        return os.path.relpath(match, base_dir)
                return ""
            return ""

        if "xml_path" in filtered_df.columns and "image_type" in filtered_df.columns:
            filtered_df["TIFF File"] = filtered_df.apply(make_tiff_link, axis=1)

            st.dataframe(filtered_df, use_container_width=True)

            # --- Successive dropdowns: Cruise -> Core -> Section -> TIFF file ---
            tiff_df = filtered_df[filtered_df["TIFF File"].notnull() & (filtered_df["TIFF File"] != "")].copy()

            # Cruise dropdown
            cruise_options = sorted(tiff_df["cruise_name"].dropna().unique())
            selected_cruise = st.selectbox("Select Cruise", cruise_options)
            df_cruise = tiff_df[tiff_df["cruise_name"] == selected_cruise]

            # Core dropdown
            core_options = sorted(df_cruise["core_name"].dropna().unique())
            selected_core = st.selectbox("Select Core", core_options)
            df_core = df_cruise[df_cruise["core_name"] == selected_core]

            # Section dropdown
            section_options = sorted(df_core["section_number_from_sections"].dropna().unique(), key=lambda x: (str(x).isdigit(), x))
            selected_section = st.selectbox("Select Section", section_options)
            df_section = df_core[df_core["section_number_from_sections"] == selected_section]

            # TIFF file dropdown
            tiff_files = df_section["TIFF File"].dropna().unique()
            tiff_files = [f for f in tiff_files if f]
            selected_tiff = st.selectbox("Select TIFF file", tiff_files) if tiff_files else None

            if selected_tiff:
                base_dir = ROOT_DIRECTORY
                tiff_full_path = os.path.join(base_dir, selected_tiff)
                try:
                    img = Image.open(tiff_full_path)
                    if img.mode == "I;16":
                        arr = np.array(img)
                        arr8 = (arr / 256).astype("uint8")  # Scale to 8-bit
                        img = Image.fromarray(arr8)
                    st.image(img, caption=selected_tiff, use_container_width=True)
                except Exception as e:
                    st.warning(f"Could not load TIFF: {e}")

    except Exception as e:
        st.error(f"Could not connect to Postgres or query data: {e}")

# Optional: allow standalone run
if __name__ == "__main__":
    ct_explorer()