import streamlit as st
import pandas as pd
from db_util import get_connection  # Use shared DB connection

st.title("CT Data Explorer (Postgres)")

def get_full_table():
    with get_connection() as conn:
        query = """
            SELECT ct_xml.*, sections.section_number AS section_number_from_sections
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
    st.header("Full CT XML Table (with Section Number from Sections)")
    st.dataframe(df)

    st.header("Summary View")
    summary = get_summary_table(df)
    st.dataframe(summary)
except Exception as e:
    st.error(f"Could not connect to Postgres or query data: {e}")