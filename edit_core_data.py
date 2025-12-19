import streamlit as st
import os
import pandas as pd
from db_util import get_connection, add_sync_tracking
from db_util import fetch_dropdown_values
from db_util import fetch_cruise_options  # Add this import
from utils import render_dynamic_fields_from_metadata
from datetime import date, time
from sqlalchemy import text
import re
from utils import custom_time_input

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

# --- Edit Core Data Page ---
st.title("✏️ Edit Sediment Core Record")

# Initialize session state
if "selected_core" not in st.session_state:
    st.session_state.selected_core = None
if "show_confirmation" not in st.session_state:
    st.session_state.show_confirmation = False

# --- Core Selection ---
st.subheader("Select Core to Edit")

# Get all core names for selection with cruise info
with get_connection() as conn:
    cores_query = """
    SELECT c.core_id, c.core_name, cr.cruise_name, v.vessel_name
    FROM cores c
    LEFT JOIN cruises cr ON c.cruise_id = cr.cruise_id
    LEFT JOIN vessels v ON cr.vessel_id = v.vessel_id
    WHERE c.core_dredge = 'core'
    ORDER BY c.core_name
    """
    all_cores = conn.execute(text(cores_query)).fetchall()

if not all_cores:
    st.warning("No cores found in the database.")
    st.stop()

# Create enhanced core options with cruise and vessel info
core_options = {}
for core in all_cores:
    cruise_info = f" - {core[2]}" if core[2] else ""
    vessel_info = f" ({core[3]})" if core[3] else ""
    display_name = f"{core[1]}{cruise_info}{vessel_info}"
    core_options[display_name] = core[0]

selected_core_display = st.selectbox("Select Core to Edit", ["Select a core..."] + list(core_options.keys()))

if selected_core_display == "Select a core...":
    st.info("Please select a core to edit.")
    st.stop()

selected_core_id = core_options[selected_core_display]

# Load the selected core data
with get_connection() as conn:
    # Get core data with related table info including cruise
    core_query = """
        SELECT c.*, v.vessel_name, ct.core_type_name, w.wire_type, cr.cruise_name, cr.cruise_id
        FROM cores c
        LEFT JOIN vessels v ON c.vessel_id = v.vessel_id
        LEFT JOIN core_types ct ON c.core_type_id = ct.core_type_id
        LEFT JOIN wire w ON c.wire_type_id = w.wire_type_id
        LEFT JOIN cruises cr ON c.cruise_id = cr.cruise_id
        WHERE c.core_id = :core_id
    """
    core_data = conn.execute(text(core_query), {"core_id": selected_core_id}).fetchone()
    
    if not core_data:
        st.error("Core not found!")
        st.stop()

# Fetch dropdown values dynamically
vessels, core_types = fetch_dropdown_values()
cruises = fetch_cruise_options()

# --- Cruise Selection with Auto-populated Vessel ---
st.subheader("Cruise and Vessel")

# Create cruise options for dropdown
cruise_options = {}
cruise_vessel_map = {}  # Map cruise_id to vessel info

if cruises:
    for cruise in cruises:
        cruise_id, cruise_name, vessel_name, vessel_id = cruise
        display_name = f"{cruise_name} ({vessel_name})" if vessel_name else cruise_name
        cruise_options[display_name] = cruise_id
        cruise_vessel_map[cruise_id] = {
            'vessel_name': vessel_name,
            'vessel_id': vessel_id
        }

# Determine current cruise selection
current_cruise_index = 0
if core_data.cruise_id:
    # Find the matching cruise in the options
    for i, (display_name, cruise_id) in enumerate(cruise_options.items()):
        if cruise_id == core_data.cruise_id:
            current_cruise_index = i + 1  # +1 because of "Select Cruise" option
            break

# Cruise selection dropdown
cruise_choice = st.selectbox(
    "Select Cruise*",
    ["Select Cruise"] + list(cruise_options.keys()),
    index=current_cruise_index
)

# Auto-populate vessel based on cruise selection
if cruise_choice == "Select Cruise":
    cruise_id = None
    vessel_id = None
    vessel_name = "No cruise selected"
    st.info("Please select a cruise to auto-populate vessel information.")
else:
    cruise_id = cruise_options[cruise_choice]
    vessel_info = cruise_vessel_map[cruise_id]
    vessel_id = vessel_info['vessel_id']
    vessel_name = vessel_info['vessel_name']
    
    # Display auto-populated vessel
    st.success(f"**Vessel:** {vessel_name} (auto-populated from cruise)")

# Show vessel selection as read-only info
st.text_input("Vessel", value=vessel_name, disabled=True, 
              help="Vessel is automatically selected based on the chosen cruise")

# Warn if cruise changed
if cruise_id != core_data.cruise_id:
    st.warning("⚠️ Changing the cruise will also change the vessel association.")

