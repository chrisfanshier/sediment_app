import streamlit as st
import os
import pandas as pd
from db_util import get_connection
from db_util import fetch_dropdown_values
from db_util import fetch_cruise_options
from datetime import date, time
from sqlalchemy import text
import re
from utils import custom_time_input

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

# --- Edit Dredge Data Page ---
st.title("✏️ Edit Dredge Record")

# Initialize session state
if "selected_dredge" not in st.session_state:
    st.session_state.selected_dredge = None
if "show_confirmation_edit_dredge" not in st.session_state:
    st.session_state.show_confirmation_edit_dredge = False

# --- Dredge Selection ---
st.subheader("Select Dredge to Edit")

# Get all dredge names for selection with cruise info
with get_connection() as conn:
    dredges_query = """
    SELECT c.core_id, c.core_name, cr.cruise_name, v.vessel_name
    FROM cores c
    LEFT JOIN cruises cr ON c.cruise_id = cr.cruise_id
    LEFT JOIN vessels v ON cr.vessel_id = v.vessel_id
    WHERE c.core_dredge = 'dredge'
    ORDER BY c.core_name
    """
    all_dredges = conn.execute(text(dredges_query)).fetchall()

if not all_dredges:
    st.warning("No dredges found in the database.")
    st.stop()

# Create enhanced dredge options with cruise and vessel info
dredge_options = {}
for dredge in all_dredges:
    cruise_info = f" - {dredge[2]}" if dredge[2] else ""
    vessel_info = f" ({dredge[3]})" if dredge[3] else ""
    display_name = f"{dredge[1]}{cruise_info}{vessel_info}"
    dredge_options[display_name] = dredge[0]

selected_dredge_display = st.selectbox("Select Dredge to Edit", ["Select a dredge..."] + list(dredge_options.keys()))

if selected_dredge_display == "Select a dredge...":
    st.info("Please select a dredge to edit.")
    st.stop()

selected_dredge_id = dredge_options[selected_dredge_display]

# Load the selected dredge data
with get_connection() as conn:
    dredge_query = """
        SELECT c.*, v.vessel_name, w.wire_type, cr.cruise_name, cr.cruise_id,
               main_pin.pin_type as main_pin_type, side_pin.pin_type as side_pin_type
        FROM cores c
        LEFT JOIN vessels v ON c.vessel_id = v.vessel_id
        LEFT JOIN wire w ON c.wire_type_id = w.wire_type_id
        LEFT JOIN cruises cr ON c.cruise_id = cr.cruise_id
        LEFT JOIN shear_pin_types main_pin ON c.main_shear_pin_type_id = main_pin.shear_pin_type_id
        LEFT JOIN shear_pin_types side_pin ON c.side_pin_type_id = side_pin.shear_pin_type_id
        WHERE c.core_id = :core_id AND c.core_dredge = 'dredge'
    """
    dredge_data = conn.execute(text(dredge_query), {"core_id": selected_dredge_id}).fetchone()
    
    if not dredge_data:
        st.error("Dredge not found!")
        st.stop()

# Fetch dropdown values dynamically
vessels, core_types = fetch_dropdown_values()
cruises = fetch_cruise_options()

# --- Display Edit Form ---
st.subheader("Edit Dredge Data")
st.info(f"Editing: **{dredge_data.core_name}**")

# --- Static Fields ---
st.subheader("Meta Data")

# Dredge Name (editable but warn about consequences)
core_name_input = st.text_input("Dredge Name*", value=dredge_data.core_name, max_chars=100, key="core_name_input")

# Auto-capitalize and filter allowed characters
if core_name_input:
    filtered_input = re.sub(r'[^A-Za-z0-9\-]', '', core_name_input)
    core_name = filtered_input.upper()
    
    if core_name != core_name_input:
        st.warning(f"Dredge Name automatically formatted: **{core_name}**")
        st.caption("Only letters, numbers, and hyphens (-) are allowed. All letters will be capitalized.")
else:
    core_name = ""

# Warn if dredge name changed
if core_name != dredge_data.core_name:
    st.warning("⚠️ Changing the dredge name will affect all related records (files, etc.)")

# --- Cruise Selection with Auto-populated Vessel ---
st.subheader("Cruise and Vessel")

# Create cruise options for dropdown
cruise_options = {}
cruise_vessel_map = {}

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
if dredge_data.cruise_id:
    for i, (display_name, cruise_id) in enumerate(cruise_options.items()):
        if cruise_id == dredge_data.cruise_id:
            current_cruise_index = i + 1
            break

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
    st.success(f"**Vessel:** {vessel_name} (auto-populated from cruise)")

