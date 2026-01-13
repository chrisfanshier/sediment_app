import streamlit as st
import os
import pandas as pd
from db_util import get_connection, add_sync_tracking
from db_util import fetch_dropdown_values
from db_util import fetch_last_record
from db_util import fetch_cruise_options
from datetime import date, time
from sqlalchemy import text
import re
from utils import custom_time_input

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

# --- Add Dredge Data Page ---
st.title("⚓ Add a New Dredge Sample")

# Fetch dropdown values dynamically
vessels, core_types = fetch_dropdown_values()
cruises = fetch_cruise_options(only_created_on_ship=True)

# Fetch the last record for carry-forward functionality
last_record = fetch_last_record()

# --- Static Fields ---
st.subheader("Meta Data")
core_name_input = st.text_input("Dredge Name*", max_chars=100, key="core_name_input")

# Auto-capitalize and filter allowed characters
if core_name_input:
    # Remove any characters that aren't letters, numbers, or hyphens
    filtered_input = re.sub(r'[^A-Za-z0-9\-]', '', core_name_input)
    # Convert to uppercase
    core_name = filtered_input.upper()
    
    # Show warning if input was modified
    if core_name != core_name_input:
        st.warning(f"Dredge Name automatically formatted: **{core_name}**")
        st.caption("Only letters, numbers, and hyphens (-) are allowed. All letters will be capitalized.")
else:
    core_name = ""

# Optional: Show real-time preview
if core_name and core_name != core_name_input:
    st.info(f"Formatted Dredge Name: **{core_name}**")

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

# Determine default cruise selection
default_cruise_index = 0
if last_record and last_record.get('cruise_id'):
    # Find the matching cruise in the options
    for i, (display_name, cruise_id) in enumerate(cruise_options.items()):
        if cruise_id == last_record['cruise_id']:
            default_cruise_index = i + 1  # +1 because of "Select Cruise" option
            break

