import os
import streamlit as st

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

import psycopg2
import pandas as pd
import numpy as np
from datetime import date
import plotly.express as px
import io
import re

from plotly.subplots import make_subplots
import plotly.graph_objects as go

# Database connection
def get_connection():
    return psycopg2.connect(
        host="localhost",
        database="sediment_cores",
        user="postgres",
        password="madmaxfuryroad"
    )

# Ensure 'uploaded_files' directory exists
upload_folder = "uploaded_files"
if not os.path.exists(upload_folder):
    os.makedirs(upload_folder)

# Function to handle the file upload and save it
def upload_file(uploaded_file):
    # Save the uploaded file to the 'uploaded_files' directory
    file_path = os.path.join(upload_folder, uploaded_file.name)
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())  # Save the file buffer
    return file_path

def fetch_cores():
    with get_connection() as conn:
        query = "SELECT core_id, core_name FROM cores ORDER BY core_name"
        return pd.read_sql(query, conn)

# Function to insert section data into the database
def insert_section_data(core_id, section_data):
    with get_connection() as conn:
        with conn.cursor() as cur:
            query = """
                INSERT INTO sections (core_id, section_number, section_length, top_cum_length, bottom_cum_length)
                VALUES (%s, %s, %s, %s, %s)
            """
            # Prepare values for bulk insertion
            values = [
                (core_id, row["section_number"], row["section_length"], row["top_cum_length"], row["bottom_cum_length"])
                for row in data_list
            ]
            # Execute all rows in one bulk insert
            cur.executemany(query, values)
            conn.commit()

import json
import psycopg2

