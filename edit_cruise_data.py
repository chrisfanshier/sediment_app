import streamlit as st
import os
import pandas as pd
from db_util import get_connection, add_sync_tracking
from datetime import date
from sqlalchemy import text
import re

# Force wide layout for Streamlit
# st.set_page_config(layout="wide")

# Custom CSS to reduce blank space
st.markdown(
    """
    <style>
    /* Reduce padding in the main content container */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
        padding-left: 0rem !important;
        padding-right: 1rem !important;
    }
    .css-1lcbmhc {
        margin-left: 0rem !important;
        margin-right: 0rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Edit Cruise Data Page ---
st.title("✏️ Edit Cruise Record")

# Initialize session state
if "selected_cruise" not in st.session_state:
    st.session_state.selected_cruise = None
if "show_cruise_confirmation" not in st.session_state:
    st.session_state.show_cruise_confirmation = False

# --- Cruise Selection ---
st.subheader("Select Cruise to Edit")

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

selected_cruise_display = st.selectbox("Select Cruise to Edit", 
                                     ["Select a cruise..."] + list(cruise_display_options.keys()))

if selected_cruise_display == "Select a cruise...":
    st.info("Please select a cruise to edit.")
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

# Fetch vessel dropdown values
def fetch_vessel_options():
    with get_connection() as conn:
        vessel_query = "SELECT vessel_id, vessel_name FROM vessels ORDER BY vessel_name"
        vessels = conn.execute(text(vessel_query)).fetchall()
    return vessels

vessels = fetch_vessel_options()

# --- Display Edit Form ---
st.subheader("Edit Cruise Data")
st.info(f"Editing: **{cruise_data.cruise_name}**")

# --- Static Fields ---
st.subheader("Cruise Information")

# Cruise Name (editable but warn about consequences)
cruise_name_input = st.text_input("Cruise Name*", value=cruise_data.cruise_name, 
                                 max_chars=100, key="cruise_name_input")

# Auto-capitalize and filter allowed characters
if cruise_name_input:
    filtered_input = re.sub(r'[^A-Za-z0-9\-]', '', cruise_name_input)
    cruise_name = filtered_input.upper()
    
    if cruise_name != cruise_name_input:
        st.warning(f"Cruise Name automatically formatted: **{cruise_name}**")
        st.caption("Only letters, numbers, and hyphens (-) are allowed. All letters will be capitalized.")
else:
    cruise_name = ""

# Warn if cruise name changed
if cruise_name != cruise_data.cruise_name:
    st.warning("⚠️ Changing the cruise name will affect all related core records and winch data.")

# Vessel Selection
vessel_options = {v[1]: v[0] for v in vessels}  # Map vessel names to IDs

# Find current vessel index
if cruise_data.vessel_id:
    try:
        current_vessel_name = next(v[1] for v in vessels if v[0] == cruise_data.vessel_id)
        current_vessel_index = list(vessel_options.keys()).index(current_vessel_name)
    except (StopIteration, ValueError):
        current_vessel_index = 0
        st.warning("Current vessel not found in vessels list")
else:
    current_vessel_index = 0

vessel_choice = st.selectbox(
    "Select Vessel*",
    ["Select Vessel"] + list(vessel_options.keys()),
    index=current_vessel_index + 1 if cruise_data.vessel_id else 0
)

if vessel_choice == "Select Vessel":
    vessel_id = None
else:
    vessel_id = vessel_options[vessel_choice]

# Chief Scientist
chief_scientist = st.text_input("Chief Scientist", 
                               value=cruise_data.chief_scientist or "", 
                               placeholder="Enter chief scientist name")

# Date Fields
st.subheader("Cruise Dates")
col1, col2 = st.columns(2)

with col1:
    start_date = st.date_input(
        "Start Date*", 
        value=cruise_data.start_date if cruise_data.start_date else date.today(),
        min_value=date(1900, 1, 1),
        max_value=date(2050, 12, 31)
    )

with col2:
    end_date = st.date_input(
        "End Date", 
        value=cruise_data.end_date if cruise_data.end_date else None,
        min_value=date(1900, 1, 1),
        max_value=date(2050, 12, 31)
    )

# Validate end_date is after start_date
if end_date and start_date and end_date < start_date:
    st.warning("End Date must be after Start Date.")
    end_date = None

# Port Information
st.subheader("Port Information")
col3, col4 = st.columns(2)

with col3:
    departure_port = st.text_input("Departure Port", 
                                  value=cruise_data.departure_port or "", 
                                  placeholder="Enter departure port")

with col4:
    arrival_port = st.text_input("Arrival Port", 
                                value=cruise_data.arrival_port or "", 
                                placeholder="Enter arrival port")

# Additional Information
st.subheader("Additional Information")

cruise_description = st.text_area(
    "Cruise Description", 
    value=cruise_data.cruise_description or "",
    placeholder="Enter a brief description of the cruise objectives and activities"
)

funding_agency = st.text_input(
    "Funding Agency", 
    value=cruise_data.funding_agency or "",
    placeholder="Enter funding agency or sponsor"
)

cruise_report_url = st.text_input(
    "Cruise Report URL", 
    value=cruise_data.cruise_report_url or "",
    placeholder="Enter URL to cruise report or related documentation"
)

# --- Save Button ---
if st.button("Update Cruise"):
    # Validation: Check for missing required fields
    missing_fields = []

    if not cruise_name.strip():
        missing_fields.append("Cruise Name")
    if vessel_choice == "Select Vessel":
        missing_fields.append("Vessel")
    if not start_date:
        missing_fields.append("Start Date")

    if missing_fields:
        st.warning(f"The following required fields are missing: {', '.join(missing_fields)}")
    else:
        st.session_state.show_cruise_confirmation = True

# Show confirmation dialog
if st.session_state.show_cruise_confirmation:
    st.warning("⚠️ **Confirm Update Operation**")
    st.info(f"Updating cruise: **{cruise_data.cruise_name}** → **{cruise_name}**")
    
    # Collect NULL values
    null_values = []
    if not chief_scientist or not chief_scientist.strip(): 
        null_values.append("Chief Scientist")
    if not end_date: 
        null_values.append("End Date")
    if not departure_port or not departure_port.strip(): 
        null_values.append("Departure Port")
    if not arrival_port or not arrival_port.strip(): 
        null_values.append("Arrival Port")
    if not cruise_description or not cruise_description.strip(): 
        null_values.append("Cruise Description")
    if not funding_agency or not funding_agency.strip(): 
        null_values.append("Funding Agency")
    if not cruise_report_url or not cruise_report_url.strip(): 
        null_values.append("Cruise Report URL")
    
    if null_values:
        st.markdown("**The following fields will be saved as NULL:**")
        for null_field in null_values:
            st.markdown(f"• {null_field}")
        st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("✅ Confirm Update", type="primary"):
            try:
                with get_connection() as conn:
                    # Check for duplicate cruise name (excluding current cruise)
                    if cruise_name != cruise_data.cruise_name:
                        duplicate_check_query = """
                            SELECT COUNT(*) FROM cruises 
                            WHERE cruise_name = :cruise_name AND cruise_id != :cruise_id
                        """
                        result = conn.execute(text(duplicate_check_query), {
                            "cruise_name": cruise_name, 
                            "cruise_id": selected_cruise_id
                        }).scalar()
                        if result > 0:
                            st.error(f"A cruise with the name '{cruise_name}' already exists. Please use a different name.")
                            st.stop()
                    
                    # Update cruise record
                    update_query = """
                        UPDATE cruises SET
                            cruise_name = :cruise_name,
                            vessel_id = :vessel_id,
                            chief_scientist = :chief_scientist,
                            start_date = :start_date,
                            end_date = :end_date,
                            departure_port = :departure_port,
                            arrival_port = :arrival_port,
                            cruise_description = :cruise_description,
                            funding_agency = :funding_agency,
                            cruise_report_url = :cruise_report_url,
                            sync_status = :sync_status
                        WHERE cruise_id = :cruise_id
                    """
                    
                    values = {
                        "cruise_name": cruise_name,
                        "vessel_id": vessel_id,
                        "chief_scientist": chief_scientist or None,
                        "start_date": start_date,
                        "end_date": end_date,
                        "departure_port": departure_port or None,
                        "arrival_port": arrival_port or None,
                        "cruise_description": cruise_description or None,
                        "funding_agency": funding_agency or None,
                        "cruise_report_url": cruise_report_url or None,
                        "cruise_id": selected_cruise_id
                    }
                    
                    # Add sync tracking for update
                    values = add_sync_tracking(values, is_update=True)
                    
                    conn.execute(text(update_query), values)
                    conn.commit()
                    
                    st.success(f"Successfully updated cruise: **{cruise_name}**!")
                    st.session_state.show_cruise_confirmation = False
                    
                    # Reset selection to force reload
                    st.session_state.selected_cruise = None
                    
                    # Show impact on related records
                    with get_connection() as conn:
                        # Count related cores
                        cores_count_query = "SELECT COUNT(*) FROM cores WHERE cruise_id = :cruise_id"
                        cores_count = conn.execute(text(cores_count_query), {"cruise_id": selected_cruise_id}).scalar()
                        
                        # Count related winch data
                        winch_count_query = "SELECT COUNT(*) FROM winch_data WHERE cruise_id = :cruise_id"
                        winch_count = conn.execute(text(winch_count_query), {"cruise_id": selected_cruise_id}).scalar()
                        
                        if cores_count > 0 or winch_count > 0:
                            st.info(f"📊 **Related Records:** {cores_count} cores and {winch_count} winch data records reference this cruise.")
                    
            except Exception as e:
                st.error(f"An error occurred: {e}")
                st.session_state.show_cruise_confirmation = False
    
    with col2:
        if st.button("❌ Cancel"):
            st.session_state.show_cruise_confirmation = False
            st.rerun()

# --- Additional Information Section ---
if cruise_data:
    st.divider()
    st.subheader("📊 Related Records")
    
    # Show related cores and winch data
    with get_connection() as conn:
        # Get related cores
        related_cores_query = """
        SELECT core_name, date, station 
        FROM cores 
        WHERE cruise_id = :cruise_id 
        ORDER BY core_name
        """
        related_cores = conn.execute(text(related_cores_query), {"cruise_id": selected_cruise_id}).fetchall()
        
        # Get related winch data count
        winch_count_query = "SELECT COUNT(*) FROM winch_data WHERE cruise_id = :cruise_id"
        winch_count = conn.execute(text(winch_count_query), {"cruise_id": selected_cruise_id}).scalar()
    
    if related_cores:
        st.write(f"**Cores from this cruise ({len(related_cores)}):**")
        cores_df = pd.DataFrame(related_cores, columns=['Core Name', 'Date', 'Station'])
        st.dataframe(cores_df, use_container_width=True)
    else:
        st.info("No cores found for this cruise.")
    
    if winch_count > 0:
        st.write(f"**Winch Data Records:** {winch_count}")
    else:
        st.info("No winch data records found for this cruise.")