st.text_input("Vessel", value=vessel_name, disabled=True, 
              help="Vessel is automatically selected based on the chosen cruise")

# Warn if cruise changed
if cruise_id != dredge_data.cruise_id:
    st.warning("⚠️ Changing the cruise will also change the vessel association.")

# --- Other Meta Data Fields ---
leg = st.text_input("Leg", value=dredge_data.leg or "")
station = st.text_input("Station", value=dredge_data.station or "")
date_field = st.date_input("Date*", value=dredge_data.date if dredge_data.date else date.today())

# Observer
observer = st.text_input("Observer", value=dredge_data.observer or "", placeholder="Enter observer name")

# Wire Type Selection
with get_connection() as conn:
    wire_query = "SELECT wire_type_id, wire_type FROM wire ORDER BY wire_type"
    wire_types = conn.execute(text(wire_query)).fetchall()

wire_type_options = {wt[1]: wt[0] for wt in wire_types}

current_wire_type_index = 0
if dredge_data.wire_type_id:
    wire_type_names = list(wire_type_options.keys())
    for i, wire_type_name in enumerate(wire_type_names):
        if wire_type_options[wire_type_name] == dredge_data.wire_type_id:
            current_wire_type_index = i + 1
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

# --- Dredge-Specific Fields ---
st.subheader("Dredge-Specific Information")

# Active/Passive dropdown
current_active_passive = dredge_data.active_passive if dredge_data.active_passive else "Select"
active_passive_options = ["Select", "active", "passive"]
active_passive_index = active_passive_options.index(current_active_passive) if current_active_passive in active_passive_options else 0

active_passive = st.selectbox("Active/Passive", active_passive_options, index=active_passive_index)
if active_passive == "Select":
    active_passive = None

# Fetch shear pin types from database
with get_connection() as conn:
    pin_query = "SELECT shear_pin_type_id, pin_type FROM shear_pin_types ORDER BY pin_type"
    pin_types = conn.execute(text(pin_query)).fetchall()

pin_options = {pt[1]: pt[0] for pt in pin_types}

# Main shear pin
current_main_pin_index = 0
if dredge_data.main_shear_pin_type_id:
    pin_type_names = list(pin_options.keys())
    for i, pin_type_name in enumerate(pin_type_names):
        if pin_options[pin_type_name] == dredge_data.main_shear_pin_type_id:
            current_main_pin_index = i + 1
            break

main_shear_pin_choice = st.selectbox("Main Shear Pin Type", ["Select Pin Type"] + list(pin_options.keys()), 
                                     index=current_main_pin_index, key="main_pin")
if main_shear_pin_choice == "Select Pin Type":
    main_shear_pin_type_id = None
else:
    main_shear_pin_type_id = pin_options[main_shear_pin_choice]

# Main shear pin groove diameter
main_pin_groove_diam_input = st.text_input("Main Shear Pin Groove Diameter (inches)", 
                                           value=str(dredge_data.main_pin_groove_diam) if dredge_data.main_pin_groove_diam is not None else "",
                                           placeholder="Enter value or leave blank for NULL")
if main_pin_groove_diam_input.strip() == "":
    main_pin_groove_diam = None
else:
    try:
        main_pin_groove_diam = float(main_pin_groove_diam_input)
    except ValueError:
        st.warning("Main Shear Pin Groove Diameter must be a numeric value.")
        main_pin_groove_diam = None

main_shear_pin_break_input = st.text_input("Main Shear Pin Break (lbs)", 
                                           value=str(dredge_data.main_shear_pin_break) if dredge_data.main_shear_pin_break is not None else "",
                                           placeholder="Enter value or leave blank for NULL")
if main_shear_pin_break_input.strip() == "":
    main_shear_pin_break = None
else:
    try:
        main_shear_pin_break = int(main_shear_pin_break_input)
    except ValueError:
        st.warning("Main Shear Pin Break must be an integer value.")
        main_shear_pin_break = None

# Side pin
current_side_pin_index = 0
if dredge_data.side_pin_type_id:
    pin_type_names = list(pin_options.keys())
    for i, pin_type_name in enumerate(pin_type_names):
        if pin_options[pin_type_name] == dredge_data.side_pin_type_id:
            current_side_pin_index = i + 1
            break

side_pin_choice = st.selectbox("Side Pin Type", ["Select Pin Type"] + list(pin_options.keys()), 
                               index=current_side_pin_index, key="side_pin")
if side_pin_choice == "Select Pin Type":
    side_pin_type_id = None
else:
    side_pin_type_id = pin_options[side_pin_choice]