# --- Other Meta Data Fields ---
leg = st.text_input("Leg", value=core_data.leg or "")
station = st.text_input("Station", value=core_data.station or "")

# Date Field
date_field = st.date_input("Date*", value=core_data.date if core_data.date else date.today())

# Geographic Coordinates
st.subheader("Geographic Coordinates")
col1, col2 = st.columns(2)

with col1:
    latitude_input = st.text_input("Latitude", 
                                  value=str(core_data.latitude) if core_data.latitude is not None else "", 
                                  placeholder="Enter latitude or leave blank for NULL")
    if latitude_input.strip() == "":
        latitude = None
    else:
        try:
            latitude = float(latitude_input)
        except ValueError:
            st.warning("Latitude must be a numeric value.")
            latitude = None

with col2:
    longitude_input = st.text_input("Longitude", 
                                   value=str(core_data.longitude) if core_data.longitude is not None else "", 
                                   placeholder="Enter longitude or leave blank for NULL")
    if longitude_input.strip() == "":
        longitude = None
    else:
        try:
            longitude = float(longitude_input)
        except ValueError:
            st.warning("Longitude must be a numeric value.")
            longitude = None

# Water Depth
water_depth_input = st.text_input("Water Depth (m)", 
                                 value=str(core_data.water_depth_m) if core_data.water_depth_m is not None else "", 
                                 placeholder="Enter water depth or leave blank for NULL")
if water_depth_input.strip() == "":
    water_depth = None
else:
    try:
        water_depth = float(water_depth_input)
    except ValueError:
        st.warning("Water Depth must be a numeric value.")
        water_depth = None

# Observer
observer = st.text_input("Observer", value=core_data.observer or "", placeholder="Enter observer name")

# Core Type Selection
core_type_options = {f"{ct[1]}": (ct[0], ct[1]) for ct in core_types}

# Find current core type index
current_core_type_index = 0
if core_data.core_type_id:
    for i, (core_type_name, (core_type_id_val, core_type_name_val)) in enumerate(core_type_options.items()):
        if core_type_id_val == core_data.core_type_id:
            current_core_type_index = i + 1  # +1 because of "Select Core Type" option
            break

core_type_choice = st.selectbox(
    "Core Type*",
    ["Select Core Type"] + list(core_type_options.keys()),
    index=current_core_type_index
)

# Replace lines 189-202:

# Wire Type Selection - Get from database dynamically  
with get_connection() as conn:
    wire_query = "SELECT wire_type_id, wire_type FROM wire ORDER BY wire_type"
    wire_types = conn.execute(text(wire_query)).fetchall()

wire_type_options = {wt[1]: wt[0] for wt in wire_types}  # Map wire type names to IDs

# Find current wire type index
current_wire_type_index = 0
if core_data.wire_type_id:
    wire_type_names = list(wire_type_options.keys())
    for i, wire_type_name in enumerate(wire_type_names):
        if wire_type_options[wire_type_name] == core_data.wire_type_id:
            current_wire_type_index = i + 1  # +1 because of "Select Wire Type" option
            break

wire_type_choice = st.selectbox(
    "Wire Type",
    ["Select Wire Type"] + list(wire_type_options.keys()),
    index=current_wire_type_index
)

if wire_type_choice == "Select Wire Type":
    wire_type_id = None
else:
    wire_type_id = wire_type_options[wire_type_choice]

# --- Display Edit Form ---
st.subheader("Edit Core Data")
st.info(f"Editing: **{core_data.core_name}**")

# --- Static Fields ---
st.subheader("Meta Data")

# Core Name (editable but warn about consequences)
core_name_input = st.text_input("Core Name*", value=core_data.core_name, max_chars=100, key="core_name_input")

# Auto-capitalize and filter allowed characters
if core_name_input:
    filtered_input = re.sub(r'[^A-Za-z0-9\-]', '', core_name_input)
    core_name = filtered_input.upper()
    
    if core_name != core_name_input:
        st.warning(f"Core Name automatically formatted: **{core_name}**")
        st.caption("Only letters, numbers, and hyphens (-) are allowed. All letters will be capitalized.")
else:
    core_name = ""

# Warn if core name changed
if core_name != core_data.core_name:
    st.warning("⚠️ Changing the core name will affect all related records (files, etc.)")

# --- Dynamic Fields ---
if core_type_choice != "Select Core Type":
    core_type_id = core_type_options[core_type_choice][0]
    
    # Get existing dynamic field values from the cores table
    from utils import get_dynamic_fields_metadata
    
    dynamic_field_names = get_dynamic_fields_metadata(core_type_id)
    
    existing_dynamic_values = {}
    if dynamic_field_names:
        with get_connection() as conn:
            # Build query to get current values for the dynamic fields
            fields_str = ", ".join(dynamic_field_names)
            current_values_query = f"SELECT {fields_str} FROM cores WHERE core_id = :core_id"
            current_values = conn.execute(text(current_values_query), {"core_id": selected_core_id}).fetchone()
            
            # Create a dictionary of current values
            if current_values:
                for i, field_name in enumerate(dynamic_field_names):
                    existing_dynamic_values[field_name] = current_values[i]
    
    # Render dynamic fields with existing values
    dynamic_field_values = render_dynamic_fields_from_metadata(core_type_id, existing_values=existing_dynamic_values)
