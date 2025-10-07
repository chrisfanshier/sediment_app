import streamlit as st
import pandas as pd
import os
import json
from db_util import get_connection
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
def insert_winch_data(file_name, file_path, cruise, start_time, end_time, settings, notes):
    """Insert winch file metadata into database (no core association)"""
    with get_connection() as conn:
        query = text("""
            INSERT INTO winch_data (file_name, file_path, cruise, start_time, end_time, settings, notes)
            VALUES (:file_name, :file_path, :cruise, :start_time, :end_time, :settings, :notes)
        """)
        conn.execute(query, {
            "file_name": file_name,
            "file_path": file_path,
            "cruise": cruise or None,
            "start_time": start_time,
            "end_time": end_time,
            "settings": settings,
            "notes": notes or None
        })
        conn.commit()

# Main interface - no core selection needed
st.info("ℹ️ Winch data files contain continuous logging that may include multiple core operations or partial deployments.")

# Step 1: Cruise identification
cruise_name = st.text_input("Cruise Identifier", 
                           placeholder="e.g., SKQ202512S, RR2208",
                           help="Enter the cruise identifier for this winch data")

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
if uploaded_file is not None and cruise_name:
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
                    cruise_name,
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

elif uploaded_file is not None and not cruise_name:
    st.warning("Please enter a cruise identifier before processing the file.")

# Display current winch data summary
st.markdown("---")
st.subheader("📈 Current Winch Data Files")

try:
    with get_connection() as conn:
        # Get summary by cruise
        query = text("""
            SELECT 
                cruise,
                COUNT(*) as file_count,
                MIN(start_time) as earliest_data,
                MAX(end_time) as latest_data
            FROM winch_data 
            WHERE cruise IS NOT NULL
            GROUP BY cruise
            ORDER BY cruise
        """)
        
        winch_summary = pd.read_sql(query, conn)
        
        if not winch_summary.empty:
            st.write("**Winch Data by Cruise:**")
            
            for _, row in winch_summary.iterrows():
                with st.expander(f"🚢 {row['cruise']} ({row['file_count']} files)"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Earliest Data:** {row['earliest_data']}")
                    with col2:
                        st.write(f"**Latest Data:** {row['latest_data']}")
                    
                    # Get individual files for this cruise
                    file_query = text("""
                        SELECT file_name, start_time, end_time, notes
                        FROM winch_data 
                        WHERE cruise = :cruise
                        ORDER BY start_time
                    """)
                    cruise_files = pd.read_sql(file_query, conn, params={"cruise": row['cruise']})
                    
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