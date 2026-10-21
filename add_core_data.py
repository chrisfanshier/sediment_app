import streamlit as st
import os
import pandas as pd
from db_util import get_connection, add_sync_tracking
from db_util import fetch_dropdown_values
from db_util import fetch_last_record
from db_util import fetch_cruise_options  # Add this import
from db_util import fetch_liner_configs
from utils import render_dynamic_fields_from_metadata
from utils import generate_liner_label
from datetime import date, time
from sqlalchemy import text
import re
from utils import utc_datetime_input, legacy_date
from elog_widget import elog_fill_widget


def make_tc_core_name(core_name):
    """Name for the companion Trigger Core: swap the core-type letters for TC (X-JPC01 -> X-TC01).
    Names without a hyphen get '-TC' appended so the companion never collides with the main core."""
    tc_name = re.sub(r'(-[0-9]*)([A-Z]+)([0-9]*)$', r'\1TC\3', core_name)
    return tc_name if tc_name != core_name else core_name + '-TC'

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

# --- Add Core Data Page ---
st.title("🧪 Add a New Sediment Core")

# Fetch dropdown values dynamically
vessels, core_types = fetch_dropdown_values()
cruises = fetch_cruise_options(only_created_on_ship=True)

# Fetch the last record for carry-forward functionality
last_record = fetch_last_record()

# --- Static Fields ---
st.subheader("Meta Data")
core_name_input = st.text_input("Core Name*", max_chars=100, key="core_name_input")

# Auto-capitalize and filter allowed characters
if core_name_input:
    # Remove any characters that aren't letters, numbers, or hyphens
    filtered_input = re.sub(r'[^A-Za-z0-9\-]', '', core_name_input)
    # Convert to uppercase
    core_name = filtered_input.upper()
    
    # Show warning if input was modified
    if core_name != core_name_input:
        st.warning(f"Core Name automatically formatted: **{core_name}**")
        st.caption("Only letters, numbers, and hyphens (-) are allowed. All letters will be capitalized.")
else:
    core_name = ""

# Optional: Show real-time preview
if core_name and core_name != core_name_input:
    st.info(f"Formatted Core Name: **{core_name}**")

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

# Remove the old vessel and cruise input sections and continue with leg
leg = st.text_input("Leg", value=last_record['leg'] if last_record else "")
station = st.text_input("Station", value=last_record['station'] if last_record else "")

# Coordinate format selection
coord_format = st.selectbox("Coordinate Format", ["Decimal Degrees", "Degrees and Decimal Minutes", "NULL entry"], key="coord_format")

if coord_format == "Decimal Degrees":
    lat_input = st.text_input("Latitude (decimal degrees)", value="", placeholder="Enter latitude or leave blank for NULL", key="lat_input")
    lon_input = st.text_input("Longitude (decimal degrees)", value="", placeholder="Enter longitude or leave blank for NULL", key="lon_input")
    
    # Handle latitude (same pattern as water_depth)
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
    
    # Handle longitude (same pattern as water_depth)
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

elif coord_format == "Degrees and Decimal Minutes":
    # Keep existing degrees/minutes code as-is
    st.markdown("Enter coordinates in **degrees and decimal minutes** format:")
    
    # Latitude
    lat_deg = st.number_input("Latitude Degrees (°)", min_value=0, max_value=90, step=1)
    lat_min = st.number_input("Latitude Minutes (')", min_value=0.0, max_value=59.999999, step=0.000001, format="%.6f")
    lat_dir = st.selectbox("Latitude Direction", ["N", "S"])

    # Longitude
    lon_deg = st.number_input("Longitude Degrees (°)", min_value=0, max_value=180, step=1)
    lon_min = st.number_input("Longitude Minutes (')", min_value=0.0, max_value=59.999999, step=0.000001, format="%.6f")
    lon_dir = st.selectbox("Longitude Direction", ["E", "W"])

    # Convert to decimal degrees
    latitude = lat_deg + (lat_min / 60.0)
    if lat_dir == "S":
        latitude = -latitude

    longitude = lon_deg + (lon_min / 60.0)
    if lon_dir == "W":
        longitude = -longitude

    st.markdown(f"Converted Latitude: **{latitude:.6f}°**")
    st.markdown(f"Converted Longitude: **{longitude:.6f}°**")
else:  # NULL entry
    st.warning("Latitude and Longitude will be saved as NULL.")
    latitude = None
    longitude = None

# Water Depth
water_depth = st.text_input("Water Depth (meters)", value="", placeholder="Enter water depth or leave blank for NULL")
if water_depth.strip() == "":
    water_depth = None