else:
    dynamic_field_values = {}
    core_type_id = None

# --- Deployment Details ---
st.subheader("Deployment Details")

# Time Fields
st.subheader("Deployment Times")

# Convert time objects to strings for the input
time_launched_str = core_data.time_launched.strftime("%H:%M") if core_data.time_launched else ""
time_on_bottom_str = core_data.time_on_bottom.strftime("%H:%M") if core_data.time_on_bottom else ""
time_recovered_str = core_data.time_recovered.strftime("%H:%M") if core_data.time_recovered else ""

time_launched = custom_time_input("Time Launched", default=time_launched_str)
time_on_bottom = custom_time_input("Time on Bottom", default=time_on_bottom_str)
time_recovered = custom_time_input("Time Recovered", default=time_recovered_str)

# Numeric fields with existing values
def create_numeric_field(label, current_value, placeholder):
    value_input = st.text_input(label, 
                               value=str(current_value) if current_value is not None else "", 
                               placeholder=placeholder)
    if value_input.strip() == "":
        return None
    else:
        try:
            return float(value_input)
        except ValueError:
            st.warning(f"{label} must be a numeric value.")
            return None

wire_out_on_bottom = create_numeric_field("Wire Out on Bottom (meters)", core_data.wire_out_on_bottom, "Enter value or leave blank for NULL")
max_wire_out = create_numeric_field("Max Wire Out (meters)", core_data.max_wire_out, "Enter value or leave blank for NULL")
impact_speed = create_numeric_field("Impact Speed (m/min)", core_data.impact_speed, "Enter value or leave blank for NULL")
tension_at_surface = create_numeric_field("Tension at Surface (lbs)", core_data.tension_at_surface, "Enter value or leave blank for NULL")
tension_near_bottom = create_numeric_field("Tension Near Bottom (lbs)", core_data.tension_near_bottom, "Enter value or leave blank for NULL")
tension_at_bottom = create_numeric_field("Tension at Bottom (lbs)", core_data.tension_on_bottom, "Enter value or leave blank for NULL")
pullout_tension = create_numeric_field("Pullout Tension (lbs)", core_data.pullout_tension, "Enter value or leave blank for NULL")

# Notes
notes = st.text_area("Notes", value=core_data.notes or "", placeholder="Enter any additional notes or observations here...")

# Add this after the notes field:
data_entry_remarks = st.text_area("Data Entry Remarks", value=core_data.data_entry_remarks or "", placeholder="Enter any remarks about the data entry process, corrections, or data quality notes here...")

# --- Save Button ---
if st.button("Update Core"):
    # Validation: Check for missing required fields
    missing_fields = []

    if not core_name.strip():
        missing_fields.append("Core Name")
    if cruise_choice == "Select Cruise":
        missing_fields.append("Cruise")
    if core_type_choice == "Select Core Type":
        missing_fields.append("Core Type")
    if not date_field:
        missing_fields.append("Date")

    if missing_fields:
        st.warning(f"The following fields are missing or incomplete: {', '.join(missing_fields)}")
    else:
        st.session_state.show_confirmation = True

