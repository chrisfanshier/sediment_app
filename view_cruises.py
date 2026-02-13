import streamlit as st
import os
import pandas as pd
from db_util import get_connection
from datetime import date
from sqlalchemy import text
import re

def view_cruises():
    """Main function to display cruise overview page with cruise selection"""
    
    # --- View Cruise Data Page ---
    st.title("🚢 View Cruise Data")

    # Initialize session state
    if "selected_cruise" not in st.session_state:
        st.session_state.selected_cruise = None

    # --- Cruise Selection ---
    st.subheader("Select Cruise to View")

    # Get all cruise names for selection
    with get_connection() as conn:
        cruises_query = """
        SELECT cr.cruise_id, cr.cruise_name, v.vessel_name 
        FROM cruises cr
        LEFT JOIN vessels v ON cr.vessel_id = v.vessel_id
        ORDER BY cr.cruise_name
        """
        all_cruises = conn.execute(text(cruises_query)).fetchall()

    if not all_cruises:
        st.warning("No cruises found in the database.")
        st.stop()

    # Create cruise options with vessel info for display
    cruise_display_options = {}
    cruise_id_map = {}
    for cruise in all_cruises:
        vessel_info = f" ({cruise[2]})" if cruise[2] else ""
        display_name = f"{cruise[1]}{vessel_info}"
        cruise_display_options[display_name] = cruise[0]
        cruise_id_map[cruise[0]] = cruise[1]  # Map ID to cruise name

    selected_cruise_display = st.selectbox("Select Cruise to View", 
                                         ["Select a cruise..."] + list(cruise_display_options.keys()))

    if selected_cruise_display == "Select a cruise...":
        st.info("Please select a cruise to view.")
        st.stop()

    # Load the selected cruise data
    selected_cruise_id = cruise_display_options[selected_cruise_display]

    with get_connection() as conn:
        # Get cruise data with vessel info
        cruise_query = """
            SELECT cr.*, v.vessel_name
            FROM cruises cr
            LEFT JOIN vessels v ON cr.vessel_id = v.vessel_id
            WHERE cr.cruise_id = :cruise_id
        """
        cruise_data = conn.execute(text(cruise_query), {"cruise_id": selected_cruise_id}).fetchone()
        
        if not cruise_data:
            st.error("Cruise not found!")
            st.stop()

    # --- Display Cruise Data (Clean Display) ---
    st.subheader("Cruise Information")
    st.info(f"**{cruise_data.cruise_name}**")

    # Display cruise info in columns without text boxes
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🚢 Vessel & Personnel")
        if cruise_data.vessel_name:
            st.write(f"**Vessel:** {cruise_data.vessel_name}")
        if cruise_data.chief_scientist:
            st.write(f"**Chief Scientist:** {cruise_data.chief_scientist}")
        
        st.markdown("### 🏴 Ports")
        if cruise_data.departure_port:
            st.write(f"**Departure:** {cruise_data.departure_port}")
        if cruise_data.arrival_port:
            st.write(f"**Arrival:** {cruise_data.arrival_port}")

    with col2:
        st.markdown("### 📅 Dates")
        if cruise_data.start_date:
            st.write(f"**Start Date:** {cruise_data.start_date.strftime('%Y-%m-%d')}")
        if cruise_data.end_date:
            st.write(f"**End Date:** {cruise_data.end_date.strftime('%Y-%m-%d')}")
            if cruise_data.start_date:
                duration = (cruise_data.end_date - cruise_data.start_date).days
                st.write(f"**Duration:** {duration} days")
        
        st.markdown("### 💰 Funding")
        if cruise_data.funding_agency:
            st.write(f"**Agency:** {cruise_data.funding_agency}")

    # Description and URL
    if cruise_data.cruise_description:
        st.markdown("### 📝 Description")
        st.write(cruise_data.cruise_description)

    if cruise_data.cruise_report_url:
        st.markdown("### 📄 Cruise Report")
        st.write(f"[View Report]({cruise_data.cruise_report_url})")

    # --- Enhanced Related Records Section ---
    if cruise_data:
        st.divider()
        st.subheader("📊 Related Records")
        
        # Show related cores with file information
        with get_connection() as conn:
            related_cores_query = """
                SELECT
                    co.core_id,
                    co.core_name,
                    COUNT(DISTINCT sf.file_id) AS sensor_file_count,
                    COUNT(DISTINCT ms.file_id) AS mscl_file_count,
                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM sections s
                            JOIN ct_xml x ON x.section_id = s.section_id
                            WHERE s.core_id = co.core_id
                        ) THEN 1 ELSE 0
                    END AS has_ct_data
                FROM cores co
                LEFT JOIN sections sec ON sec.core_id = co.core_id
                LEFT JOIN sensor_files sf ON sf.core_id = co.core_id
                LEFT JOIN mscl_files ms ON ms.core_id = co.core_id
                WHERE co.cruise_id = :cruise_id
                GROUP BY co.core_id, co.core_name
                ORDER BY co.core_name
            """
            related_cores = conn.execute(
                text(related_cores_query), {"cruise_id": cruise_data.cruise_id}
            ).fetchall()
            
            # Get related winch data count
            winch_count_query = "SELECT COUNT(*) FROM winch_data WHERE cruise_id = :cruise_id"
            winch_count = conn.execute(text(winch_count_query), {"cruise_id": selected_cruise_id}).scalar()
        
        if related_cores:
            import pandas as pd
            df = pd.DataFrame(related_cores, columns=[
                "Core ID", "Core Name", "Sensor Files", "MSCL Files", "Has CT Data"
            ])
            # add CT data check mark column, leave other logic intact
            df["CT data"] = df["Has CT Data"].apply(lambda x: "✓" if x else "")
            df = df.drop(columns=["Has CT Data"])
            st.dataframe(df)

            # --- summary metrics (added CT-count) ---
            try:
                total_cores = len(df)
                cores_with_sensor = (df["Sensor Files"].astype(int) > 0).sum()
                cores_with_mscl = (df["MSCL Files"].astype(int) > 0).sum()
            except Exception:
                # fallback if types are unexpected
                cores_with_sensor = (df["Sensor Files"] > 0).sum()
                cores_with_mscl = (df["MSCL Files"] > 0).sum()

            cores_with_ct = (df["CT data"] == "✓").sum()

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total cores", total_cores)
            col2.metric("Cores with sensor files", int(cores_with_sensor))
            col3.metric("Cores with MSCL files", int(cores_with_mscl))
            col4.metric("Cores with CT data", int(cores_with_ct))
            
        else:
            st.info("No cores found for this cruise.")
        
        if winch_count > 0:
            st.write(f"**Winch Data Records:** {winch_count}")
        else:
            st.info("No winch data records found for this cruise.")