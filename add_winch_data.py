import os
import json
import pandas as pd
import streamlit as st
from sqlalchemy import text
from db_util import get_connection, fetch_cruise_options

# Predefined winch formats
WINCH_FORMATS = {
    "Custom Format": {
        "delimiter": ",",
        "header_lines": 0,
        "columns": [],
        "datetime_code": "pd.to_datetime(df[['year', 'month', 'day', 'hour', 'minute', 'second']])"
    },
    "Sikuliaq": {
        "delimiter": "\\s+",
        "header_lines": 0,
        "columns": ["year", "month", "day", "hour", "minute", "second", "Winch", "Winch Mode", "Wire_out", "Calc Tension", "Velocity", "Alarm", "Block Length", "Tension"],
        "datetime_code": "pd.to_datetime(df[['year', 'month', 'day', 'hour', 'minute', 'second']])"
    },
    "Armstrong": {
        "delimiter": ",",
        "header_lines": 0,
        "columns": ["timestamp", "offset_datetime", "tension", "speed", "payout", "kgTension?"],
        "datetime_code": "pd.to_datetime(df['timestamp'].str.extract(r'(\\d{4}/\\d{2}/\\d{2} \\d{2}:\\d{2}:\\d{2}\\.\\d{3})')[0])"
    },
    "Atlantis": {
        "delimiter": ",",
        "header_lines": 13,
        "columns": ["Date", "Time", "Winch Number", "Tension", "Tension Alarm", "Payout", "Payout Alarm", "Speed", "Speed Alarm", "Max Payout"],
        "datetime_code": "pd.to_datetime(df['Date'] + ' ' + df['Time'], errors='coerce')"
    }
}

def insert_winch_data(file_name, file_path, cruise_id, start_time, end_time, settings, notes=None):
    """Insert winch data metadata into the database"""
    with get_connection() as conn:
        query = text('''
            INSERT INTO winch_data (
                file_name, file_path, cruise_id, start_time, end_time, settings, notes
            ) VALUES (:file_name, :file_path, :cruise_id, :start_time, :end_time, :settings, :notes)
        ''')
        conn.execute(query, {
            "file_name": file_name,
            "file_path": file_path,
            "cruise_id": cruise_id,
            "start_time": start_time,
            "end_time": end_time,
            "settings": settings,
            "notes": notes
        })
        conn.commit()