# Cruise selection dropdown
cruise_choice = st.selectbox(
    "Select Cruise*",
    ["Select Cruise"] + list(cruise_options.keys()),
    index=default_cruise_index
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

# Continue with leg and other fields
leg = st.text_input("Leg", value=last_record['leg'] if last_record else "")
date_field = st.date_input("Date", 
                          value=date.today(),
                          min_value=date(1900, 1, 1),
                          max_value=date(2050, 12, 31))
station = st.text_input("Station", value=last_record['station'] if last_record else "")

# --- START POSITION COORDINATES ---
st.subheader("Start Position")

# Coordinate format selection for start position
coord_format_start = st.selectbox("Start Coordinate Format", ["Decimal Degrees", "Degrees and Decimal Minutes", "NULL entry"], key="start_coord_format")

if coord_format_start == "Decimal Degrees":
    lat_input = st.text_input("Start Latitude (decimal degrees)", value="", placeholder="Enter latitude or leave blank for NULL", key="start_lat")
    lon_input = st.text_input("Start Longitude (decimal degrees)", value="", placeholder="Enter longitude or leave blank for NULL", key="start_lon")
    
    # Handle latitude
    if lat_input.strip() == "":
        latitude = None
    else:
        try:
            latitude = float(lat_input)
            if latitude < -90 or latitude > 90:
                st.warning("Latitude must be between -90 and 90 degrees.")
                latitude = None
        except ValueError:
            st.warning("Latitude must be a numeric value.")
            latitude = None
    
    # Handle longitude
    if lon_input.strip() == "":
        longitude = None
    else:
        try:
            longitude = float(lon_input)
            if longitude < -180 or longitude > 180:
                st.warning("Longitude must be between -180 and 180 degrees.")
                longitude = None
        except ValueError:
            st.warning("Longitude must be a numeric value.")
            longitude = None

elif coord_format_start == "Degrees and Decimal Minutes":
    st.markdown("Enter **start** coordinates in degrees and decimal minutes format:")
    
    # Latitude
    lat_deg = st.number_input("Start Latitude Degrees (°)", min_value=0, max_value=90, step=1, key="start_lat_deg")
    lat_min = st.number_input("Start Latitude Minutes (')", min_value=0.0, max_value=59.999999, step=0.000001, format="%.6f", key="start_lat_min")
    lat_dir = st.selectbox("Start Latitude Direction", ["N", "S"], key="start_lat_dir")

    # Longitude
    lon_deg = st.number_input("Start Longitude Degrees (°)", min_value=0, max_value=180, step=1, key="start_lon_deg")
    lon_min = st.number_input("Start Longitude Minutes (')", min_value=0.0, max_value=59.999999, step=0.000001, format="%.6f", key="start_lon_min")
    lon_dir = st.selectbox("Start Longitude Direction", ["E", "W"], key="start_lon_dir")

    # Convert to decimal degrees
    latitude = lat_deg + (lat_min / 60.0)
    if lat_dir == "S":
        latitude = -latitude

    longitude = lon_deg + (lon_min / 60.0)
    if lon_dir == "W":
        longitude = -longitude

    st.markdown(f"Converted Start Latitude: **{latitude:.6f}°**")
    st.markdown(f"Converted Start Longitude: **{longitude:.6f}°**")
else:  # NULL entry
    st.warning("Start Latitude and Longitude will be saved as NULL.")
    latitude = None
    longitude = None

# Start Water Depth
water_depth = st.text_input("Start Water Depth (meters)", value="", placeholder="Enter water depth or leave blank for NULL", key="start_depth")
if water_depth.strip() == "":
    water_depth = None
else:
    try:
        water_depth = float(water_depth)
    except ValueError:
        st.warning("Water Depth must be a numeric value.")
        water_depth = None

# --- END POSITION COORDINATES ---
st.subheader("End Position")

# Coordinate format selection for end position
coord_format_end = st.selectbox("End Coordinate Format", ["Decimal Degrees", "Degrees and Decimal Minutes", "NULL entry"], key="end_coord_format")

if coord_format_end == "Decimal Degrees":
    lat_end_input = st.text_input("End Latitude (decimal degrees)", value="", placeholder="Enter latitude or leave blank for NULL", key="end_lat")
    lon_end_input = st.text_input("End Longitude (decimal degrees)", value="", placeholder="Enter longitude or leave blank for NULL", key="end_lon")
    
    # Handle end latitude
    if lat_end_input.strip() == "":
        latitude_end = None
    else:
        try:
            latitude_end = float(lat_end_input)
            if latitude_end < -90 or latitude_end > 90:
                st.warning("End Latitude must be between -90 and 90 degrees.")
                latitude_end = None
        except ValueError:
            st.warning("End Latitude must be a numeric value.")
            latitude_end = None
    
    # Handle end longitude
    if lon_end_input.strip() == "":
        longitude_end = None
    else:
        try:
            longitude_end = float(lon_end_input)
            if longitude_end < -180 or longitude_end > 180:
                st.warning("End Longitude must be between -180 and 180 degrees.")
                longitude_end = None
        except ValueError:
            st.warning("End Longitude must be a numeric value.")
            longitude_end = None

elif coord_format_end == "Degrees and Decimal Minutes":
    st.markdown("Enter **end** coordinates in degrees and decimal minutes format:")
    
    # End Latitude
    lat_end_deg = st.number_input("End Latitude Degrees (°)", min_value=0, max_value=90, step=1, key="end_lat_deg")
    lat_end_min = st.number_input("End Latitude Minutes (')", min_value=0.0, max_value=59.999999, step=0.000001, format="%.6f", key="end_lat_min")
    lat_end_dir = st.selectbox("End Latitude Direction", ["N", "S"], key="end_lat_dir")

    # End Longitude
    lon_end_deg = st.number_input("End Longitude Degrees (°)", min_value=0, max_value=180, step=1, key="end_lon_deg")
    lon_end_min = st.number_input("End Longitude Minutes (')", min_value=0.0, max_value=59.999999, step=0.000001, format="%.6f", key="end_lon_min")
    lon_end_dir = st.selectbox("End Longitude Direction", ["E", "W"], key="end_lon_dir")

    # Convert to decimal degrees
    latitude_end = lat_end_deg + (lat_end_min / 60.0)
    if lat_end_dir == "S":
        latitude_end = -latitude_end

    longitude_end = lon_end_deg + (lon_end_min / 60.0)
    if lon_end_dir == "W":
        longitude_end = -longitude_end

    st.markdown(f"Converted End Latitude: **{latitude_end:.6f}°**")
    st.markdown(f"Converted End Longitude: **{longitude_end:.6f}°**")
else:  # NULL entry
    st.warning("End Latitude and Longitude will be saved as NULL.")
    latitude_end = None
    longitude_end = None

# End Water Depth
depth_end = st.text_input("End Water Depth (meters)", value="", placeholder="Enter water depth or leave blank for NULL", key="end_depth")
if depth_end.strip() == "":
    depth_end = None
else:
    try:
        depth_end = float(depth_end)
    except ValueError:
        st.warning("End Water Depth must be a numeric value.")
        depth_end = None

st.subheader("Observer and Wire")
observer = st.text_input("Observer")

# Wire Type - Dropdown selection
with get_connection() as conn:
    wire_query = "SELECT wire_type_id, wire_type FROM wire ORDER BY wire_type"
    wire_types = conn.execute(text(wire_query)).fetchall()

wire_options = {wt[1]: wt[0] for wt in wire_types}  # Map wire type names to IDs
wire_choice = st.selectbox("Wire Type", ["Select Wire Type"] + list(wire_options.keys()))

if wire_choice == "Select Wire Type":
    wire_type_id = None
else:
    wire_type_id = wire_options[wire_choice]

# --- Deployment Details ---
st.subheader("Deployment Details")

# Time Fields
st.subheader("Deployment Times")

# Time Launched
time_launched = custom_time_input("Time Launched", default="")

# Time on Bottom
time_on_bottom = custom_time_input("Time on Bottom", default="")

# Time off Bottom
time_off_bottom = custom_time_input("Time off Bottom", default="")

# Time Recovered
time_recovered = custom_time_input("Time Recovered", default="")

# Wire Out on Bottom
wire_out_on_bottom = st.text_input("Wire Out on Bottom (meters)", value="", placeholder="Enter value or leave blank for NULL")
if wire_out_on_bottom.strip() == "":
    wire_out_on_bottom = None
else:
    try:
        wire_out_on_bottom = float(wire_out_on_bottom)
    except ValueError:
        st.warning("Wire Out on Bottom must be a numeric value.")
        wire_out_on_bottom = None

# Max Wire Out
max_wire_out = st.text_input("Max Wire Out (meters)", value="", placeholder="Enter value or leave blank for NULL")
if max_wire_out.strip() == "":
    max_wire_out = None
else:
    try:
        max_wire_out = float(max_wire_out)
    except ValueError:
        st.warning("Max Wire Out must be a numeric value.")
        max_wire_out = None

# Tension at Surface
tension_at_surface = st.text_input(
    "Tension at Surface (lbs)", value="", placeholder="Enter value or leave blank for NULL"
)
if tension_at_surface.strip() == "":
    tension_at_surface = None
else:
    try:
        tension_at_surface = float(tension_at_surface)
    except ValueError:
        st.warning("Tension at Surface must be a numeric value.")
        tension_at_surface = None

# Tension Near Bottom
tension_near_bottom = st.text_input(
    "Tension Near Bottom (lbs)", value="", placeholder="Enter value or leave blank for NULL"
)
if tension_near_bottom.strip() == "":
    tension_near_bottom = None
else:
    try:
        tension_near_bottom = float(tension_near_bottom)
    except ValueError:
        st.warning("Tension Near Bottom must be a numeric value.")
        tension_near_bottom = None

# Tension at Bottom
tension_at_bottom = st.text_input(
    "Tension at Bottom (lbs)", value="", placeholder="Enter value or leave blank for NULL"
)
if tension_at_bottom.strip() == "":
    tension_at_bottom = None
else:
    try:
        tension_at_bottom = float(tension_at_bottom)
    except ValueError:
        st.warning("Tension at Bottom must be a numeric value.")
        tension_at_bottom = None

# Max Tension (stored as pullout_tension)
pullout_tension = st.text_input(
    "Max Tension (lbs)", value="", placeholder="Enter value or leave blank for NULL"
)
if pullout_tension.strip() == "":
    pullout_tension = None
else:
    try:
        pullout_tension = float(pullout_tension)
    except ValueError:
        st.warning("Max Tension must be a numeric value.")
        pullout_tension = None

# --- Dredge-Specific Fields ---
st.subheader("Dredge-Specific Information")

# Active/Passive dropdown
active_passive = st.selectbox("Active/Passive", ["Select", "active", "passive"])
if active_passive == "Select":
    active_passive = None

# Fetch shear pin types from database
with get_connection() as conn:
    pin_query = "SELECT shear_pin_type_id, pin_type FROM shear_pin_types ORDER BY pin_type"
    pin_types = conn.execute(text(pin_query)).fetchall()

pin_options = {pt[1]: pt[0] for pt in pin_types}  # Map pin type names to IDs

# Main shear pin
main_shear_pin_choice = st.selectbox("Main Shear Pin Type", ["Select Pin Type"] + list(pin_options.keys()), key="main_pin")
if main_shear_pin_choice == "Select Pin Type":
    main_shear_pin_type_id = None
else:
    main_shear_pin_type_id = pin_options[main_shear_pin_choice]

main_shear_pin_break = st.text_input("Main Shear Pin Break (lbs)", value="", placeholder="Enter value or leave blank for NULL")
if main_shear_pin_break.strip() == "":
    main_shear_pin_break = None
else:
    try:
        main_shear_pin_break = int(main_shear_pin_break)
    except ValueError:
        st.warning("Main Shear Pin Break must be an integer value.")
        main_shear_pin_break = None

# Side pin
side_pin_choice = st.selectbox("Side Pin Type", ["Select Pin Type"] + list(pin_options.keys()), key="side_pin")
if side_pin_choice == "Select Pin Type":
    side_pin_type_id = None
else:
    side_pin_type_id = pin_options[side_pin_choice]

side_pin_strength = st.text_input("Side Pin Strength (lbs)", value="", placeholder="Enter value or leave blank for NULL")
if side_pin_strength.strip() == "":
    side_pin_strength = None
else:
    try:
        side_pin_strength = int(side_pin_strength)
    except ValueError:
        st.warning("Side Pin Strength must be an integer value.")
        side_pin_strength = None

# Groove diameter fields
groove_diameter_main_pin = st.text_input("Groove Diameter Main Pin (inches)", value="", placeholder="Enter value or leave blank for NULL")
if groove_diameter_main_pin.strip() == "":
    groove_diameter_main_pin = None
else:
    try:
        groove_diameter_main_pin = float(groove_diameter_main_pin)
    except ValueError:
        st.warning("Groove Diameter Main Pin must be a numeric value.")
        groove_diameter_main_pin = None

groove_diameter_side_pin = st.text_input("Groove Diameter Side Pin (inches)", value="", placeholder="Enter value or leave blank for NULL")
if groove_diameter_side_pin.strip() == "":
    groove_diameter_side_pin = None
else:
    try:
        groove_diameter_side_pin = float(groove_diameter_side_pin)
    except ValueError:
        st.warning("Groove Diameter Side Pin must be a numeric value.")
        groove_diameter_side_pin = None

# Distance measurements
usbl_distance = st.text_input("USBL Distance (meters)", value="", placeholder="Enter value or leave blank for NULL")
if usbl_distance.strip() == "":
    usbl_distance = None
else:
    try:
        usbl_distance = int(usbl_distance)
    except ValueError:
        st.warning("USBL Distance must be an integer value.")
        usbl_distance = None

pinger_distance = st.text_input("Pinger Distance (meters)", value="", placeholder="Enter value or leave blank for NULL")
if pinger_distance.strip() == "":
    pinger_distance = None
else:
    try:
        pinger_distance = int(pinger_distance)
    except ValueError:
        st.warning("Pinger Distance must be an integer value.")
        pinger_distance = None

notes = st.text_area("Notes", placeholder="Enter any additional notes or observations here...")
data_entry_remarks = st.text_area("Data Entry Remarks", placeholder="Enter any remarks about the data entry process, corrections, or data quality notes here...")

# Add session state for confirmation
if "show_confirmation_dredge" not in st.session_state:
    st.session_state.show_confirmation_dredge = False

if st.button("Save Dredge"):
    # Validation: Check for missing fields
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
        st.session_state.show_confirmation_dredge = True

# Show confirmation dialog
if st.session_state.show_confirmation_dredge:
    st.warning("⚠️ **Confirm Save Operation**")
    
    # Collect all NULL values that will be saved
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
    if main_shear_pin_break is None: null_values.append("Main Shear Pin Break")
    if side_pin_type_id is None: null_values.append("Side Pin Type")
    if side_pin_strength is None: null_values.append("Side Pin Strength")
    if groove_diameter_main_pin is None: null_values.append("Groove Diameter Main Pin")
    if groove_diameter_side_pin is None: null_values.append("Groove Diameter Side Pin")
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
        if st.button("✅ Confirm Save", type="primary"):
            try:
                with get_connection() as conn:
                    # Check for duplicate dredge name
                    duplicate_check_query = "SELECT COUNT(*) FROM cores WHERE core_name = :core_name"
                    result = conn.execute(text(duplicate_check_query), {"core_name": core_name}).scalar()
                    
                    if result > 0:
                        st.error(f"A sample with the name '{core_name}' already exists. Please use a different name.")
                    else:
                        # Insert dredge record with core_dredge='dredge' and core_type_id=NULL
                        query = """
                            INSERT INTO cores (
                                core_name, vessel_id, cruise_id, leg, date, station, water_depth_m, latitude, longitude,
                                latitude_end, longitude_end, depth_end,
                                observer, core_type_id, core_dredge,
                                time_launched, time_on_bottom, time_off_bottom, time_recovered, 
                                wire_out_on_bottom, max_wire_out,
                                tension_at_surface, tension_near_bottom, tension_on_bottom, pullout_tension,
                                active_passive, main_shear_pin_type_id, main_shear_pin_break,
                                side_pin_type_id, side_pin_strength, main_pin_groove_diam, side_pin_groove_diam,
                                usbl_distance, pinger_distance,
                                notes, wire_type_id, data_entry_remarks,
                                created_on_ship, sync_status
                            ) VALUES (
                                :core_name, :vessel_id, :cruise_id, :leg, :date, :station, :water_depth, :latitude, :longitude,
                                :latitude_end, :longitude_end, :depth_end,
                                :observer, NULL, 'dredge',
                                :time_launched, :time_on_bottom, :time_off_bottom, :time_recovered,
                                :wire_out_on_bottom, :max_wire_out,
                                :tension_at_surface, :tension_near_bottom, :tension_at_bottom, :pullout_tension,
                                :active_passive, :main_shear_pin_type_id, :main_shear_pin_break,
                                :side_pin_type_id, :side_pin_strength, :main_pin_groove_diam, :side_pin_groove_diam,
                                :usbl_distance, :pinger_distance,
                                :notes, :wire_type_id, :data_entry_remarks,
                                :created_on_ship, :sync_status
                            )
                        """

                        values = {
                            "core_name": core_name,
                            "vessel_id": vessel_id,
                            "cruise_id": cruise_id,
                            "leg": leg or None,
                            "date": date_field,
                            "station": station or None,
                            "water_depth": water_depth,
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
                            "tension_at_bottom": tension_at_bottom,
                            "pullout_tension": pullout_tension,
                            "active_passive": active_passive,
                            "main_shear_pin_type_id": main_shear_pin_type_id,
                            "main_shear_pin_break": main_shear_pin_break,
                            "side_pin_type_id": side_pin_type_id,
                            "side_pin_strength": side_pin_strength,
                            "main_pin_groove_diam": groove_diameter_main_pin,
                            "side_pin_groove_diam": groove_diameter_side_pin,
                            "usbl_distance": usbl_distance,
                            "pinger_distance": pinger_distance,
                            "notes": notes or None,
                            "wire_type_id": wire_type_id,
                            "data_entry_remarks": data_entry_remarks or None,
                            "created_on_ship": True,
                            "sync_status": "pending"
                        }
                        
                        conn.execute(text(query), values)
                        conn.commit()
                        
                        st.success(f"Dredge **{core_name}** successfully saved!")
                        st.session_state.show_confirmation_dredge = False
            
            except Exception as e:
                st.error(f"An error occurred: {e}")
                st.session_state.show_confirmation_dredge = False
    
    with col2:
        if st.button("❌ Cancel"):
            st.session_state.show_confirmation_dredge = False
            st.rerun()