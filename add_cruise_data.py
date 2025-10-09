import streamlit as st
import os
import pandas as pd
from db_util import get_connection
from datetime import date
from sqlalchemy import text
import re

# Force wide layout for Streamlit
#st.set_page_config(layout="wide")

# Custom CSS to reduce blank space
st.markdown(
    """
    <style>
    /* Reduce padding in the main content container */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
        padding-left: 0rem !important; /* Remove left padding */
        padding-right: 1rem !important;
    }
    /* Remove margin between the sidebar and main content */
    .css-1lcbmhc {
        margin-left: 0rem !important; /* Remove left margin */
        margin-right: 0rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Add Cruise Data Page ---
st.title("🚢 Add a New Cruise")

# Fetch vessel dropdown values
def fetch_vessel_options():
    with get_connection() as conn:
        vessel_query = "SELECT vessel_id, vessel_name FROM vessels ORDER BY vessel_name"
        vessels = conn.execute(text(vessel_query)).fetchall()
    return vessels

vessels = fetch_vessel_options()

# --- Static Fields ---
st.subheader("Cruise Information")

# Cruise Name Input with validation
cruise_name_input = st.text_input("Cruise Name*", max_chars=100, key="cruise_name_input")

# Auto-capitalize and filter allowed characters (same pattern as core_name)
if cruise_name_input:
    # Remove any characters that aren't letters, numbers, or hyphens
    filtered_input = re.sub(r'[^A-Za-z0-9\-]', '', cruise_name_input)
    # Convert to uppercase
    cruise_name = filtered_input.upper()
    
    # Show warning if input was modified
    if cruise_name != cruise_name_input:
        st.warning(f"Cruise Name automatically formatted: **{cruise_name}**")
        st.caption("Only letters, numbers, and hyphens (-) are allowed. All letters will be capitalized.")
else:
    cruise_name = ""

# Optional: Show real-time preview
if cruise_name and cruise_name != cruise_name_input:
    st.info(f"Formatted Cruise Name: **{cruise_name}**")

# Vessel Selection
vessel_options = {v[1]: v[0] for v in vessels}  # Map vessel names to IDs
vessel_choice = st.selectbox(
    "Select Vessel*",
    ["Select Vessel"] + list(vessel_options.keys())
)

if vessel_choice == "Select Vessel":
    vessel_id = None
else:
    vessel_id = vessel_options[vessel_choice]

# Chief Scientist and Additional PI
st.subheader("Scientific Personnel")
col_sci1, col_sci2 = st.columns(2)

with col_sci1:
    chief_scientist = st.text_input("Chief Scientist", placeholder="Enter chief scientist name")

with col_sci2:
    additional_PI = st.text_input("Additional PI", placeholder="Enter additional principal investigator")

# Date Fields
st.subheader("Cruise Dates")
col1, col2 = st.columns(2)

with col1:
    start_date = st.date_input(
        "Start Date*", 
        value=date.today(),
        min_value=date(1900, 1, 1),
        max_value=date(2050, 12, 31)
    )

with col2:
    end_date = st.date_input(
        "End Date", 
        value=None,
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
    departure_port = st.text_input("Departure Port", placeholder="Enter departure port")

with col4:
    arrival_port = st.text_input("Arrival Port", placeholder="Enter arrival port")

# Additional Information
st.subheader("Additional Information")

cruise_description = st.text_area(
    "Cruise Description", 
    placeholder="Enter a brief description of the cruise objectives and activities"
)

funding_agency = st.text_input(
    "Funding Agency", 
    placeholder="Enter funding agency or sponsor"
)

cruise_report_url = st.text_input(
    "Cruise Report URL", 
    placeholder="Enter URL to cruise report or related documentation"
)

# Add confirmation state
if "show_cruise_confirmation" not in st.session_state:
    st.session_state.show_cruise_confirmation = False

if st.button("Save Cruise"):
    # Validation: Check for missing required fields
    missing_fields = []

    # Check if cruise_name is blank
    if not cruise_name.strip():
        missing_fields.append("Cruise Name")

    # Check if vessel is selected
    if vessel_choice == "Select Vessel":
        missing_fields.append("Vessel")

    # Check if start_date is missing
    if not start_date:
        missing_fields.append("Start Date")

    # Display warning for missing fields
    if missing_fields:
        st.warning(f"The following required fields are missing: {', '.join(missing_fields)}")
    else:
        # Show confirmation with NULL values
        st.session_state.show_cruise_confirmation = True

# Show confirmation dialog if triggered
if st.session_state.show_cruise_confirmation:
    st.warning("⚠️ **Confirm Save Operation**")
    
    st.info(f"**Cruise to be created:** {cruise_name}")
    st.markdown("---")
    
    # Collect all NULL values that will be saved
    null_values = []
    
    # Check fields for NULLs
    if not chief_scientist or not chief_scientist.strip(): 
        null_values.append("Chief Scientist")
    if not additional_PI or not additional_PI.strip(): 
        null_values.append("Additional PI")
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
        if st.button("✅ Confirm Save", type="primary"):
            try:
                # Check for duplicate cruise_name
                with get_connection() as conn:
                    duplicate_check_query = "SELECT COUNT(*) FROM cruises WHERE cruise_name = :cruise_name"
                    result = conn.execute(text(duplicate_check_query), {"cruise_name": cruise_name}).scalar()
                    
                    if result > 0:
                        st.error(f"A cruise with the name '{cruise_name}' already exists. Please use a different name.")
                    else:
                        # Insert new cruise
                        insert_query = """
                            INSERT INTO cruises (
                                cruise_name, vessel_id, chief_scientist, additional_PI, start_date, end_date, 
                                departure_port, arrival_port, cruise_description, funding_agency, cruise_report_url
                            ) VALUES (
                                :cruise_name, :vessel_id, :chief_scientist, :additional_PI, :start_date, :end_date,
                                :departure_port, :arrival_port, :cruise_description, :funding_agency, :cruise_report_url
                            )
                        """
                        
                        values = {
                            "cruise_name": cruise_name,
                            "vessel_id": vessel_id,
                            "chief_scientist": chief_scientist or None,
                            "additional_PI": additional_PI or None,
                            "start_date": start_date,
                            "end_date": end_date,
                            "departure_port": departure_port or None,
                            "arrival_port": arrival_port or None,
                            "cruise_description": cruise_description or None,
                            "funding_agency": funding_agency or None,
                            "cruise_report_url": cruise_report_url or None
                        }
                        
                        conn.execute(text(insert_query), values)
                        conn.commit()
                        
                        st.success(f"Cruise **{cruise_name}** successfully created!")
                        st.session_state.show_cruise_confirmation = False
                        
                        # Optional: Show next steps
                        st.info("💡 **Next Steps:** You can now use this cruise when creating new sediment cores.")
            
            except Exception as e:
                st.error(f"An error occurred: {e}")
                st.session_state.show_cruise_confirmation = False
    
    with col2:
        if st.button("❌ Cancel"):
            st.session_state.show_cruise_confirmation = False
            st.rerun()