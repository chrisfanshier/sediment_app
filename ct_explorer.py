import streamlit as st
import pandas as pd
from db_util import get_connection  # Use shared DB connection

st.title("CT Data Explorer (Postgres)")

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
            SELECT ct_xml.*, sections.section_number AS section_number_from_sections, sections.core_id as section_core_id
            FROM ct_xml
            LEFT JOIN sections ON ct_xml.section_id = sections.section_id
        """
        df = pd.read_sql_query(query, conn)
    return df

def get_summary_table(df):
    filtered = df[~(df["image_type"].isnull() & df["processing_stage"].isnull())].copy()
    filtered["image_type_disp"] = filtered["image_type"].fillna("NULL")
    filtered["processing_stage_disp"] = filtered["processing_stage"].fillna("NULL")
    filtered["combo"] = filtered.apply(
        lambda row: f"{row['image_type_disp']} | {row['processing_stage_disp']}", axis=1
    )
    summary = (
        filtered.groupby(["core_name", "section_number_from_sections"])
        .agg({"combo": lambda x: sorted(set(x))})
        .reset_index()
    )
    summary["available_image_types"] = summary["combo"].apply(lambda x: ", ".join(x))
    summary = summary.drop(columns=["combo"])
    all_pairs = df[["core_name", "section_number_from_sections"]].drop_duplicates()
    summary = all_pairs.merge(summary, on=["core_name", "section_number_from_sections"], how="left")
    summary["available_image_types"] = summary["available_image_types"].fillna("")
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

    # --- Full CT XML Table ---
    st.header("Full CT XML Table (with Section Number from Sections)")
    search_cruise_full = st.text_input("Search Cruise (Full Table):", value="", key="search_cruise_full")
    search_core_full = st.text_input("Search Core (Full Table):", value="", key="search_core_full")

    filtered_df = df.copy()
    if search_cruise_full:
        filtered_df = filtered_df[filtered_df['core_name'].astype(str).str.contains(search_cruise_full, case=False)]
    if search_core_full:
        filtered_df = filtered_df[filtered_df['core_name'].astype(str).str.contains(search_core_full, case=False)]

    st.dataframe(filtered_df, use_container_width=True)

except Exception as e:
    st.error(f"Could not connect to Postgres or query data: {e}")