else:
    try:
        water_depth = float(water_depth)
    except ValueError:
        st.warning("Water Depth must be a numeric value.")
        water_depth = None

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

# Continue with core type selection
core_type_options = {ct[1]: (ct[0], ct[2]) for ct in core_types}  # Map core type names to IDs and required fields
core_type_choice = st.selectbox("Select Core Type", ["Select Core Type"] + list(core_type_options.keys()))

# --- Liner Configuration ---
liner_config_id = None
liner_configs = []
selected_core_type_id = None

# Check if this is a Jumbo Piston Core (core_type_id = 1) and offer TC option
create_trigger_core = False
if core_type_choice != "Select Core Type":
    selected_core_type_id = core_type_options[core_type_choice][0]  # Get the core_type_id
    liner_configs = fetch_liner_configs(selected_core_type_id)

    if len(liner_configs) == 0:
        liner_config_id = None

    elif len(liner_configs) == 1:
        liner_config_id = liner_configs[0].liner_config_id
        st.caption(f"Liner: {generate_liner_label(liner_configs[0])}")

    else:
        liner_options = {generate_liner_label(row): row.liner_config_id for row in liner_configs}
        liner_choice = st.selectbox("Liner Configuration*", ["Select Liner Configuration"] + list(liner_options.keys()))
        liner_config_id = liner_options.get(liner_choice)

    if selected_core_type_id == 1:  # Jumbo Piston (4") - JC
        create_trigger_core = st.checkbox(
            "Also create Trigger Core (TC) record", 
            value=True,  # Default to checked
            help="Creates a companion TC record with the same metadata but separate core length from trigger_core_length field"
        )

# --- Dynamic Fields ---
if core_type_choice != "Select Core Type":
    core_type_id = core_type_options[core_type_choice][0]  # Fetch core type ID
    dynamic_field_values = render_dynamic_fields_from_metadata(core_type_id)  # Render AND collect values
else:
    dynamic_field_values = {}
    core_type_id = None

# --- Post-Core Type Fields ---
st.subheader("Deployment Details")

# Time Fields
st.subheader("Deployment Times")

elog_fill_widget("add_core", core_name, "core", {
    "deploy_utc": "deploy_utc_input", "bottom_utc": "bottom_utc_input",
    "pullout_utc": "pullout_utc_input", "recover_utc": "recover_utc_input",
    "latitude": "lat_input", "longitude": "lon_input", "coord_format": "coord_format",
})

deploy_utc = utc_datetime_input("Deploy", key="deploy_utc_input")
bottom_utc = utc_datetime_input("Bottom", key="bottom_utc_input")
pullout_utc = utc_datetime_input("Pullout", key="pullout_utc_input")
recover_utc = utc_datetime_input("Recover", key="recover_utc_input")

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

# Impact Speed
impact_speed = st.text_input("Impact Speed (m/min)", value="", placeholder="Enter value or leave blank for NULL")
if impact_speed.strip() == "":
    impact_speed = None
else:
    try:
        impact_speed = float(impact_speed)
    except ValueError:
        st.warning("Impact Speed must be a numeric value.")
        impact_speed = None

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

# Pullout Tension
pullout_tension = st.text_input(
    "Pullout Tension (lbs)", value="", placeholder="Enter value or leave blank for NULL"
)
if pullout_tension.strip() == "":
    pullout_tension = None
else:
    try:
        pullout_tension = float(pullout_tension)
    except ValueError:
        st.warning("Pullout Tension must be a numeric value.")
        pullout_tension = None

notes = st.text_area("Notes", placeholder="Enter any additional notes or observations here...")
data_entry_remarks = st.text_area("Data Entry Remarks", placeholder="Enter any remarks about the data entry process, corrections, or data quality notes here...")

# Add this after the existing session state checks
if "show_confirmation" not in st.session_state:
    st.session_state.show_confirmation = False

if st.button("Save Core"):
    # Validation: Check for missing fields
    missing_fields = []

    # Check if core_name is blank
    if not core_name.strip():
        missing_fields.append("Core Name")

    # Check if cruise is selected
    if cruise_choice == "Select Cruise":
        missing_fields.append("Cruise")

    # Check if core_type is selected
    if core_type_choice == "Select Core Type":
        missing_fields.append("Core Type")

    if core_type_id in [6, 7, 12] and liner_config_id is None:
        missing_fields.append("Liner Configuration")

    # Display warning for missing fields
    if missing_fields:
        st.warning(f"The following fields are missing or incomplete: {', '.join(missing_fields)}")
    else:
        # Show confirmation with NULL values
        st.session_state.show_confirmation = True