def get_dynamic_fields_metadata(core_type_id):
    """
    Fetch dynamic fields for the selected core type from the database.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Correct query to fetch the required fields
            cur.execute("SELECT required_fields FROM core_types WHERE core_type_id = %s", (core_type_id,))
            core_type_metadata = cur.fetchone()
            if core_type_metadata:
                # Directly return the data since psycopg2 already deserializes the JSON column
                return core_type_metadata[0]
    return []

def get_column_data_types(table_name):
    """
    Fetch column data types for a given table from the database.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Query information_schema to get column data types
            cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = %s
            """, (table_name,))
            return {row[0]: row[1] for row in cur.fetchall()}

def map_data_type_to_input(data_type):
    """
    Map database column data types to Streamlit input types.
    """
    if data_type in ["integer", "bigint", "smallint"]:
        return {"input_type": "integer", "step": 1, "format": "%d"}
    elif data_type in ["real", "double precision", "numeric", "decimal"]:
        return {"input_type": "float", "step": 0.01, "format": "%.2f"}
    elif data_type in ["character varying", "text"]:
        return {"input_type": "text"}
    elif data_type in ["boolean"]:
        return {"input_type": "boolean"}
    elif data_type in ["date"]:
        return {"input_type": "date"}
    elif data_type in ["time without time zone", "time with time zone"]:
        return {"input_type": "time"}
    else:
        return {"input_type": "text"}  # Default to text input

def render_dynamic_fields_from_metadata(core_type_id):
    """
    Render dynamic fields based on metadata from the database.
    """
    # Fetch dynamic fields metadata
    dynamic_fields = get_dynamic_fields_metadata(core_type_id) or []  # Ensure it's a list, even if None is returned

    dynamic_field_values = {}

    # Render input fields based on the metadata
    for field in dynamic_fields:
        field_name = field.replace("_", " ").capitalize()  # Clean up field names for display

        # Map the data type to Streamlit input type
        input_metadata = map_data_type_to_input(field)

        # Render inputs dynamically
        if input_metadata["input_type"] == "integer":
            dynamic_field_values[field] = st.number_input(
                f"{field_name} (integer)", min_value=0, step=input_metadata["step"], format=input_metadata["format"]
            )
        elif input_metadata["input_type"] == "float":
            dynamic_field_values[field] = st.number_input(
                f"{field_name} (numeric)", min_value=0.0, step=input_metadata["step"], format=input_metadata["format"]
            )
        elif input_metadata["input_type"] == "text":
            dynamic_field_values[field] = st.text_input(f"{field_name}")
        elif input_metadata["input_type"] == "boolean":
            dynamic_field_values[field] = st.checkbox(f"{field_name}")
        elif input_metadata["input_type"] == "date":
            dynamic_field_values[field] = st.date_input(f"{field_name}")
        elif input_metadata["input_type"] == "time":
            dynamic_field_values[field] = st.time_input(f"{field_name}")
        else:
            dynamic_field_values[field] = st.text_input(f"{field_name} (default)")

    return dynamic_field_values
def parse_mscl_out_file(uploaded_file):
    import re
    import pandas as pd
    import streamlit as st

    try:
        # Read the file and split it into lines
        lines = uploaded_file.read().decode("utf-8").splitlines()
        header_index = None

        # Locate the header row
        for i, line in enumerate(lines):
            if line.strip().startswith("SB DEPTH"):
                header_index = i
                break

        if header_index is None:
            st.error("Could not find data header in file.")
            return None

        # Extract header using 2+ spaces, tab, or end of line as delimiters
        header_line = lines[header_index]
        header = re.findall(r"[A-Za-z0-9\^\-\(\)\/\s]+?(?=\s{2,}|\t|$)", header_line.strip())

        # Parse data rows
        data_lines = lines[header_index + 2:]  # Skip the header and unit row
        data = []
        for line in data_lines:
            if not line.strip():
                continue  # Skip empty lines
            values = re.split(r'\s{2,}|\t', line.strip())  # Split by 2+ spaces or tabs
            while len(values) < len(header):  # Pad missing values with None
                values.append(None)
            data.append(values[:len(header)])  # Ensure no extra values beyond headers

        # Create a DataFrame
        df = pd.DataFrame(data, columns=header)

        # Convert numeric columns where possible
        for col in df.columns:
            try:
                df[col] = pd.to_numeric(df[col], errors='coerce')  # Convert to numeric, set invalid values to NaN
            except Exception as e:
                st.warning(f"Could not convert column '{col}' to numeric: {e}")

        # Drop rows where all entries are NaN
        df.dropna(how="all", inplace=True)

        # Return the cleaned DataFrame
        return df

    except Exception as e:
        st.error(f"An error occurred while parsing the file: {e}")
        return None

# Function to plot mscl data
def plot_mscl_data(df, x_col, y_col, core_name, x_min, x_max, y_min, y_max):
    # Create the figure
    fig = go.Figure()

    # Plot the first trace (MS vs Depth)
    fig.add_trace(go.Scatter(
        x=df[x_col], 
        y=df[y_col], 
        mode='lines', 
        name=x_col, 
        line=dict(color='blue')
    ))

    # Plot the second trace (Density vs Depth), only if 'Den1' column exists
    if 'Den1' in df.columns:
        fig.add_trace(go.Scatter(
            x=df['Den1'], 
            y=df[y_col], 
            mode='lines', 
            name=x_col, 
            line=dict(color='red')
        ))

    # Apply the layout configuration
    fig.update_layout(
        title=f"{core_name}: {x_col} vs Depth",
        xaxis_title="Value",
        yaxis_title="Depth (SB DEPTH)",
        showlegend=True,
        height=1200
    )

    # Apply X axis limits if provided
    if x_min is not None and x_max is not None:
        fig.update_xaxes(range=[x_min, x_max])

    # Apply Y axis limits and reverse depth (ensure deeper is lower on the y-axis)
    if y_min is not None and y_max is not None:
        fig.update_yaxes(range=[y_max, y_min], autorange=False)  # Reverse depth (higher to lower)
    else:
        fig.update_yaxes(autorange='reversed')  # Reverse the y-axis automatically

    # Show the plot in Streamlit
    st.plotly_chart(fig)

# Function to compare and plot mscl data
def plot_mscl_data_compare(
    df1,
    df2,
    x_col,
    y_col,
    core_name_1,
    core_name_2,
    plot_type="Overlay",
    x_min=None,
    x_max=None,
    y_min=None,
    y_max=None,
    x_offset=0.0,
    y_offset=0.0,
    x_scale=1.0,
    y_scale=1.0
):
    if plot_type == "Side by Side":
        fig = make_subplots(rows=1, cols=2, shared_yaxes=True, subplot_titles=(core_name_1, core_name_2))
        
        # Core 1
        fig.add_trace(go.Scatter(
            x=df1[x_col],
            y=df1[y_col],
            mode='lines',
            line=dict(color='blue')
        ), row=1, col=1)

        # Core 2 (transformed)
        x2 = df2[x_col] * x_scale + x_offset
        y2 = df2[y_col] * y_scale + y_offset
        fig.add_trace(go.Scatter(
            x=x2,
            y=y2,
            mode='lines',
            line=dict(color='red')
        ), row=1, col=2)

        # Update axes ranges
        if x_min is not None and x_max is not None:
            fig.update_xaxes(range=[x_min, x_max], row=1, col=1)
            fig.update_xaxes(range=[x_min, x_max], row=1, col=2)
        if y_min is not None and y_max is not None:
            fig.update_yaxes(range=[y_max, y_min], row=1, col=1)  # Reverse depth
            fig.update_yaxes(range=[y_max, y_min], row=1, col=2)  # Reverse depth
        else:
            fig.update_yaxes(autorange="reversed", row=1, col=1)  # Reverse depth
            fig.update_yaxes(autorange="reversed", row=1, col=2)  # Reverse depth

        fig.update_layout(
            height=1200  # Adjust height
        )

    else:  # Overlay
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df1[x_col],
            y=df1[y_col],
            mode='lines',
            name=core_name_1,  # Name for Core 1
            line=dict(color='blue')
        ))
        x2 = df2[x_col] * x_scale + x_offset
        y2 = df2[y_col] * y_scale + y_offset
        fig.add_trace(go.Scatter(
            x=x2,
            y=y2,
            mode='lines',
            name=core_name_2,  # Name for Core 2
            line=dict(color='red')
        ))

        # Axis settings for overlay
        fig.update_layout(
            title=f"{core_name_1} vs {core_name_2} - {x_col}",  # Updated title
            xaxis=dict(
                range=[x_min, x_max] if x_min is not None and x_max is not None else None
            ),
            yaxis=dict(
                range=[y_max, y_min] if y_min is not None and y_max is not None else None,
                autorange="reversed" if y_min is None and y_max is None else False  # Reverse for depth
            ),
            showlegend=False,  # Disable legend
            height=1200  # Adjust height
        )

    # Show the comparison plot
    st.plotly_chart(fig, use_container_width=True)

import plotly.graph_objects as go

def plot_mscl_data_compare(
    df1,
    df2,
    x_col,
    y_col,
    core_name_1,
    core_name_2,
    plot_type="Overlay",
    x_min=None,
    x_max=None,
    y_min=None,
    y_max=None,
    x_offset=0.0,
    y_offset=0.0,
    x_scale=1.0,
    y_scale=1.0
):
    if plot_type == "Side by Side":
        fig = make_subplots(rows=1, cols=2, shared_yaxes=True, subplot_titles=(core_name_1, core_name_2))
        
        # Core 1
        fig.add_trace(go.Scatter(
            x=df1[x_col],
            y=df1[y_col],
            mode='lines+markers',
            name=core_name_1,
            line=dict(color='blue')
        ), row=1, col=1)

        # Core 2 (transformed)
        x2 = df2[x_col] * x_scale + x_offset
        y2 = df2[y_col] * y_scale + y_offset
        fig.add_trace(go.Scatter(
            x=x2,
            y=y2,
            mode='lines+markers',
            name=core_name_2,
            line=dict(color='red')
        ), row=1, col=2)

        # Update axes ranges
        if x_min is not None and x_max is not None:
            fig.update_xaxes(range=[x_min, x_max], row=1, col=1)
            fig.update_xaxes(range=[x_min, x_max], row=1, col=2)
        if y_min is not None and y_max is not None:
            fig.update_yaxes(range=[y_max, y_min], row=1, col=1)  # Reverse for depth
            fig.update_yaxes(range=[y_max, y_min], row=1, col=2)  # Reverse for depth
        else:
            fig.update_yaxes(autorange="reversed", row=1, col=1)  # Reverse for depth
            fig.update_yaxes(autorange="reversed", row=1, col=2)  # Reverse for depth

        fig.update_layout(
            title=f"Comparison of {core_name_1} and {core_name_2} for {x_col}",  # Dynamic title
            height=1200  # Adjust height
        )
    else:  # Overlay
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df1[x_col],
            y=df1[y_col],
            mode='lines+markers',
            name=core_name_1,
            line=dict(color='blue')
        ))
        x2 = df2[x_col] * x_scale + x_offset
        y2 = df2[y_col] * y_scale + y_offset
        fig.add_trace(go.Scatter(
            x=x2,
            y=y2,
            mode='lines+markers',
            name=core_name_2,
            line=dict(color='red')
        ))

        # Axis settings for overlay
        fig.update_layout(
            title=f"Overlay: {core_name_1} vs {core_name_2} for {x_col}",  # Dynamic title
            xaxis=dict(
                range=[x_min, x_max] if x_min is not None and x_max is not None else None
            ),
            yaxis=dict(
                range=[y_max, y_min] if y_min is not None and y_max is not None else None,
                autorange="reversed" if y_min is None and y_max is None else False  # Reverse for depth
            ),
            height=1200
        )

    # Show the comparison plot
    st.plotly_chart(fig, use_container_width=True)

import streamlit as st
import psycopg2
from datetime import date, time
import json

# Fetch dropdown options
def fetch_dropdown_values():
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Fetch vessels
            cur.execute("SELECT vessel_id, vessel_name FROM vessels ORDER BY vessel_name;")
            vessels = cur.fetchall()

            # Fetch core types
            cur.execute("SELECT core_type_id, core_type_name, required_fields FROM core_types ORDER BY core_type_name;")
            core_types = cur.fetchall()

    return vessels, core_types

def render_dynamic_fields(core_type_choice, required_fields):
    dynamic_field_values = {}  # Dictionary to store field names and user inputs

    st.subheader(f"Dynamic Fields for {core_type_choice}")

    for field in required_fields:
        # Render a number input for numeric fields
        if "weight" in field.lower() or "length" in field.lower() or "depth" in field.lower():
            dynamic_field_values[field] = st.number_input(f"{field.replace('_', ' ').capitalize()} (numeric)", min_value=0.0, step=1.0)
        else:
            # Default to a text input for other fields
            dynamic_field_values[field] = st.text_input(f"{field.replace('_', ' ').capitalize()}")

    return dynamic_field_values

@st.cache_data
def process_rsk_data(file_path):
    """Process the RSK file and return a DataFrame with calculated fields."""
    from pyrsktools import RSK
    import pandas as pd

    with RSK(file_path) as rsk:
        rsk.open()
        rsk.readdata()
        rsk.deriveseapressure()  # Calculate sea pressure
        rsk.derivedepth(latitude=45.0)  # Calculate depth

        # Convert to DataFrame
        data_dict = {
            "Timestamp": rsk.data["timestamp"],
            "Pressure (dbar)": rsk.data["pressure"],
            "Sea Pressure (dbar)": rsk.data["sea_pressure"],
            "Depth (m)": rsk.data["depth"],
        }
        df = pd.DataFrame(data_dict)
    return df

@st.cache_data
def downsample_data(df, max_points=1000):
    """Downsample the DataFrame to a maximum number of points."""
    import numpy as np

    if len(df) > max_points:
        indices = np.linspace(0, len(df) - 1, max_points, dtype=int)
        return df.iloc[indices]
    return df

# Sidebar navigation
menu = ["Add Core", "View Cores", "Manage Files", "Visualize MSCL Data", "Input Section Length Data", "Visualize RSK Data", "View Core Section Data"]

choice = st.sidebar.radio("Select Option", menu)

# --- Add Core Page ---
if choice == "Add Core":
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
# --- View Cores Page ---
elif choice == "View Cores":
    st.title("📊 View and Explore Cores Data")

    # Fetch the cores table from the database
    with get_connection() as conn:
        query_cores = "SELECT * FROM cores ORDER BY core_name"
        cores_data = pd.read_sql(query_cores, conn)

        # Fetch vessel names
        query_vessels = "SELECT vessel_id, vessel_name FROM vessels"
        vessels_df = pd.read_sql(query_vessels, conn)
        vessel_map = vessels_df.set_index('vessel_id')['vessel_name'].to_dict()

        # Fetch core type names
        query_core_types = "SELECT core_type_id, core_type_name FROM core_types"
        core_types_df = pd.read_sql(query_core_types, conn)
        core_type_map = core_types_df.set_index('core_type_id')['core_type_name'].to_dict()

        # Replace IDs with names
        cores_data['vessel_name'] = cores_data['vessel_id'].map(vessel_map).fillna(cores_data['vessel_id'])
        cores_data['core_type_name'] = cores_data['core_type_id'].map(core_type_map).fillna(cores_data['core_type_id'])

        # Drop the original ID columns if you only want to display names
        if 'vessel_id' in cores_data.columns:
            cores_data.drop(columns=['vessel_id'], inplace=True)
        if 'core_type_id' in cores_data.columns:
            cores_data.drop(columns=['core_type_id'], inplace=True)

    if not cores_data.empty:
        # Sidebar Search Boxes (Above Column Selection)
        st.sidebar.header("Search")
        search_cruise = st.sidebar.text_input("Search Cruise:", value="")
        search_core_name = st.sidebar.text_input("Search Core Name:", value="")

        # Sidebar: Column visibility toggle
        st.sidebar.header("Column Visibility")
        all_columns = list(cores_data.columns)  # Get all column names
        visible_columns = st.sidebar.multiselect(
            "Select columns to display:",
            options=all_columns,
            default=all_columns  # Default to showing all columns
        )

        # Filter the DataFrame to only show selected columns
        filtered_data = cores_data[visible_columns].copy()

        # Apply search filters
        if search_cruise:
            filtered_data = filtered_data[filtered_data['cruise'].astype(str).str.contains(search_cruise, case=False)]
        if search_core_name:
            filtered_data = filtered_data[filtered_data['core_name'].astype(str).str.contains(search_core_name, case=False)]

        # Sidebar filters for all visible columns (excluding search fields)
        st.sidebar.header("Filter Options")
        for column in visible_columns:
            if column not in ["cruise", "core_name", "vessel_name", "core_type_name"]: # Exclude the name columns as well
                unique_values = cores_data[column].dropna().unique()

                if len(unique_values) < 20:  # Use a multiselect filter for categorical-like columns
                    selected_values = st.sidebar.multiselect(
                        f"Filter by {column}:", options=["All"] + list(unique_values), default="All"
                    )
                    if "All" not in selected_values:
                        filtered_data = filtered_data[filtered_data[column].isin(selected_values)]

        # Show the filtered table
        st.write("### Cores Table")
        st.dataframe(filtered_data, use_container_width=True)  # Display the filtered cores table

        # Add download functionality for filtered data
        st.download_button(
            label="Download Filtered Data as CSV",
            data=filtered_data.to_csv(index=False),  # Convert the filtered DataFrame to a CSV string
            file_name="filtered_cores_table.csv",
            mime="text/csv"
        )

        # Inform users about filtering and column visibility
        st.markdown(
            """
            - Use the **sidebar** to search by Cruise and Core Name, toggle column visibility, and filter the table.
            - The table updates dynamically based on your selections.
            - You can also download the filtered data using the button below.
            """
        )
    else:
        st.write("No cores added yet.")

# --- Manage Files Page ---
elif choice == "Manage Files":
    st.title("📂 Manage Associated Data Files")
    st.write("You can upload and manage files related to sediment cores here.")

    # Fetch list of cores
    cores = fetch_cores()
    if cores.empty:
        st.warning("No cores found. Please add cores first.")
    else:
        core_options = {f"{name} (ID: {id})": id for id, name in zip(cores['core_id'], cores['core_name'])}

        # Dropdown to select core
        selected_core_label = st.selectbox("Select Core to Associate File With", list(core_options.keys()))
        selected_core_id = core_options[selected_core_label]

        # File type selection
        file_type = st.selectbox("Select File Type", ["MSCL Data", "RBR Sensor", "Star-Oddi Sensor"])

        # Dynamically set allowed file extensions based on file type
        allowed_extensions = {"MSCL Data": ["out"], "RBR Sensor": ["rsk"], "Star-Oddi Sensor": []}
        file_extensions = allowed_extensions[file_type]

        # Initialize session state for uploaded file tracking
        if "last_uploaded_file" not in st.session_state:
            st.session_state.last_uploaded_file = None

        # Upload file
        uploaded_file = st.file_uploader("Upload Data File", type=file_extensions, key="file_uploader")

        # Process the uploaded file only if it's new
        if uploaded_file is not None and uploaded_file != st.session_state.last_uploaded_file:
            # Save the file to session state to prevent duplicate processing
            st.session_state.last_uploaded_file = uploaded_file

            # Save the uploaded file
            def upload_file(file):
                import os
                upload_dir = "uploaded_files"
                os.makedirs(upload_dir, exist_ok=True)  # Ensure the directory exists
                file_path = os.path.join(upload_dir, file.name)
                with open(file_path, "wb") as f:
                    f.write(file.getbuffer())
                return file_path

            # Insert file into the database
            def insert_file(core_id, file_name, file_path, file_type):
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        query = """
                            INSERT INTO files (core_id, file_name, file_path, file_type)
                            VALUES (%s, %s, %s, %s)
                        """
                        cur.execute(query, (core_id, file_name, file_path, file_type))
                        conn.commit()

            # Ensure only the current file is processed
            with st.spinner(f"Processing file '{uploaded_file.name}'..."):
                # Save the file to the 'uploaded_files' directory
                uploaded_file_path = upload_file(uploaded_file)
                st.success(f"File '{uploaded_file.name}' uploaded successfully!")
                st.write(f"File saved at: {uploaded_file_path}")

                # Insert the uploaded file into the database with the selected file type
                insert_file(selected_core_id, uploaded_file.name, uploaded_file_path, file_type)

                # If the file type is "MSCL Data", attempt to parse and display it
                if file_type == "MSCL Data":
                    # Parse the uploaded MSCL data
                    df = parse_mscl_out_file(uploaded_file)

                    # Display parsed data if available
                    if df is not None:
                        st.write("Parsed MSCL Data Preview:")
                        st.dataframe(df)

                        # Plot Magnetic Susceptibility vs Depth if columns exist
                        if "SB DEPTH" in df.columns and "MS1" in df.columns:
                            import plotly.express as px
                            fig = px.line(df, x="SB DEPTH", y="MS1", title="Magnetic Susceptibility vs Depth")
                            st.plotly_chart(fig, use_container_width=True)

        elif uploaded_file is not None:
            st.warning("This file has already been processed. Please upload a new file.")

# --- Visualize MSCL Data Page ---
elif choice == "Visualize MSCL Data":
    st.title("📊 Visualize MSCL Data")

    # Initialize session state for comparison
    if 'compare_enabled' not in st.session_state:
        st.session_state['compare_enabled'] = False
    if 'comparison_settings_expanded' not in st.session_state:
        st.session_state['comparison_settings_expanded'] = False

    # Fetch list of cores
    cores = fetch_cores()
    core_options = {f"{name} (ID: {id})": id for id, name in zip(cores['core_id'], cores['core_name'])}

    # Create two columns: controls on the left, plot on the right
    col1, col2 = st.columns([1, 3])  # Adjust the width ratio (e.g., 1:3)

    with col1:
        st.header("Controls")

        # Expander for Core and File Selection
        with st.expander("Core and File Selection", expanded=True):
            selected_core_label = st.selectbox("Select Core to Visualize MSCL Data", list(core_options.keys()))
            selected_core_id = core_options[selected_core_label]

            # Fetch associated MSCL files for the selected core
            with get_connection() as conn:
                query = "SELECT file_name, file_path FROM files WHERE core_id = %s AND file_type = 'MSCL Data'"
                df_files = pd.read_sql(query, conn, params=(selected_core_id,))

            if not df_files.empty:
                selected_file_label = st.selectbox("Select MSCL Data File", df_files['file_name'])
                file_row = df_files[df_files['file_name'] == selected_file_label].iloc[0]
                uploaded_file_path = file_row['file_path']
            else:
                st.warning("No MSCL file for this core.")
                uploaded_file_path = None  # Ensure the variable is defined

        # Proceed only if a valid file is selected for the primary core
        if uploaded_file_path:
            with st.expander("Plot Settings"):
                # Parse the selected MSCL file
                try:
                    with open(uploaded_file_path, "rb") as file:
                        df = parse_mscl_out_file(file)

                    if df is not None:
                        # Toggle to show/hide parsed data preview
                        show_parsed_data = st.checkbox("Show Parsed Data Preview", value=False)
                        if show_parsed_data:
                            st.write("Parsed MSCL Data Preview:")
                            st.dataframe(df)

                        numeric_columns = df.select_dtypes(include='number').columns.tolist()
                        if "SB DEPTH" in numeric_columns:
                            numeric_columns.remove("SB DEPTH")

                        if numeric_columns:
                            parameter = st.selectbox("Select Parameter to Plot", options=numeric_columns, index=0)
                            x_min = st.number_input('Set X-axis Min', value=float(df[parameter].min()), step=0.1)
                            x_max = st.number_input('Set X-axis Max', value=float(df[parameter].max()), step=0.1)
                            y_min = st.number_input('Set Y-axis Min (Depth)', value=float(df["SB DEPTH"].min()), step=0.1)
                            y_max = st.number_input('Set Y-axis Max (Depth)', value=float(df["SB DEPTH"].max()), step=0.1)
                        else:
                            st.warning("No numeric columns found for plotting.")
                            df = None # Prevent further processing if no valid data
                    else:
                        st.warning("Could not parse the MSCL data file.")
                except Exception as e:
                    st.error(f"An error occurred while processing the file: {e}")
                    df = None # Prevent further processing if an error occurred

            if df is not None:
                # Expander for Dropout Filter
                with st.expander("Dropout Filter"):
                    enable_filter = st.checkbox("Apply Drop Out Filter", value=False)
                    if enable_filter and numeric_columns:
                        filter_column = st.selectbox("Select Column for Drop Out Filter", options=numeric_columns, index=0)
                        threshold = st.number_input(f"Set Threshold for '{filter_column}'", value=0.0, step=0.1)
                        filtered_df = df[df[filter_column] >= threshold].copy() # Use .copy() to avoid SettingWithCopyWarning
                        show_filtered_data = st.checkbox("Show Filtered Data Preview", value=False)
                        if show_filtered_data:
                            st.write("Filtered Data Preview:")
                            st.dataframe(filtered_df)
                    else:
                        filtered_df = df.copy() # Use .copy() to avoid potential issues

                # Expander for Comparison Settings
                with st.expander("Comparison Settings", expanded=st.session_state.get('comparison_settings_expanded', False)):
                    st.session_state['compare_enabled'] = st.checkbox("Compare with Another Core", value=st.session_state.get('compare_enabled', False)) # Removed on_change
                    if st.session_state['compare_enabled']:
                        other_core_options = core_options.copy()
                        del other_core_options[selected_core_label]
                        second_core_label = st.selectbox("Select Second Core", list(other_core_options.keys()))
                        second_core_id = other_core_options[second_core_label]

                        with get_connection() as conn:
                            query = "SELECT file_name, file_path FROM files WHERE core_id = %s AND file_type = 'MSCL Data'"
                            df_files_2 = pd.read_sql(query, conn, params=(second_core_id,))

                        if not df_files_2.empty:
                            selected_file_label_2 = st.selectbox("Select MSCL Data File for Second Core", df_files_2['file_name'])
                            file_row_2 = df_files_2[df_files_2['file_name'] == selected_file_label_2].iloc[0]
                            uploaded_file_path_2 = file_row_2['file_path']

                            try:
                                with open(uploaded_file_path_2, "rb") as file2:
                                    df2 = parse_mscl_out_file(file2)

                                if df2 is not None:
                                    # Apply the same filter to the second core (if enabled)
                                    if enable_filter and filter_column in df2.columns:
                                        filtered_df2 = df2[df2[filter_column] >= threshold].copy()
                                    else:
                                        filtered_df2 = df2.copy()

                                    # Plot type: Overlay or Side by Side
                                    plot_type = st.radio("Plot Type", ["Overlay", "Side by Side"])

                                    # Adjustments for the second core
                                    st.markdown("### Adjustments for Second Core")
                                    x_offset = st.number_input("X Offset", value=0.0, step=0.1)
                                    y_offset = st.number_input("Y Offset (Depth)", value=0.0, step=0.1)
                                    x_scale = st.number_input("X Scale (stretch/compress)", value=1.0, step=0.1, min_value=0.1)
                                    y_scale = st.number_input("Y Scale (stretch/compress)", value=1.0, step=0.1, min_value=0.1)

                                    # Plot the comparison
                                    with col2:
                                        plot_mscl_data_compare(
                                            df1=filtered_df,
                                            df2=filtered_df2,
                                            x_col=parameter,
                                            y_col="SB DEPTH",
                                            core_name_1=selected_core_label,  # Pass the name of the first core
                                            core_name_2=second_core_label,    # Pass the name of the second core
                                            plot_type=plot_type,
                                            x_min=x_min,
                                            x_max=x_max,
                                            y_min=y_min,
                                            y_max=y_max,
                                            x_offset=x_offset,
                                            y_offset=y_offset,
                                            x_scale=x_scale,
                                            y_scale=y_scale
                                        )
                                else:
                                    st.warning("Could not parse second MSCL data file.")
                            except Exception as e:
                                st.error(f"An error occurred while processing the second file: {e}")
                        else:
                            st.info("No MSCL data files found for the selected second core.") 
                    else:
                        # Plot the single core data with the filter applied
                        if df is not None and not filtered_df.empty and parameter: # Ensure df is valid and parameter is defined
                            with col2:
                                plot_mscl_data(
                                    df=filtered_df,
                                    x_col=parameter,
                                    y_col="SB DEPTH",
                                    core_name=selected_core_label,
                                    x_min=x_min,
                                    x_max=x_max,
                                    y_min=y_min,
                                    y_max=y_max
                                )
        else:
            st.info("Please select an MSCL data file to visualize.")


# Input Section Length Data Page
elif choice == "Input Section Length Data":
    st.title("✏️ Input Section Length Data")
    st.write("Select a core and manually input section length data or calculate cumulative depths from MSCL data.")

    # Fetch list of cores
    cores = fetch_cores()
    if cores.empty:
        st.warning("No cores found. Please add cores first.")
    else:
        core_options = {f"{name} (ID: {id})": id for id, name in zip(cores['core_id'], cores['core_name'])}

        # Dropdown to select a core
        selected_core_label = st.selectbox("Select Core to Input Section Data", list(core_options.keys()))
        selected_core_id = core_options[selected_core_label]

        # Section for MSCL file selection and preview
        st.subheader(f"Select MSCL File for Core: {selected_core_label}")

        with get_connection() as conn:
            query = "SELECT file_name, file_path FROM files WHERE core_id = %s AND file_type = 'MSCL Data'"
            mscl_files = pd.read_sql(query, conn, params=(selected_core_id,))

        if not mscl_files.empty:
            selected_file_label = st.selectbox("Select MSCL Data File", mscl_files['file_name'])
            file_row = mscl_files[mscl_files['file_name'] == selected_file_label].iloc[0]
            uploaded_file_path = file_row['file_path']

            # Parse and preview the selected MSCL file
            with open(uploaded_file_path, "rb") as file:
                df = parse_mscl_out_file(file)
                if df is not None:
                    st.write("### Parsed MSCL Data Preview:")
                    st.dataframe(df)

                    # Use column indices to explicitly select the required columns
                    try:
                        sb_depth_col = df.columns[0]  # First column
                        sect_num_col = df.columns[1]  # Second column
                        st.write(f"Identified SB DEPTH Column: {sb_depth_col}")
                        st.write(f"Identified Section Number Column: {sect_num_col}")

                        # Group by Section Number and calculate section lengths
                        section_data = df.groupby(sect_num_col).agg(
                            section_length=(sb_depth_col, lambda x: x.max() - x.min())
                        ).reset_index()

                        # Calculate cumulative depths
                        cumulative_length = 0.0
                        section_data["top_cum_length"] = 0.0
                        section_data["bottom_cum_length"] = 0.0
                        for index, row in section_data.iterrows():
                            top_cum_length = cumulative_length
                            bottom_cum_length = top_cum_length + row["section_length"]
                            cumulative_length = bottom_cum_length

                            section_data.at[index, "top_cum_length"] = top_cum_length
                            section_data.at[index, "bottom_cum_length"] = bottom_cum_length

                        # Rename columns and ensure proper data types
                        section_data.rename(columns={
                            sect_num_col: "section_number",  # Rename SECT NUM to section_number
                            "section_length": "section_length",
                            "top_cum_length": "top_cum_length",
                            "bottom_cum_length": "bottom_cum_length"
                        }, inplace=True)

                        # Ensure all data types are correct for the database
                        section_data = section_data.astype({
                            "section_number": int,  # Convert section_number to integer
                            "section_length": float,  # Convert section_length to numeric (float)
                            "top_cum_length": float,  # Convert top_cum_length to numeric (float)
                            "bottom_cum_length": float  # Convert bottom_cum_length to numeric (float)
                        })

                        # Display the calculated section data
                        st.subheader("Cumulative Depth Table")
                        st.dataframe(section_data)

                        # Convert DataFrame to a list of dictionaries with native Python types
                        data_to_insert = section_data.astype({
                            "section_number": int,  # Ensure section_number is an integer
                            "section_length": float,  # Ensure section_length is a float
                            "top_cum_length": float,  # Ensure top_cum_length is a float
                            "bottom_cum_length": float  # Ensure bottom_cum_length is a float
                        }).to_dict(orient="records")

                        # Debugging: Display the converted data
                        st.write("Data prepared for database insertion:", data_to_insert)

                        # Save section data to the database
                        if st.button("Save Section Data"):
                            try:
                                # Convert DataFrame to a list of dictionaries with native Python types
                                data_list = section_data.astype({
                                    "section_number": int,  # Ensure section_number is an integer
                                    "section_length": float,  # Ensure section_length is a float
                                    "top_cum_length": float,  # Ensure top_cum_length is a float
                                    "bottom_cum_length": float  # Ensure bottom_cum_length is a float
                                }).to_dict(orient="records")

                                # Call the bulk insertion function
                                insert_section_data(selected_core_id, data_list)
                                st.success("Section data saved successfully!")
                            except Exception as e:
                                st.error(f"An error occurred while saving section data: {e}")
                    except IndexError:
                        st.error("The expected column indices (1st for SB DEPTH and 2nd for SECT NUM) are not present.")
                else:
                    st.warning("Failed to parse the selected MSCL file.")
        else:
            st.info("No MSCL data files found for the selected core.")

        # Manual input of section lengths
        st.subheader(f"Manually Input Section Data for Core: {selected_core_label}")

        # Number of sections
        num_sections = st.number_input("Enter the number of sections:", min_value=1, step=1, value=1)

        # Create an empty DataFrame to store section data
        section_data_manual = pd.DataFrame(columns=["section_number", "section_length", "top_cum_length", "bottom_cum_length"])

        # Input section lengths
        cumulative_length = 0.0
        for section_number in range(1, num_sections + 1):
            section_length = st.number_input(f"Enter length for Section {section_number} (cm):", min_value=0.0, step=0.1, key=f"length_{section_number}")

            # Calculate cumulative lengths
            top_cum_length = cumulative_length
            bottom_cum_length = top_cum_length + section_length
            cumulative_length = bottom_cum_length

            # Append data to the DataFrame
            section_data_manual = pd.concat([section_data_manual, pd.DataFrame({
                "section_number": [section_number],
                "section_length": [section_length],
                "top_cum_length": [top_cum_length],
                "bottom_cum_length": [bottom_cum_length]
            })], ignore_index=True)

        # Display the manually entered section data
        st.subheader("Manually Entered Section Data")
        st.write(section_data_manual)

        # Save manually entered section data to the database
        if st.button("Save Manual Section Data"):
            try:
                # Convert the manual DataFrame to a list of dictionaries
                data_list = section_data_manual.astype({
                    "section_number": int,  # Ensure section_number is an integer
                    "section_length": float,  # Ensure section_length is a float
                    "top_cum_length": float,  # Ensure top_cum_length is a float
                    "bottom_cum_length": float  # Ensure bottom_cum_length is a float
                }).to_dict(orient="records")

                # Pass the list of dictionaries to the bulk insert function
                insert_section_data(selected_core_id, data_list)
                st.success("Manually entered section data saved successfully!")
            except Exception as e:
                st.error(f"An error occurred while saving manual section data: {e}")                       

elif choice == "Visualize RSK Data":
    # --- Visualize RSK Data Page ---
    st.title("📊 Visualize RSK Data")

    # Core Selection
    @st.cache_data
    def fetch_cores():
        """Fetch list of cores from the database."""
        with get_connection() as conn:
            query = "SELECT core_id, core_name FROM cores"
            cores = pd.read_sql(query, conn)
        return cores

    @st.cache_data
    def fetch_files_for_core(core_id):
        """Fetch list of RSK files associated with a given core."""
        with get_connection() as conn:
            query = "SELECT file_name, file_path FROM files WHERE core_id = %s AND file_type = 'RBR Sensor'"
            files = pd.read_sql(query, conn, params=(core_id,))
        return files

    # Dropdown for selecting a core
    cores = fetch_cores()
    if not cores.empty:
        core_options = {f"{name} (ID: {id})": id for id, name in zip(cores['core_id'], cores['core_name'])}
        selected_core_label = st.selectbox("Select Core to Visualize RSK Data", list(core_options.keys()))
        selected_core_id = core_options[selected_core_label]

        # Dropdown for selecting an RSK file
        files = fetch_files_for_core(selected_core_id)
        if not files.empty:
            file_options = {file_name: file_path for file_name, file_path in zip(files['file_name'], files['file_path'])}
            selected_file_label = st.selectbox("Select RSK Data File", list(file_options.keys()))
            selected_file_path = file_options[selected_file_label]

            # Proceed with the selected file
            if selected_file_path:
                # Save the selected file path to a temporary location
                temp_file_path = "temp_rsk_file.rsk"
                with open(temp_file_path, "wb") as f:
                    f.write(open(selected_file_path, "rb").read())

                try:
                    # Process the RSK file and cache the results
                    st.subheader("Processing RSK File...")
                    df = process_rsk_data(temp_file_path)

                    st.subheader("Preview of Data")
                    st.dataframe(df.head())

                    # Downsample data for plotting
                    st.subheader("Interactive Plotting")
                    max_points = st.slider("Max Points for Plotting", min_value=100, max_value=5000, value=1000, step=100)
                    downsampled_df = downsample_data(df, max_points=max_points)

                    # Dropdown for selecting a parameter to plot
                    y_axis = st.selectbox(
                        "Select Parameter to Plot:",
                        options=["Pressure (dbar)", "Sea Pressure (dbar)", "Depth (m)"],
                        index=2
                    )

                    # Plotly interactive plot with downsampled data
                    fig = px.line(downsampled_df, x="Timestamp", y=y_axis, title=f"{y_axis} Over Time (Downsampled)")
                    fig.update_layout(
                        xaxis_title="Timestamp",
                        yaxis_title=y_axis,
                        template="plotly_white",
                        height=600,
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    # High-Resolution View
                    st.subheader("High-Resolution Zoom")
                    st.markdown(
                        "Zoom in on the plot above to identify the time range you're interested in, "
                        "then click the button below to view all data points in the selected range."
                    )

                    # Allow users to enter the high-resolution range manually
                    start_time = st.text_input(
                        "Start Time (YYYY-MM-DD HH:MM:SS):",
                        value=str(downsampled_df["Timestamp"].iloc[0])
                    )
                    end_time = st.text_input(
                        "End Time (YYYY-MM-DD HH:MM:SS):",
                        value=str(downsampled_df["Timestamp"].iloc[-1])
                    )

                    if st.button("Refresh High Resolution Plot"):
                        try:
                            # Ensure valid timestamps are entered
                            start_time = pd.to_datetime(start_time)
                            end_time = pd.to_datetime(end_time)

                            # Filter the high-resolution data
                            high_res_df = df[(df["Timestamp"] >= start_time) & (df["Timestamp"] <= end_time)]

                            if high_res_df.empty:
                                st.warning("No data points found in the selected range.")
                            else:
                                # Plot high-resolution data
                                high_res_fig = px.line(
                                    high_res_df, x="Timestamp", y=y_axis,
                                    title=f"{y_axis} Over Time (High Resolution)"
                                )
                                high_res_fig.update_layout(
                                    xaxis_title="Timestamp",
                                    yaxis_title=y_axis,
                                    template="plotly_white",
                                    height=600,
                                )
                                st.plotly_chart(high_res_fig, use_container_width=True)
                        except Exception as e:
                            st.error(f"An error occurred while generating the high-resolution plot: {e}")

                except Exception as e:
                    st.error(f"An error occurred while processing the RSK file: {e}")

                finally:
                    # Clean up the temporary file
                    if os.path.exists(temp_file_path):
                        try:
                            os.remove(temp_file_path)
                        except Exception as e:
                            st.warning(f"Failed to delete the temporary file: {e}")
        else:
            st.warning("No RSK files found for the selected core.")
    else:
        st.warning("No cores found in the database.")

# --- View Core Section Data Page ---
elif choice == "View Core Section Data":
    st.title("📊 View Core Section Data")

    with get_connection() as conn:
        # Fetch sections data
        query_sections = "SELECT core_id, section_number, section_length, top_cum_length, bottom_cum_length FROM sections ORDER BY core_id, section_number"
        sections_data = pd.read_sql(query_sections, conn)

        # Fetch core names and cruise information
        query_cores = "SELECT core_id, core_name, cruise FROM cores"
        cores_df = pd.read_sql(query_cores, conn)
        cores_map = cores_df.set_index('core_id')[['core_name', 'cruise']].to_dict(orient='index')

        # Replace core_id with core_name
        sections_data['core_name'] = sections_data['core_id'].map(lambda cid: cores_map.get(cid, {}).get('core_name', cid)).fillna(sections_data['core_id'])

        # Add cruise information using core_id for mapping
        sections_data['cruise'] = sections_data['core_id'].map(lambda cid: cores_map.get(cid, {}).get('cruise', '')).fillna('')

        # Reorder columns
        sections_data = sections_data[['core_name', 'section_number', 'section_length', 'top_cum_length', 'bottom_cum_length', 'cruise']]

    if not sections_data.empty:
        # Search Box
        search_cruise = st.text_input("Search by Cruise:", value="")
        if search_cruise:
            sections_data = sections_data[sections_data['cruise'].astype(str).str.contains(search_cruise, case=False)]

        st.dataframe(sections_data, use_container_width=True)

        st.download_button(
            label="Download Filtered Sections Data as CSV",
            data=sections_data.to_csv(index=False),
            file_name="sections_data_filtered_by_cruise.csv",
            mime="text/csv"
        )
    else:
        st.info("No section data available yet.")