def w_import():
    SAVE_DIR = "scripts/uploaded_files"
    os.makedirs(SAVE_DIR, exist_ok=True)

    st.title("🚢 Winch File Ingestion")

    # Step 1: Select cruise from database
    st.subheader("📋 Select Cruise")
    cruises = fetch_cruise_options()
    
    if not cruises:
        st.error("❌ No cruises found in database. Please add a cruise first.")
        return
    
    cruise_options = ["Select Cruise"] + [f"{cruise.cruise_name} - {cruise.vessel_name} (ID: {cruise.cruise_id})" for cruise in cruises]
    cruise_choice = st.selectbox("Choose a cruise*", cruise_options)
    
    if cruise_choice != "Select Cruise":
        # Extract cruise_id from selection
        cruise_id = int(cruise_choice.split("ID: ")[1].rstrip(")"))
        cruise_name = cruise_choice.split(" - ")[0]
        st.success(f"✅ Selected cruise: **{cruise_name}**")
    else:
        cruise_id = None
        cruise_name = None

    uploaded_file = st.file_uploader("Upload Winch File")  # accept any extension

    if uploaded_file is not None:
        # Format selection dropdown
        st.subheader("⚙️ File Format")
        format_choice = st.selectbox("Select Format", list(WINCH_FORMATS.keys()))
        selected_format = WINCH_FORMATS[format_choice]
        
        # Show format details
        if format_choice != "Custom Format":
            with st.expander(f"📋 {format_choice} Format Details"):
                st.json(selected_format)

        # Initialize settings from selected format
        header_lines = st.number_input("Number of header lines to skip", 
                                     min_value=0, 
                                     value=selected_format["header_lines"], 
                                     step=1)

        # Delimiter selection with format default
        delimiter_options = [
            ("Comma (,)", ","),
            ("Tab (\\t)", "\t"),
            ("Pipe (|)", "|"),
            ("Space ( )", " "),
            ("Semicolon (;)", ";"),
            ("Whitespace (\\s+)", r"\s+")
        ]
        
        # Find the default delimiter for the selected format
        format_delimiter = selected_format["delimiter"]
        default_idx = 0
        for i, (label, value) in enumerate(delimiter_options):
            if value == format_delimiter:
                default_idx = i
                break
        
        delimiter_label = st.selectbox("Select Delimiter", 
                                     [label for label, _ in delimiter_options],
                                     index=default_idx)
        delimiter = next(value for label, value in delimiter_options if label == delimiter_label)

        # Custom delimiter
        custom_delim = st.text_input("Custom delimiter (optional)", "")
        if custom_delim:
            delimiter = custom_delim

        # Preview raw data
        try:
            uploaded_file.seek(0)
            if delimiter == r"\s+":
                df_preview = pd.read_csv(uploaded_file, delim_whitespace=True, skiprows=header_lines, nrows=20, header=None)
            else:
                df_preview = pd.read_csv(uploaded_file, delimiter=delimiter, skiprows=header_lines, nrows=20, header=None)
            st.write("Raw Preview (first 20 rows):", df_preview)
        except Exception as e:
            st.error(f"Error reading file: {e}")
            return

        # Column renaming with format default
        st.subheader("Rename Columns")
        default_columns = str(selected_format["columns"]) if selected_format["columns"] else "[]"
        colnames_input = st.text_area(
            "Enter column names as a Python list (e.g., ['year', 'month', 'day', ...])",
            value=default_columns
        )
        try:
            colnames = eval(colnames_input)  # Convert string input to a Python list
            if len(colnames) != len(df_preview.columns):
                st.warning("The number of column names does not match the number of columns in the file.")
            else:
                df_preview.columns = colnames
                st.write("Preview with renamed columns:", df_preview)
        except Exception as e:
            st.error(f"Error parsing column names: {e}")

        # Datetime column creation with format default
        st.subheader("Create Datetime Column")
        st.markdown(
            "Use the DataFrame `df` in your code. For example:\n"
            "`pd.to_datetime(df[['year', 'month', 'day', 'hour', 'minute', 'second']])`"
        )
        datetime_code = st.text_area(
            "Enter the Python code for creating the datetime column",
            value=selected_format["datetime_code"]
        )

        # Test datetime creation
        try:
            if datetime_code.strip():
                # Read the entire dataset
                uploaded_file.seek(0)  # Reset file pointer
                if delimiter == r"\s+":
                    df = pd.read_csv(uploaded_file, delim_whitespace=True, skiprows=header_lines, names=colnames)
                else:
                    df = pd.read_csv(uploaded_file, delimiter=delimiter, skiprows=header_lines, names=colnames)

                # Validate and execute the user-provided code
                exec(f"df['datetime'] = {datetime_code}")
                st.write("Preview with datetime column (first 20 rows):", df.head())

                # Calculate start and end datetimes for the full dataset
                start_datetime = df['datetime'].min()
                end_datetime = df['datetime'].max()
                st.write(f"Start Datetime: {start_datetime}")
                st.write(f"End Datetime: {end_datetime}")
            else:
                start_datetime = None
                end_datetime = None
        except Exception as e:
            st.error(f"Error creating datetime column: {e}")
            start_datetime = None
            end_datetime = None

        # Optional notes
        notes = st.text_area("📝 Notes (Optional)", placeholder="Enter any notes about this winch data file")

        # Save file + metadata
        if st.button("Ingest File") and cruise_choice != "Select Cruise":
            if not colnames:
                st.error("❌ Please specify column names before saving")
            elif not datetime_code.strip():
                st.error("❌ Please specify datetime creation code before saving")
            elif start_datetime is None:
                st.error("❌ Please test datetime creation successfully before saving")
            else:
                try:
                    # Save file to uploaded_files directory
                    file_path = os.path.join(SAVE_DIR, uploaded_file.name)
                    with open(file_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())

                    # Prepare settings as JSON string
                    settings = json.dumps({
                        "delimiter": delimiter,
                        "header_lines": header_lines,
                        "columns": colnames,
                        "datetime_code": datetime_code,
                        "total_records": len(df),
                        "duration_hours": (end_datetime - start_datetime).total_seconds() / 3600
                    })

                    # Insert metadata into winch_data table using PostgreSQL
                    insert_winch_data(
                        uploaded_file.name,
                        SAVE_DIR,
                        cruise_id,
                        str(start_datetime),
                        str(end_datetime),
                        settings,
                        notes
                    )

                    st.success(f"✅ File and metadata saved!\n- File: {file_path}\n- Database: PostgreSQL sediment_cores")
                    st.write(f"**Cruise:** {cruise_name}")
                    st.write(f"**Records:** {len(df):,} data points")

                except Exception as e:
                    st.error(f"❌ Error saving file: {e}")
                    import traceback
                    st.code(traceback.format_exc())

        elif uploaded_file is not None and cruise_choice == "Select Cruise":
            st.warning("⚠️ Please select a cruise before saving the file.")

if __name__ == "__main__":
    w_import()