# Show confirmation dialog
if st.session_state.show_confirmation:
    st.warning("⚠️ **Confirm Update Operation**")
    
    # Get the original core name for display
    selected_core_name = core_data.core_name
    st.info(f"Updating core: **{selected_core_name}** → **{core_name}**")
    
    # Collect NULL values
    null_values = []
    if cruise_id is None: null_values.append("Cruise")
    if not leg or not leg.strip(): null_values.append("Leg")
    if not station or not station.strip(): null_values.append("Station")
    if latitude is None: null_values.append("Latitude")
    if longitude is None: null_values.append("Longitude")
    if water_depth is None: null_values.append("Water Depth")
    if not observer or not observer.strip(): null_values.append("Observer")
    if wire_type_id is None: null_values.append("Wire Type")
    if time_launched is None: null_values.append("Time Launched")
    if time_on_bottom is None: null_values.append("Time on Bottom")
    if time_recovered is None: null_values.append("Time Recovered")
    if wire_out_on_bottom is None: null_values.append("Wire Out on Bottom")
    if max_wire_out is None: null_values.append("Max Wire Out")
    if impact_speed is None: null_values.append("Impact Speed")
    if tension_at_surface is None: null_values.append("Tension at Surface")
    if tension_near_bottom is None: null_values.append("Tension Near Bottom")
    if tension_at_bottom is None: null_values.append("Tension at Bottom")
    if pullout_tension is None: null_values.append("Pullout Tension")
    if not notes or not notes.strip(): null_values.append("Notes")
    if not data_entry_remarks or not data_entry_remarks.strip(): null_values.append("Data Entry Remarks")
    
    # Check dynamic fields for NULLs
    if 'dynamic_field_values' in locals():
        for field, value in dynamic_field_values.items():
            if value is None or (isinstance(value, str) and not value.strip()):
                null_values.append(field.replace("_", " ").capitalize())
    
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
                    # Check for duplicate core name (excluding current core)
                    if core_name != core_data.core_name:
                        duplicate_check_query = """
                            SELECT COUNT(*) FROM cores 
                            WHERE core_name = :core_name AND core_id != :core_id
                        """
                        result = conn.execute(text(duplicate_check_query), {
                            "core_name": core_name, 
                            "core_id": selected_core_id
                        }).scalar()
                        if result > 0:
                            st.error(f"A core with the name '{core_name}' already exists. Please use a different name.")
                            st.stop()
                    
                    # Build UPDATE query
                    base_update = """
                        UPDATE cores SET
                            core_name = :core_name, vessel_id = :vessel_id, cruise_id = :cruise_id, leg = :leg, 
                            date = :date, station = :station, water_depth_m = :water_depth_m, 
                            latitude = :latitude, longitude = :longitude, observer = :observer, 
                            core_type_id = :core_type_id, time_launched = :time_launched, 
                            time_on_bottom = :time_on_bottom, time_recovered = :time_recovered,
                            wire_out_on_bottom = :wire_out_on_bottom, max_wire_out = :max_wire_out,
                            impact_speed = :impact_speed, tension_at_surface = :tension_at_surface,
                            tension_near_bottom = :tension_near_bottom, tension_on_bottom = :tension_on_bottom,
                            pullout_tension = :pullout_tension, notes = :notes, wire_type_id = :wire_type_id,
                            data_entry_remarks = :data_entry_remarks, sync_status = :sync_status
                    """
                    
                    base_values = {
                        "core_name": core_name,
                        "vessel_id": vessel_id,
                        "cruise_id": cruise_id,
                        "leg": leg or None,
                        "date": date_field,
                        "station": station or None,
                        "water_depth_m": water_depth,
                        "latitude": latitude,
                        "longitude": longitude,
                        "observer": observer or None,
                        "core_type_id": core_type_id,
                        "time_launched": time_launched,
                        "time_on_bottom": time_on_bottom,
                        "time_recovered": time_recovered,
                        "wire_out_on_bottom": wire_out_on_bottom,
                        "max_wire_out": max_wire_out,
                        "impact_speed": impact_speed,
                        "tension_at_surface": tension_at_surface,
                        "tension_near_bottom": tension_near_bottom,
                        "tension_on_bottom": tension_at_bottom,
                        "pullout_tension": pullout_tension,
                        "notes": notes or None,
                        "wire_type_id": wire_type_id,
                        "data_entry_remarks": data_entry_remarks or None,
                        "core_id": selected_core_id
                    }
                    
                    # Add sync tracking for update
                    base_values = add_sync_tracking(base_values, is_update=True)
                    
                    # Handle dynamic fields
                    if 'dynamic_field_values' in locals() and dynamic_field_values:
                        cleaned_dynamic_values = {}
                        for key, value in dynamic_field_values.items():
                            if isinstance(value, str) and value.strip() == "":
                                cleaned_dynamic_values[key] = None
                            else:
                                cleaned_dynamic_values[key] = value
                        
                        # Add dynamic fields to UPDATE query
                        dynamic_updates = []
                        for key in cleaned_dynamic_values.keys():
                            dynamic_updates.append(f"{key} = :{key}")
                        
                        if dynamic_updates:
                            update_query = f"{base_update}, {', '.join(dynamic_updates)} WHERE core_id = :core_id"
                            all_values = {**base_values, **cleaned_dynamic_values}
                        else:
                            update_query = f"{base_update} WHERE core_id = :core_id"
                            all_values = base_values
                    else:
                        update_query = f"{base_update} WHERE core_id = :core_id"
                        all_values = base_values
                    
                    # Execute update
                    conn.execute(text(update_query), all_values)
                    conn.commit()
                    
                    st.success(f"Successfully updated core: **{core_name}**!")
                    st.session_state.show_confirmation = False
                    
                    # Reset selection to force reload
                    st.session_state.selected_core = None
                    
            except Exception as e:
                st.error(f"An error occurred: {e}")
                st.session_state.show_confirmation = False
    
    with col2:
        if st.button("❌ Cancel"):
            st.session_state.show_confirmation = False
            st.rerun()