# Show confirmation dialog if triggered
if st.session_state.show_confirmation:
    st.warning("⚠️ **Confirm Save Operation**")
    
    # Show what will be created
    if create_trigger_core:
        tc_core_name = make_tc_core_name(core_name)
        st.info(f"**Two cores will be created:**")
        st.markdown(f"1. **{core_name}** (Jumbo Piston Core)")
        st.markdown(f"2. **{tc_core_name}** (Trigger Core)")
        st.markdown("---")
    
    # Collect all NULL values that will be saved
    null_values = []
    
    # Check static fields for NULLs
    if cruise_id is None: null_values.append("Cruise")  # Change from cruise text check
    if not leg or not leg.strip(): null_values.append("Leg")
    if not station or not station.strip(): null_values.append("Station")
    if latitude is None: null_values.append("Latitude")
    if longitude is None: null_values.append("Longitude")
    if water_depth is None: null_values.append("Water Depth")
    if not observer or not observer.strip(): null_values.append("Observer")
    if wire_type_id is None: null_values.append("Wire Type")  # ADD THIS LINE
    if deploy_utc is None: null_values.append("Deploy (UTC)")
    if bottom_utc is None: null_values.append("Bottom (UTC)")
    if pullout_utc is None: null_values.append("Pullout (UTC)")
    if recover_utc is None: null_values.append("Recover (UTC)")
    if wire_out_on_bottom is None: null_values.append("Wire Out on Bottom")
    if max_wire_out is None: null_values.append("Max Wire Out")
    if impact_speed is None: null_values.append("Impact Speed")
    if tension_at_surface is None: null_values.append("Tension at Surface")
    if tension_near_bottom is None: null_values.append("Tension Near Bottom")
    if tension_at_bottom is None: null_values.append("Tension at Bottom")
    if pullout_tension is None: null_values.append("Pullout Tension")
    if not notes or not notes.strip(): null_values.append("Notes")
    if not data_entry_remarks or not data_entry_remarks.strip(): null_values.append("Data Entry Remarks")
    if liner_config_id is None and core_type_id is not None and len(liner_configs) == 0:
        null_values.append("Liner Configuration")

    # Check dynamic fields for NULLs
    for field, value in dynamic_field_values.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            null_values.append(field.replace("_", " ").capitalize())
    
    if null_values:
        st.markdown("**The following fields will be saved as NULL:**")
        for null_field in null_values:
            st.markdown(f"• {null_field}")
        
        if create_trigger_core:
            st.markdown("**Additional NULL fields for Trigger Core:**")
            st.markdown("• Tension at Surface")
            st.markdown("• Tension Near Bottom") 
            st.markdown("• Tension at Bottom")
            st.markdown("• Pullout Tension")
            
            # Check if trigger_core_length exists for TC core_length
            trigger_length = dynamic_field_values.get('trigger_core_length') if dynamic_field_values else None
            if not trigger_length or (isinstance(trigger_length, str) and not trigger_length.strip()):
                st.markdown("• Core Length (no trigger_core_length found)")
            else:
                st.markdown(f"✓ Core Length will be: **{trigger_length}** (from trigger_core_length)")
        st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("✅ Confirm Save", type="primary"):
            try:
                # Check for duplicate core_name(s)
                with get_connection() as conn:
                    cores_to_check = [core_name]
                    if create_trigger_core:
                        tc_core_name = make_tc_core_name(core_name)
                        cores_to_check.append(tc_core_name)
                    
                    # Check for duplicates
                    duplicate_found = False
                    for check_name in cores_to_check:
                        duplicate_check_query = "SELECT COUNT(*) FROM cores WHERE core_name = :core_name"
                        result = conn.execute(text(duplicate_check_query), {"core_name": check_name}).scalar()
                        if result > 0:
                            st.error(f"A core with the name '{check_name}' already exists. Please use a different name.")
                            duplicate_found = True
                            break
                    
                    if not duplicate_found:
                        # === CREATE JC CORE (original logic) ===
                        base_query = """
                            INSERT INTO cores (
                                core_name, vessel_id, cruise_id, leg, date, station, water_depth_m, latitude, longitude, observer, core_type_id, liner_config_id, core_dredge,
                                deploy_utc, bottom_utc, pullout_utc, recover_utc, wire_out_on_bottom, max_wire_out, impact_speed,
                                tension_at_surface, tension_near_bottom, tension_on_bottom, pullout_tension, notes, wire_type_id, data_entry_remarks,
                                created_on_ship, sync_status
                        """

                        base_values = [
                            core_name, vessel_id, cruise_id, leg or None, legacy_date(deploy_utc, bottom_utc, pullout_utc, recover_utc), station or None, 
                            water_depth, latitude, longitude, observer or None, core_type_id, liner_config_id, 'core', deploy_utc, bottom_utc, 
                            pullout_utc, recover_utc, wire_out_on_bottom, max_wire_out, impact_speed, tension_at_surface, tension_near_bottom, 
                            tension_at_bottom, pullout_tension, notes or None, wire_type_id, data_entry_remarks or None,
                            True, 'pending'
                        ]

                        # Handle dynamic fields for JC core
                        if dynamic_field_values:
                            cleaned_dynamic_values = {}
                            for key, value in dynamic_field_values.items():
                                if isinstance(value, str) and value.strip() == "":
                                    cleaned_dynamic_values[key] = None
                                else:
                                    cleaned_dynamic_values[key] = value
                            
                            dynamic_columns = ", ".join(cleaned_dynamic_values.keys())
                            dynamic_placeholders = ", ".join([":{}".format(key) for key in cleaned_dynamic_values.keys()])
                            query = f"{base_query}, {dynamic_columns}) VALUES ({', '.join([':{}'.format(i) for i in range(len(base_values))])}, {dynamic_placeholders})"
                            values = {**{str(i): value for i, value in enumerate(base_values)}, **cleaned_dynamic_values}
                        else:
                            query = f"{base_query}) VALUES ({', '.join([':{}'.format(i) for i in range(len(base_values))])})"
                            values = {str(i): value for i, value in enumerate(base_values)}

                        # Execute JC core insertion
                        conn.execute(text(query), values)
                        
                        # === CREATE TC CORE if requested ===
                        if create_trigger_core:
                            tc_core_name = make_tc_core_name(core_name)
                            tc_core_type_id = 3  # Trigger - TC core type ID
                            
                            # TC core values (same as JC but with different name, core_type, and NULL tensions)
                            tc_base_values = [
                                tc_core_name, vessel_id, cruise_id, leg or None, legacy_date(deploy_utc, bottom_utc, pullout_utc, recover_utc), station or None, 
                                water_depth, latitude, longitude, observer or None, tc_core_type_id, liner_config_id, 'core', deploy_utc, bottom_utc, 
                                pullout_utc, recover_utc, wire_out_on_bottom, max_wire_out, impact_speed, None, None,  # tensions = NULL
                                None, None, notes or None, wire_type_id, data_entry_remarks or None,
                                True, 'pending'
                            ]

                            # TC dynamic fields: use trigger_core_length as core_length
                            tc_dynamic_values = {}
                            if dynamic_field_values and 'trigger_core_length' in dynamic_field_values:
                                trigger_length = dynamic_field_values['trigger_core_length']
                                if trigger_length and (not isinstance(trigger_length, str) or trigger_length.strip()):
                                    tc_dynamic_values['core_length'] = trigger_length
                            
                            # Build TC query
                            if tc_dynamic_values:
                                tc_dynamic_columns = ", ".join(tc_dynamic_values.keys())
                                tc_dynamic_placeholders = ", ".join([":{}".format(key) for key in tc_dynamic_values.keys()])
                                tc_query = f"{base_query}, {tc_dynamic_columns}) VALUES ({', '.join([':{}'.format(i) for i in range(len(tc_base_values))])}, {tc_dynamic_placeholders})"
                                tc_values = {**{str(i): value for i, value in enumerate(tc_base_values)}, **tc_dynamic_values}
                            else:
                                tc_query = f"{base_query}) VALUES ({', '.join([':{}'.format(i) for i in range(len(tc_base_values))])})"
                                tc_values = {str(i): value for i, value in enumerate(tc_base_values)}
                            

                            # Execute TC core insertion
                            conn.execute(text(tc_query), tc_values)
                        
                        conn.commit()
                        
                        if create_trigger_core:
                            st.success(f"Successfully created both **{core_name}** and **{tc_core_name}**!")
                        else:
                            st.success("Core successfully saved!")
                            
                        st.session_state.show_confirmation = False
            
            except Exception as e:
                st.error(f"An error occurred: {e}")
                st.session_state.show_confirmation = False
    
    with col2:
        if st.button("❌ Cancel"):
            st.session_state.show_confirmation = False
            st.rerun()