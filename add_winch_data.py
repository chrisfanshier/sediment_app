import streamlit as st
import pandas as pd
import os
import json
from db_util import get_connection, fetch_cores
from sqlalchemy import text
from config import ROOT_DIRECTORY, SUBDIRECTORIES, get_full_path

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
st.write("Upload and manage winch data files associated with cores.")

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
def upload_winch_file(file, cruise_name):
    # Create winch data subdirectory if it doesn't exist
    winch_subdir = "winch_data"
    upload_dir = os.path.join(ROOT_DIRECTORY, winch_subdir)
    os.makedirs(upload_dir, exist_ok=True)
    
    # Save the file
    file_path = os.path.join(upload_dir, file.name)
    with open(file_path, "wb") as f:
        f.write(file.getbuffer())
    
    return winch_subdir

# Function to insert winch data into database
def insert_winch_data(core_id, file_name, file_path, cruise, start_time, end_time, settings, notes):
    with get_connection() as conn:
        query = text("""
            INSERT INTO winch_data (core_id, file_name, file_path, cruise, start_time, end_time, settings, notes)
            VALUES (:core_id, :file_name, :file_path, :cruise, :start_time, :end_time, :settings, :notes)
        """)
        conn.execute(query, {
            "core_id": core_id,
            "file_name": file_name,
            "file_path": file_path,
            "cruise": cruise or None,
            "start_time": start_time,
            "end_time": end_time,
            "settings": settings,
            "notes": notes or None
        })
        conn.commit()

# Fetch list of cores
cores = fetch_cores()
if cores.empty:
    st.warning("No cores found. Please add cores first.")
else:
    core_options = {f"{name} (ID: {id})": id for id, name in zip(cores['core_id'], cores['core_name'])}

    # Step 1: Select Core
    selected_core_label = st.selectbox("Select Core to Associate Winch Data With", list(core_options.keys()))
    selected_core_id = core_options[selected_core_label]

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
    cruise_name = st.text_input("Cruise Name", placeholder="Enter cruise identifier...")
    notes = st.text_area("Notes", placeholder="Enter any notes about this winch data file...")

    # Step 5: Process file if uploaded
    if uploaded_file is not None:
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
            
            st.write(f"**Data Time Range:**")
            st.write(f"- Start: {start_datetime}")
            st.write(f"- End: {end_datetime}")

            # Step 6: Save file and metadata
            if st.button("Save Winch Data File"):
                with st.spinner(f"Processing winch file '{uploaded_file.name}'..."):
                    # Upload file
                    uploaded_file_path = upload_winch_file(uploaded_file, cruise_name)
                    
                    # Prepare settings as JSON
                    settings = json.dumps({
                        "format": winch_format,
                        "delimiter": format_config['delimiter'],
                        "header_lines": format_config['header_lines'],
                        "columns": format_config['columns'],
                        "datetime_code": format_config['datetime_code']
                    })
                    
                    # Insert into database
                    insert_winch_data(
                        selected_core_id,
                        uploaded_file.name,
                        uploaded_file_path,
                        cruise_name,
                        str(start_datetime),
                        str(end_datetime),
                        settings,
                        notes
                    )
                    
                    st.success(f"Winch file '{uploaded_file.name}' saved successfully!")
                    st.write(f"File saved at: {uploaded_file_path}")
                    st.write(f"Associated with core: {selected_core_label}")
                    st.write(f"Format used: {winch_format}")

        except Exception as e:
            st.error(f"Error processing winch file: {e}")
            st.write("Please check that the selected format matches your file structure.")

# Display current winch data count
st.markdown("---")
st.subheader("📈 Current Winch Data Files")

try:
    with get_connection() as conn:
        winch_count = conn.execute(text("SELECT COUNT(*) FROM winch_data")).scalar()
        st.metric("Total Winch Files", winch_count)
except Exception as e:
    st.error(f"Error fetching winch file count: {e}")