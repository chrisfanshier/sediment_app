import streamlit as st
import pandas as pd
import os
import json
from db_util import get_connection
from db_util import fetch_cruise_options  # Add this import
from sqlalchemy import text
from config import ROOT_DIRECTORY

# Custom CSS to reduce blank space
st.markdown(
    """
    <style>
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

st.title("🔧 Add Winch Data File")
st.write("Upload and manage winch logging files by cruise. Winch files contain continuous logging data that may span multiple core deployments.")

# Define winch formats with their processing parameters
WINCH_FORMATS = {
    "Standard Winch Format": {
        "delimiter": ",",
        "header_lines": 1,
        "columns": ['datetime', 'depth', 'tension', 'speed', 'wire_out'],
        "datetime_code": "pd.to_datetime(df['datetime'])"
    },
    "Legacy Winch Format": {
        "delimiter": "\t",
        "header_lines": 2,
        "columns": ['year', 'month', 'day', 'hour', 'minute', 'second', 'depth', 'tension', 'speed'],
        "datetime_code": "pd.to_datetime(df[['year', 'month', 'day', 'hour', 'minute', 'second']])"
    },
    "Custom Winch Format A": {
        "delimiter": ",",
        "header_lines": 0,
        "columns": ['timestamp', 'wire_length', 'load', 'velocity', 'notes'],
        "datetime_code": "pd.to_datetime(df['timestamp'])"
    },
    "Custom Winch Format B": {
        "delimiter": "|",
        "header_lines": 3,
        "columns": ['date_time', 'position', 'tension_kg', 'speed_ms', 'operator'],
        "datetime_code": "pd.to_datetime(df['date_time'])"
    }
}

# Define the upload function for winch data
def upload_winch_file(file):
    """Upload winch file to flat winch_data directory"""
    # Create winch data directory if it doesn't exist
    upload_dir = os.path.join(ROOT_DIRECTORY, "winch_data")
    os.makedirs(upload_dir, exist_ok=True)
    
    # Save the file with original name
    file_path = os.path.join(upload_dir, file.name)
    with open(file_path, "wb") as f:
        f.write(file.getbuffer())
    
    return "winch_data"  # Return relative path

# Function to insert winch data into database
def insert_winch_data(file_name, file_path, cruise_id, start_time, end_time, settings, notes):
    """Insert winch file metadata into database using cruise_id"""
    with get_connection() as conn:
        query = text("""
            INSERT INTO winch_data (file_name, file_path, cruise_id, start_time, end_time, settings, notes)
            VALUES (:file_name, :file_path, :cruise_id, :start_time, :end_time, :settings, :notes)
        """)
        conn.execute(query, {
            "file_name": file_name,
            "file_path": file_path,
            "cruise_id": cruise_id,
            "start_time": start_time,
            "end_time": end_time,
            "settings": settings,
            "notes": notes or None
        })
        conn.commit()

# Main interface - no core selection needed
st.info("ℹ️ Winch data files contain continuous logging that may include multiple core operations or partial deployments.")

# Step 1: Cruise selection
st.subheader("Cruise Selection")

# Fetch cruise options
cruises = fetch_cruise_options()

# Create cruise options for dropdown
cruise_options = {}
if cruises:
    for cruise in cruises:
        cruise_id, cruise_name, vessel_name, vessel_id = cruise
        display_name = f"{cruise_name} ({vessel_name})" if vessel_name else cruise_name
        cruise_options[display_name] = cruise_id

# Cruise selection dropdown
cruise_choice = st.selectbox(
    "Select Cruise*",
    ["Select Cruise"] + list(cruise_options.keys()),
    help="Select the cruise this winch data belongs to"
)

if cruise_choice == "Select Cruise":
    cruise_id = None
    cruise_name = None
    vessel_name = "No cruise selected"
    st.info("Please select a cruise to continue.")
else:
    cruise_id = cruise_options[cruise_choice]
    cruise_name = cruise_choice.split(" (")[0]  # Extract cruise name without vessel
    
    # Get vessel info for display
    vessel_info = next((c for c in cruises if c[0] == cruise_id), None)
    vessel_name = vessel_info[2] if vessel_info and vessel_info[2] else "Unknown vessel"
    
    # Display auto-populated vessel info
    st.success(f"**Vessel:** {vessel_name} (from selected cruise)")

# Step 2: Winch format selection
winch_format = st.selectbox("Select Winch Data Format", list(WINCH_FORMATS.keys()))
selected_format = WINCH_FORMATS[winch_format]

# Display format details
st.info(f"""
**Format Details for {winch_format}:**
- Delimiter: `{selected_format['delimiter']}`
- Header lines to skip: {selected_format['header_lines']}
- Expected columns: {', '.join(selected_format['columns'])}
""")

# Step 3: File upload
uploaded_file = st.file_uploader("Upload Winch Data File", 
                               type=["csv", "txt", "dat", "log"],
                               key="winch_uploader")

# Step 4: Additional metadata
notes = st.text_area("Notes", 
                    placeholder="Enter notes about this winch logging session (e.g., equipment issues, time periods covered, etc.)...")

# Step 5: Process file if uploaded
if uploaded_file is not None and cruise_choice != "Select Cruise":
    try:
        # Preview the file with selected format
        st.subheader("📋 File Preview")
        
        format_config = selected_format
        df_preview = pd.read_csv(
            uploaded_file, 
            delimiter=format_config['delimiter'], 
            skiprows=format_config['header_lines'], 
            nrows=10,
            names=format_config['columns']
        )
        st.write("Preview (first 10 rows):", df_preview)

        # Try to create datetime column for time range calculation
        uploaded_file.seek(0)  # Reset file pointer
        df_full = pd.read_csv(
            uploaded_file,
            delimiter=format_config['delimiter'],
            skiprows=format_config['header_lines'],
            names=format_config['columns']
        )

        # Execute datetime creation code
        datetime_code = format_config['datetime_code']
        exec(f"df_full['datetime'] = {datetime_code}")
        
        # Calculate start and end times
        start_datetime = df_full['datetime'].min()
        end_datetime = df_full['datetime'].max()
        duration_hours = (end_datetime - start_datetime).total_seconds() / 3600
        
        st.write(f"**Data Time Range:**")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.write(f"**Start:** {start_datetime}")
        with col2:
            st.write(f"**End:** {end_datetime}")
        with col3:
            st.write(f"**Duration:** {duration_hours:.1f} hours")

        # Step 6: Save file and metadata
        if st.button("Save Winch Data File"):
            with st.spinner(f"Processing winch file '{uploaded_file.name}'..."):
                # Upload file
                uploaded_file_path = upload_winch_file(uploaded_file)
                
                # Prepare settings as JSON
                settings = json.dumps({
                    "format": winch_format,
                    "delimiter": format_config['delimiter'],
                    "header_lines": format_config['header_lines'],
                    "columns": format_config['columns'],
                    "datetime_code": format_config['datetime_code'],
                    "total_records": len(df_full),
                    "duration_hours": duration_hours
                })
                
                # Insert into database
                insert_winch_data(
                    uploaded_file.name,
                    uploaded_file_path,
                    cruise_id,  # Use cruise_id instead of cruise_name
                    str(start_datetime),
                    str(end_datetime),
                    settings,
                    notes
                )
                
                st.success(f"Winch file '{uploaded_file.name}' saved successfully!")
                st.write(f"**File saved at:** `{os.path.join(ROOT_DIRECTORY, uploaded_file_path, uploaded_file.name)}`")
                st.write(f"**Cruise:** {cruise_name}")
                st.write(f"**Time Range:** {start_datetime} to {end_datetime}")
                st.write(f"**Records:** {len(df_full):,} data points")

    except Exception as e:
        st.error(f"Error processing winch file: {e}")
        st.write("Please check that the selected format matches your file structure.")

elif uploaded_file is not None and cruise_choice == "Select Cruise":
    st.warning("Please select a cruise before processing the file.")

# Display current winch data summary
st.markdown("---")
st.subheader("📈 Current Winch Data Files")

try:
    with get_connection() as conn:
        # Get summary by cruise with cruise and vessel names
        query = text("""
            SELECT 
                cr.cruise_name,
                v.vessel_name,
                COUNT(*) as file_count,
                MIN(wd.start_time) as earliest_data,
                MAX(wd.end_time) as latest_data
            FROM winch_data wd
            LEFT JOIN cruises cr ON wd.cruise_id = cr.cruise_id
            LEFT JOIN vessels v ON cr.vessel_id = v.vessel_id
            WHERE wd.cruise_id IS NOT NULL
            GROUP BY cr.cruise_name, v.vessel_name
            ORDER BY cr.cruise_name
        """)
        
        winch_summary = pd.read_sql(query, conn)
        
        if not winch_summary.empty:
            st.write("**Winch Data by Cruise:**")
            
            for _, row in winch_summary.iterrows():
                vessel_info = f" - {row['vessel_name']}" if row['vessel_name'] else ""
                with st.expander(f"🚢 {row['cruise_name']}{vessel_info} ({row['file_count']} files)"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Earliest Data:** {row['earliest_data']}")
                    with col2:
                        st.write(f"**Latest Data:** {row['latest_data']}")
                    
                    # Get individual files for this cruise
                    file_query = text("""
                        SELECT wd.file_name, wd.start_time, wd.end_time, wd.notes
                        FROM winch_data wd
                        JOIN cruises cr ON wd.cruise_id = cr.cruise_id
                        WHERE cr.cruise_name = :cruise_name
                        ORDER BY wd.start_time
                    """)
                    cruise_files = pd.read_sql(file_query, conn, params={"cruise_name": row['cruise_name']})
                    
                    for _, file_row in cruise_files.iterrows():
                        st.write(f"📄 **{file_row['file_name']}**")
                        st.write(f"   ⏰ {file_row['start_time']} → {file_row['end_time']}")
                        if file_row['notes']:
                            st.write(f"   📝 {file_row['notes']}")
        else:
            st.info("No winch data files uploaded yet.")
            
        # Total count
        total_query = text("SELECT COUNT(*) FROM winch_data")
        total_count = conn.execute(total_query).scalar()
        st.metric("Total Winch Files", total_count)
        
except Exception as e:
    st.error(f"Error fetching winch data summary: {e}")

# Quick access
st.markdown("---")
if st.button("📂 Open Winch Data Folder"):
    winch_folder = os.path.join(ROOT_DIRECTORY, "winch_data")
    if os.path.exists(winch_folder):
        os.startfile(winch_folder)
    else:
        st.error("Winch data folder not found")