# Side pin groove diameter
side_pin_groove_diam_input = st.text_input("Side Pin Groove Diameter (inches)", 
                                           value=str(dredge_data.side_pin_groove_diam) if dredge_data.side_pin_groove_diam is not None else "",
                                           placeholder="Enter value or leave blank for NULL")
if side_pin_groove_diam_input.strip() == "":
    side_pin_groove_diam = None
else:
    try:
        side_pin_groove_diam = float(side_pin_groove_diam_input)
    except ValueError:
        st.warning("Side Pin Groove Diameter must be a numeric value.")
        side_pin_groove_diam = None

side_pin_strength_input = st.text_input("Side Pin Strength (lbs)", 
                                        value=str(dredge_data.side_pin_strength) if dredge_data.side_pin_strength is not None else "",
                                        placeholder="Enter value or leave blank for NULL")
if side_pin_strength_input.strip() == "":
    side_pin_strength = None
else:
    try:
        side_pin_strength = int(side_pin_strength_input)
    except ValueError:
        st.warning("Side Pin Strength must be an integer value.")
        side_pin_strength = None

# Distance measurements
usbl_distance_input = st.text_input("USBL Distance (meters)", 
                                    value=str(dredge_data.usbl_distance) if dredge_data.usbl_distance is not None else "",
                                    placeholder="Enter value or leave blank for NULL")
if usbl_distance_input.strip() == "":
    usbl_distance = None
else:
    try:
        usbl_distance = int(usbl_distance_input)
    except ValueError:
        st.warning("USBL Distance must be an integer value.")
        usbl_distance = None

pinger_distance_input = st.text_input("Pinger Distance (meters)", 
                                      value=str(dredge_data.pinger_distance) if dredge_data.pinger_distance is not None else "",
                                      placeholder="Enter value or leave blank for NULL")
if pinger_distance_input.strip() == "":
    pinger_distance = None
else:
    try:
        pinger_distance = int(pinger_distance_input)
    except ValueError:
        st.warning("Pinger Distance must be an integer value.")
        pinger_distance = None

# --- START POSITION COORDINATES ---
st.subheader("Start Position")

