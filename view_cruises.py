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
            # Enhanced query to show file availability
            related_cores_query = """
            SELECT 
                c.core_name, 
                c.date, 
                c.station,
                COUNT(DISTINCT sf.file_id) as sensor_files,
                COUNT(DISTINCT mf.file_id) as mscl_files,
                CASE WHEN COUNT(DISTINCT sf.file_id) > 0 THEN '✅' ELSE '❌' END as has_sensor,
                CASE WHEN COUNT(DISTINCT mf.file_id) > 0 THEN '✅' ELSE '❌' END as has_mscl,
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM ct_xml x
                        LEFT JOIN sections s ON x.section_id = s.section_id
                        WHERE x.core_id = c.core_id OR s.core_id = c.core_id
                    ) THEN '✅' ELSE '❌'
                END as has_ct
            FROM cores c
            LEFT JOIN sensor_files sf ON c.core_id = sf.core_id
            LEFT JOIN mscl_files mf ON c.core_id = mf.core_id
            WHERE c.cruise_id = :cruise_id 
            GROUP BY c.core_id, c.core_name, c.date, c.station
            ORDER BY c.core_name
            """
            related_cores = conn.execute(text(related_cores_query), {"cruise_id": selected_cruise_id}).fetchall()
            
            # Get related winch data count
            winch_count_query = "SELECT COUNT(*) FROM winch_data WHERE cruise_id = :cruise_id"
            winch_count = conn.execute(text(winch_count_query), {"cruise_id": selected_cruise_id}).scalar()
        
        if related_cores:
            st.write(f"**Cores from this cruise ({len(related_cores)}):**")
            
            # Create enhanced dataframe
            cores_df = pd.DataFrame(related_cores, columns=[
                'Core Name', 'Date', 'Station', 'Sensor Files', 'MSCL Files', 'Sensor Data', 'MSCL Data', 'CT Data'
            ])
            
            # Display the enhanced table
            st.dataframe(
                cores_df,
                use_container_width=True,
                column_config={
                    "Core Name": st.column_config.TextColumn("Core Name", width="medium"),
                    "Date": st.column_config.DateColumn("Date", width="small"),
                    "Station": st.column_config.TextColumn("Station", width="small"),
                    "Sensor Files": st.column_config.NumberColumn("# Sensor Files", width="small"),
                    "MSCL Files": st.column_config.NumberColumn("# MSCL Files", width="small"),
                    "Sensor Data": st.column_config.TextColumn("Sensor", width="small"),
                    "MSCL Data": st.column_config.TextColumn("MSCL", width="small"),
                    "CT Data": st.column_config.TextColumn("CT", width="small"),
                }
            )
            
            # Summary statistics
            total_sensor_files = sum(row[3] for row in related_cores)
            total_mscl_files = sum(row[4] for row in related_cores)
            cores_with_sensor = sum(1 for row in related_cores if row[3] > 0)
            cores_with_mscl = sum(1 for row in related_cores if row[4] > 0)
            cores_with_ct = sum(1 for row in related_cores if row[7] == '✅')
            
            st.markdown("#### 📈 Data Summary")
            summary_col1, summary_col2, summary_col3, summary_col4, summary_col5 = st.columns(5)
            
            with summary_col1:
                st.metric("Total Sensor Files", total_sensor_files)
            with summary_col2:
                st.metric("Total MSCL Files", total_mscl_files)
            with summary_col3:
                st.metric("Cores with Sensor Data", f"{cores_with_sensor}/{len(related_cores)}")
            with summary_col4:
                st.metric("Cores with MSCL Data", f"{cores_with_mscl}/{len(related_cores)}")
            with summary_col5:
                st.metric("Cores with CT Data", f"{cores_with_ct}/{len(related_cores)}")
                
        else:
            st.info("No cores found for this cruise.")
        
        if winch_count > 0:
            st.write(f"**Winch Data Records:** {winch_count}")
        else:
            st.info("No winch data records found for this cruise.")