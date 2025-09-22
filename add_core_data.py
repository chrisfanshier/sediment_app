import streamlit as st
import os
import pandas as pd
from db_util import get_connection
from db_util import fetch_dropdown_values
from utils import render_dynamic_fields_from_metadata
from datetime import date, time

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

    # --- Static Fields ---
st.subheader("Meta Data")
core_name = st.text_input("Core Name*", max_chars=100)
vessel_options = {v[1]: v[0] for v in vessels}  # Map vessel names to IDs
vessel_choice = st.selectbox("Select Vessel", list(vessel_options.keys()))
cruise = st.text_input("Cruise")
leg = st.text_input("Leg")
date_field = st.date_input("Date", value=date.today())
station = st.text_input("Station")

    # Coordinate format selection
st.subheader("Coordinates")
coord_format = st.selectbox("Coordinate Format", ["Decimal Degrees", "Degrees and Decimal Minutes"])

if coord_format == "Decimal Degrees":
    latitude = st.number_input("Latitude (decimal degrees)", min_value=-90.0, max_value=90.0, step=0.000001, format="%.6f")
    longitude = st.number_input("Longitude (decimal degrees)", min_value=-180.0, max_value=180.0, step=0.000001, format="%.6f")
else:  # Degrees and Decimal Minutes
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

water_depth = st.number_input("Water Depth (meters)", min_value=0, step=1)
observer = st.text_input("Observer")
core_type_options = {ct[1]: (ct[0], ct[2]) for ct in core_types}  # Map core type names to IDs and required fields
core_type_choice = st.selectbox("Select Core Type", ["Select Core Type"] + list(core_type_options.keys()))

# --- Dynamic Fields ---
dynamic_field_values = {}
if core_type_choice != "Select Core Type":
    core_type_id = core_type_options[core_type_choice][0]  # Fetch core type ID
    dynamic_field_values = render_dynamic_fields_from_metadata(core_type_id)

# --- Post-Core Type Fields ---
st.subheader("Deployment Details")
time_launched = st.time_input("Time Launched", value=time(0, 0))
time_on_bottom = st.time_input("Time on Bottom", value=time(0, 0))
time_recovered = st.time_input("Time Recovered", value=time(0, 0))
wire_out_on_bottom = st.number_input("Wire Out on Bottom (meters)", min_value=0, step=1)
max_wire_out = st.number_input("Max Wire Out (meters)", min_value=0, step=1)
impact_speed = st.number_input("Impact Speed (m/min)", min_value=0, step=1)
tension_at_surface = st.number_input("Tension at Surface (lbs)", min_value=0, step=1)
tension_near_bottom = st.number_input("Tension Near Bottom (lbs)", min_value=0, step=1)
tension_at_bottom = st.number_input("Tension at Bottom (lbs)", min_value=0, step=1)
pullout_tension = st.number_input("Pullout Tension (lbs)", min_value=0, step=1)
notes = st.text_area("Notes", placeholder="Enter any additional notes or observations here...")

if st.button("Save Core"):
    # Validation: Check for required fields
    missing_fields = []

    if not core_name.strip():  # Check if core_name is blank
        missing_fields.append("Core Name")
    if core_type_choice == "Select Core Type":  # Check if core type is not selected
        missing_fields.append("Core Type")

    for field, value in dynamic_field_values.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            missing_fields.append(field.replace("_", " ").capitalize())

    if missing_fields:
        st.error(f"The following fields are required and cannot be left blank: {', '.join(missing_fields)}")
    else:
        try:
            with get_connection() as conn:  # Open the database connection
                with conn.cursor() as cur:  # Open the cursor
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
                        dynamic_placeholders = ", ".join(["%s"] * len(dynamic_field_values))
                        dynamic_values = list(dynamic_field_values.values())

                        # Combine static and dynamic fields
                        query = f"{base_query}, {dynamic_columns}) VALUES ({', '.join(['%s'] * len(base_values))}, {dynamic_placeholders})"
                        values = base_values + dynamic_values
                    else:
                        # Static fields only
                        query = f"{base_query}) VALUES ({', '.join(['%s'] * len(base_values))})"
                        values = base_values

                    # Execute the query
                    cur.execute(query, values)
                    conn.commit()  # Commit the transaction
            st.success("Core successfully saved!")
        except Exception as e:
            st.error(f"An error occurred: {e}")
            st.write("Error details:", e)