col1, col2 = st.columns(2)
with col1:
    latitude_input = st.text_input("Start Latitude", 
                                  value=str(dredge_data.latitude) if dredge_data.latitude is not None else "", 
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
    longitude_input = st.text_input("Start Longitude", 
                                   value=str(dredge_data.longitude) if dredge_data.longitude is not None else "", 
                                   placeholder="Enter longitude or leave blank for NULL")
    if longitude_input.strip() == "":
        longitude = None
    else:
        try:
            longitude = float(longitude_input)
        except ValueError:
            st.warning("Longitude must be a numeric value.")
            longitude = None

water_depth_input = st.text_input("Start Water Depth (m)", 
                                 value=str(dredge_data.water_depth_m) if dredge_data.water_depth_m is not None else "", 
                                 placeholder="Enter water depth or leave blank for NULL")
if water_depth_input.strip() == "":
    water_depth = None
else:
    try:
        water_depth = float(water_depth_input)
    except ValueError:
        st.warning("Water Depth must be a numeric value.")
        water_depth = None

# --- END POSITION COORDINATES ---
st.subheader("End Position")

col1, col2 = st.columns(2)
with col1:
    latitude_end_input = st.text_input("End Latitude", 
                                      value=str(dredge_data.latitude_end) if dredge_data.latitude_end is not None else "", 
                                      placeholder="Enter latitude or leave blank for NULL")
    if latitude_end_input.strip() == "":
        latitude_end = None
    else:
        try:
            latitude_end = float(latitude_end_input)
        except ValueError:
            st.warning("End Latitude must be a numeric value.")
            latitude_end = None

with col2:
    longitude_end_input = st.text_input("End Longitude", 
                                       value=str(dredge_data.longitude_end) if dredge_data.longitude_end is not None else "", 
                                       placeholder="Enter longitude or leave blank for NULL")
    if longitude_end_input.strip() == "":
        longitude_end = None
    else:
        try:
            longitude_end = float(longitude_end_input)
        except ValueError:
            st.warning("End Longitude must be a numeric value.")
            longitude_end = None

depth_end_input = st.text_input("End Water Depth (m)", 
                                value=str(dredge_data.depth_end) if dredge_data.depth_end is not None else "", 
                                placeholder="Enter water depth or leave blank for NULL")
if depth_end_input.strip() == "":
    depth_end = None
else:
    try:
        depth_end = float(depth_end_input)
    except ValueError:
        st.warning("End Water Depth must be a numeric value.")
        depth_end = None

# --- Deployment Details ---
st.subheader("Deployment Details")

# Time Fields
time_launched_str = dredge_data.time_launched.strftime("%H:%M") if dredge_data.time_launched else ""
time_on_bottom_str = dredge_data.time_on_bottom.strftime("%H:%M") if dredge_data.time_on_bottom else ""
time_off_bottom_str = dredge_data.time_off_bottom.strftime("%H:%M") if dredge_data.time_off_bottom else ""
time_recovered_str = dredge_data.time_recovered.strftime("%H:%M") if dredge_data.time_recovered else ""

time_launched = custom_time_input("Time Launched", default=time_launched_str)
time_on_bottom = custom_time_input("Time on Bottom", default=time_on_bottom_str)
time_off_bottom = custom_time_input("Time off Bottom", default=time_off_bottom_str)
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

wire_out_on_bottom = create_numeric_field("Wire Out on Bottom (meters)", dredge_data.wire_out_on_bottom, "Enter value or leave blank for NULL")
max_wire_out = create_numeric_field("Max Wire Out (meters)", dredge_data.max_wire_out, "Enter value or leave blank for NULL")
tension_at_surface = create_numeric_field("Tension at Surface (lbs)", dredge_data.tension_at_surface, "Enter value or leave blank for NULL")
tension_near_bottom = create_numeric_field("Tension Near Bottom (lbs)", dredge_data.tension_near_bottom, "Enter value or leave blank for NULL")
tension_at_bottom = create_numeric_field("Tension at Bottom (lbs)", dredge_data.tension_on_bottom, "Enter value or leave blank for NULL")
pullout_tension = create_numeric_field("Max Tension (lbs)", dredge_data.pullout_tension, "Enter value or leave blank for NULL")

# Notes
notes = st.text_area("Notes", value=dredge_data.notes or "", placeholder="Enter any additional notes or observations here...")
data_entry_remarks = st.text_area("Data Entry Remarks", value=dredge_data.data_entry_remarks or "", placeholder="Enter any remarks about the data entry process, corrections, or data quality notes here...")

# --- Save Button ---
if st.button("Update Dredge"):
    missing_fields = []

    if not core_name.strip():
        missing_fields.append("Dredge Name")
    if cruise_choice == "Select Cruise":
        missing_fields.append("Cruise")
    if not date_field:
        missing_fields.append("Date")

    if missing_fields:
        st.warning(f"The following fields are missing or incomplete: {', '.join(missing_fields)}")
    else:
        st.session_state.show_confirmation_edit_dredge = True

# Show confirmation dialog
if st.session_state.show_confirmation_edit_dredge:
    st.warning("⚠️ **Confirm Update Operation**")
    
    selected_dredge_name = dredge_data.core_name
    st.info(f"Updating dredge: **{selected_dredge_name}** → **{core_name}**")
    
    # Collect NULL values
    null_values = []
    if cruise_id is None: null_values.append("Cruise")
    if not leg or not leg.strip(): null_values.append("Leg")
    if not station or not station.strip(): null_values.append("Station")
    if latitude is None: null_values.append("Start Latitude")
    if longitude is None: null_values.append("Start Longitude")
    if water_depth is None: null_values.append("Start Water Depth")
    if latitude_end is None: null_values.append("End Latitude")
    if longitude_end is None: null_values.append("End Longitude")
    if depth_end is None: null_values.append("End Water Depth")
    if not observer or not observer.strip(): null_values.append("Observer")
    if wire_type_id is None: null_values.append("Wire Type")
    if time_launched is None: null_values.append("Time Launched")
    if time_on_bottom is None: null_values.append("Time on Bottom")
    if time_off_bottom is None: null_values.append("Time off Bottom")
    if time_recovered is None: null_values.append("Time Recovered")
    if wire_out_on_bottom is None: null_values.append("Wire Out on Bottom")
    if max_wire_out is None: null_values.append("Max Wire Out")
    if tension_at_surface is None: null_values.append("Tension at Surface")
    if tension_near_bottom is None: null_values.append("Tension Near Bottom")
    if tension_at_bottom is None: null_values.append("Tension at Bottom")
    if pullout_tension is None: null_values.append("Max Tension")
    if active_passive is None: null_values.append("Active/Passive")
    if main_shear_pin_type_id is None: null_values.append("Main Shear Pin Type")
    if main_pin_groove_diam is None: null_values.append("Main Shear Pin Groove Diameter")
    if main_shear_pin_break is None: null_values.append("Main Shear Pin Break")
    if side_pin_type_id is None: null_values.append("Side Pin Type")
    if side_pin_groove_diam is None: null_values.append("Side Pin Groove Diameter")
    if side_pin_strength is None: null_values.append("Side Pin Strength")
    if usbl_distance is None: null_values.append("USBL Distance")
    if pinger_distance is None: null_values.append("Pinger Distance")
    if not notes or not notes.strip(): null_values.append("Notes")
    if not data_entry_remarks or not data_entry_remarks.strip(): null_values.append("Data Entry Remarks")
    
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
                    # Check for duplicate dredge name (excluding current dredge)
                    if core_name != dredge_data.core_name:
                        duplicate_check_query = """
                            SELECT COUNT(*) FROM cores 
                            WHERE core_name = :core_name AND core_id != :core_id
                        """
                        result = conn.execute(text(duplicate_check_query), {
                            "core_name": core_name, 
                            "core_id": selected_dredge_id
                        }).scalar()
                        if result > 0:
                            st.error(f"A sample with the name '{core_name}' already exists. Please use a different name.")
                            st.stop()
                    
                    # Build UPDATE query
                    update_query = """
                        UPDATE cores SET
                            core_name = :core_name, vessel_id = :vessel_id, cruise_id = :cruise_id, leg = :leg, 
                            date = :date, station = :station, water_depth_m = :water_depth_m, 
                            latitude = :latitude, longitude = :longitude,
                            latitude_end = :latitude_end, longitude_end = :longitude_end, depth_end = :depth_end,
                            observer = :observer, time_launched = :time_launched, 
                            time_on_bottom = :time_on_bottom, time_off_bottom = :time_off_bottom, time_recovered = :time_recovered,
                            wire_out_on_bottom = :wire_out_on_bottom, max_wire_out = :max_wire_out,
                            tension_at_surface = :tension_at_surface, tension_near_bottom = :tension_near_bottom,
                            tension_on_bottom = :tension_on_bottom, pullout_tension = :pullout_tension,
                            active_passive = :active_passive, main_shear_pin_type_id = :main_shear_pin_type_id,
                            main_pin_groove_diam = :main_pin_groove_diam, main_shear_pin_break = :main_shear_pin_break, 
                            side_pin_type_id = :side_pin_type_id, side_pin_groove_diam = :side_pin_groove_diam,
                            side_pin_strength = :side_pin_strength, usbl_distance = :usbl_distance,
                            pinger_distance = :pinger_distance, notes = :notes, wire_type_id = :wire_type_id,
                            data_entry_remarks = :data_entry_remarks
                        WHERE core_id = :core_id
                    """
                    
                    values = {
                        "core_name": core_name,
                        "vessel_id": vessel_id,
                        "cruise_id": cruise_id,
                        "leg": leg or None,
                        "date": date_field,
                        "station": station or None,
                        "water_depth_m": water_depth,
                        "latitude": latitude,
                        "longitude": longitude,
                        "latitude_end": latitude_end,
                        "longitude_end": longitude_end,
                        "depth_end": depth_end,
                        "observer": observer or None,
                        "time_launched": time_launched,
                        "time_on_bottom": time_on_bottom,
                        "time_off_bottom": time_off_bottom,
                        "time_recovered": time_recovered,
                        "wire_out_on_bottom": wire_out_on_bottom,
                        "max_wire_out": max_wire_out,
                        "tension_at_surface": tension_at_surface,
                        "tension_near_bottom": tension_near_bottom,
                        "tension_on_bottom": tension_at_bottom,
                        "pullout_tension": pullout_tension,
                        "active_passive": active_passive,
                        "main_shear_pin_type_id": main_shear_pin_type_id,
                        "main_pin_groove_diam": main_pin_groove_diam,
                        "main_shear_pin_break": main_shear_pin_break,
                        "side_pin_type_id": side_pin_type_id,
                        "side_pin_groove_diam": side_pin_groove_diam,
                        "side_pin_strength": side_pin_strength,
                        "usbl_distance": usbl_distance,
                        "pinger_distance": pinger_distance,
                        "notes": notes or None,
                        "wire_type_id": wire_type_id,
                        "data_entry_remarks": data_entry_remarks or None,
                        "core_id": selected_dredge_id
                    }
                    
                    conn.execute(text(update_query), values)
                    conn.commit()
                    
                    st.success(f"Successfully updated dredge: **{core_name}**!")
                    st.session_state.show_confirmation_edit_dredge = False
                    st.session_state.selected_dredge = None
                    
            except Exception as e:
                st.error(f"An error occurred: {e}")
                st.session_state.show_confirmation_edit_dredge = False
    
    with col2:
        if st.button("❌ Cancel"):
            st.session_state.show_confirmation_edit_dredge = False
            st.rerun()