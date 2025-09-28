import streamlit as st
import os
import pandas as pd
from db_util import get_connection
from db_util import fetch_dropdown_values
from db_util import fetch_last_record
from utils import render_dynamic_fields_from_metadata
from datetime import date, time
from sqlalchemy import text
import re
from utils import custom_time_input

# Force wide layout for Streamlit
st.set_page_config(layout="wide")

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

# Fetch the last record for carry-forward functionality
last_record = fetch_last_record()

# --- Static Fields ---
st.subheader("Meta Data")
core_name = st.text_input("Core Name*", max_chars=100)
vessel_options = {v[1]: v[0] for v in vessels}  # Map vessel names to IDs
vessel_choice = st.selectbox(
    "Select Vessel",
    list(vessel_options.keys()),
    index=list(vessel_options.values()).index(last_record['vessel_id']) if last_record else 0
)
cruise = st.text_input("Cruise", value=last_record['cruise'] if last_record else "")
leg = st.text_input("Leg", value=last_record['leg'] if last_record else "")
date_field = st.date_input("Date", value=date.today())
station = st.text_input("Station", value=last_record['station'] if last_record else "")

# Coordinate format selection
st.subheader("Coordinates")
coord_format = st.selectbox("Coordinate Format", ["Decimal Degrees", "Degrees and Decimal Minutes", "NULL entry"])

if coord_format == "Decimal Degrees":
    latitude = st.number_input("Latitude (decimal degrees)", min_value=-90.0, max_value=90.0, step=0.000001, format="%.6f")
    longitude = st.number_input("Longitude (decimal degrees)", min_value=-180.0, max_value=180.0, step=0.000001, format="%.6f")
elif coord_format == "Degrees and Decimal Minutes":
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
st.subheader("Water Depth")
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
core_type_options = {ct[1]: (ct[0], ct[2]) for ct in core_types}  # Map core type names to IDs and required fields
core_type_choice = st.selectbox("Select Core Type", ["Select Core Type"] + list(core_type_options.keys()))

# --- Dynamic Fields ---
dynamic_field_values = {}
if core_type_choice != "Select Core Type":
    core_type_id = core_type_options[core_type_choice][0]  # Fetch core type ID
    dynamic_fields = render_dynamic_fields_from_metadata(core_type_id)

    st.subheader("Dynamic Fields")
    # DELETE this block from add_core_data.py:
    # for field_name, field_type in dynamic_fields.items():
    #     # ... all the manual rendering and value collection ...

# --- Post-Core Type Fields ---
st.subheader("Deployment Details")

# Time Fields
st.subheader("Deployment Times")

# Time Launched
time_launched = custom_time_input("Time Launched", default="")

# Time on Bottom
time_on_bottom = custom_time_input("Time on Bottom", default="")

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

if st.button("Save Core"):
    # Validation: Check for missing fields
    missing_fields = []

    # Check if core_name is blank
    if not core_name.strip():
        missing_fields.append("Core Name")

    # Check if core_type is selected
    if core_type_choice == "Select Core Type":
        missing_fields.append("Core Type")

    # Check dynamic fields for missing values
    for field, value in dynamic_field_values.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            missing_fields.append(field.replace("_", " ").capitalize())

    # Check if date is missing
    if not date_field:
        missing_fields.append("Date")

    # Display warning for missing fields
    if missing_fields:
        st.warning(f"The following fields are missing or incomplete: {', '.join(missing_fields)}")
    else:
        # No missing fields, proceed with saving
        try:
            # Check for duplicate core_name
            with get_connection() as conn:
                duplicate_check_query = "SELECT COUNT(*) FROM cores WHERE core_name = :core_name"
                result = conn.execute(text(duplicate_check_query), {"core_name": core_name}).scalar()
                if result > 0:
                    st.error(f"A core with the name '{core_name}' already exists. Please use a different name.")
                else:
                    # Proceed with insertion if no duplicate is found
                    with get_connection() as conn:  # Open the database connection
                        # Base query (static fields)
                        base_query = """
                            INSERT INTO cores (
                                core_name, vessel_id, cruise, leg, date, station, water_depth_m, latitude, longitude, observer, core_type_id, 
                                time_launched, time_on_bottom, time_recovered, wire_out_on_bottom, max_wire_out, impact_speed,
                                tension_at_surface, tension_near_bottom, tension_on_bottom, pullout_tension, notes
                            """
                        base_values = [
                            core_name, vessel_options[vessel_choice], cruise or None, leg or None, date_field, station or None, 
                            water_depth, latitude, longitude, observer or None, core_type_id, time_launched, time_on_bottom, 
                            time_recovered, wire_out_on_bottom, max_wire_out, impact_speed, tension_at_surface, tension_near_bottom, 
                            tension_at_bottom, pullout_tension, notes or None
                        ]

                        # Handle dynamic fields
                        if dynamic_field_values:
                            dynamic_columns = ", ".join(dynamic_field_values.keys())
                            dynamic_placeholders = ", ".join([":{}".format(key) for key in dynamic_field_values.keys()])
                            dynamic_values = {key: value for key, value in dynamic_field_values.items()}

                            # Combine static and dynamic fields
                            query = f"{base_query}, {dynamic_columns}) VALUES ({', '.join([':{}'.format(i) for i in range(len(base_values))])}, {dynamic_placeholders})"
                            values = {**{str(i): value for i, value in enumerate(base_values)}, **dynamic_values}
                        else:
                            # Static fields only
                            query = f"{base_query}) VALUES ({', '.join([':{}'.format(i) for i in range(len(base_values))])})"
                            values = {str(i): value for i, value in enumerate(base_values)}

                        # Execute the query
                        conn.execute(text(query), values)
                        conn.commit()  # Commit the transaction
                    st.success("Core successfully saved!")
        except Exception as e:
            st.error(f"An error occurred: {e}")
            st.write("Error details:", e)