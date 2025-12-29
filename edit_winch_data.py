import streamlit as st
import pandas as pd
import json
from db_util import get_connection, fetch_cruise_options, add_sync_tracking
from sqlalchemy import text
from config import WINCH_FORMATS

def edit_winch_data():
    st.title("✏️ Edit Winch Data Files")
    st.write("Select and edit existing winch data files.")
    
    # Fetch list of cruises
    cruises = fetch_cruise_options(only_created_on_ship=True)
    if not cruises:
        st.warning("No cruises found. Please add a cruise first.")
        return
    
    cruise_options = ["Select Cruise"] + [f"{cruise.cruise_name} - {cruise.vessel_name} (ID: {cruise.cruise_id})" for cruise in cruises]
    cruise_choice = st.selectbox("Choose a cruise", cruise_options)
    
    if cruise_choice == "Select Cruise":
        return
    
    # Extract cruise_id from selection
    cruise_id = int(cruise_choice.split("ID: ")[1].rstrip(")"))
    cruise_name = cruise_choice.split(" - ")[0]
    
    # Get winch files for selected cruise - FIXED COLUMN NAME
    with get_connection() as conn:
        winch_query = text("SELECT winch_file_id, file_name, start_time, end_time, settings, notes FROM winch_data WHERE cruise_id = :cruise_id")
        winch_files = pd.read_sql(winch_query, conn, params={"cruise_id": cruise_id})
    
    if winch_files.empty:
        st.info(f"No winch files found for cruise: {cruise_name}")
        return
    
    st.write(f"**Found {len(winch_files)} winch file(s) for {cruise_name}:**")
    
    # Create winch file options for selection
    winch_file_options = {}
    for _, row in winch_files.iterrows():
        # Parse settings to get some info for the label
        try:
            settings = json.loads(row['settings']) if row['settings'] else {}
            records = settings.get('total_records', 'Unknown')
            duration = settings.get('duration_hours', 0)
            duration_str = f"{duration:.1f}h" if duration else "Unknown"
        except:
            records = "Unknown"
            duration_str = "Unknown"
        
        label = f"🚢 {row['file_name']} ({records} records, {duration_str})"
        winch_file_options[label] = row['winch_file_id']  # FIXED COLUMN NAME
    
    # Select winch file to edit
    selected_winch_label = st.selectbox("Select Winch File to Edit", list(winch_file_options.keys()))
    winch_file_id = winch_file_options[selected_winch_label]  # FIXED VARIABLE NAME
    
    # Load and edit winch file data
    st.subheader("🚢 Edit Winch File")
    
    # Get current winch file data - FIXED COLUMN NAME
    with get_connection() as conn:
        query = text("SELECT * FROM winch_data WHERE winch_file_id = :winch_file_id")
        winch_data = conn.execute(query, {"winch_file_id": winch_file_id}).fetchone()
    
    if not winch_data:
        st.error("Winch file not found")
        return
    
    # Display current values
    st.write(f"**File Name:** {winch_data.file_name}")
    st.write(f"**File Path:** {winch_data.file_path}")
    st.write(f"**Start Time:** {winch_data.start_time}")
    st.write(f"**End Time:** {winch_data.end_time}")
    
    # Parse current settings
    try:
        current_settings = json.loads(winch_data.settings) if winch_data.settings else {}
    except:
        current_settings = {}
    
    # Show current format details
    with st.expander("📋 Current Format Details"):
        st.json(current_settings)
    
    # Allow editing of settings
    st.subheader("⚙️ Edit Format Settings")
    
    # Determine which format matches current settings (if any)
    current_format = "Custom Format"
    for format_name, format_config in WINCH_FORMATS.items():
        if (current_settings.get('delimiter') == format_config['delimiter'] and
            current_settings.get('header_lines') == format_config['header_lines'] and
            current_settings.get('columns') == format_config['columns']):
            current_format = format_name
            break
    
    # Format selection dropdown
    format_choice = st.selectbox("Select Format", list(WINCH_FORMATS.keys()), 
                               index=list(WINCH_FORMATS.keys()).index(current_format))
    selected_format = WINCH_FORMATS[format_choice]
    
    # Initialize settings from selected format or current values
    if format_choice != "Custom Format":
        default_delimiter = selected_format["delimiter"]
        default_header_lines = selected_format["header_lines"]
        default_columns = selected_format["columns"]
        default_datetime_code = selected_format["datetime_code"]
    else:
        default_delimiter = current_settings.get('delimiter', ',')
        default_header_lines = current_settings.get('header_lines', 0)
        default_columns = current_settings.get('columns', [])
        default_datetime_code = current_settings.get('datetime_code', 'pd.to_datetime(df[["year", "month", "day", "hour", "minute", "second"]])')
    
    # Editable settings
    new_header_lines = st.number_input("Number of header lines to skip", 
                                     min_value=0, 
                                     value=default_header_lines, 
                                     step=1)
    
    # Delimiter selection
    delimiter_options = [
        ("Comma (,)", ","),
        ("Tab (\\t)", "\t"),
        ("Pipe (|)", "|"),
        ("Space ( )", " "),
        ("Semicolon (;)", ";"),
        ("Whitespace (\\s+)", r"\s+")
    ]
    
    # Find current delimiter index
    default_idx = 0
    for i, (label, value) in enumerate(delimiter_options):
        if value == default_delimiter:
            default_idx = i
            break
    
    delimiter_label = st.selectbox("Select Delimiter", 
                                 [label for label, _ in delimiter_options],
                                 index=default_idx)
    new_delimiter = next(value for label, value in delimiter_options if label == delimiter_label)
    
    # Column names
    new_columns_input = st.text_area(
        "Column names (as Python list)",
        value=str(default_columns)
    )
    try:
        new_columns = eval(new_columns_input)
    except:
        st.error("Invalid column format. Please use a valid Python list.")
        new_columns = default_columns
    
    # Datetime code
    new_datetime_code = st.text_area(
        "Datetime creation code",
        value=default_datetime_code
    )
    
    # Notes (editable)
    new_notes = st.text_area("Notes", value=winch_data.notes or "", placeholder="Enter any notes about this winch data file")
    
    # Update button
    if st.button("Update Winch File"):
        try:
            # Prepare updated settings
            updated_settings = json.dumps({
                "delimiter": new_delimiter,
                "header_lines": new_header_lines,
                "columns": new_columns,
                "datetime_code": new_datetime_code,
                "total_records": current_settings.get('total_records', 0),
                "duration_hours": current_settings.get('duration_hours', 0)
            })
            
            with get_connection() as conn:
                values = {
                    "settings": updated_settings,
                    "notes": new_notes or None,
                    "winch_file_id": winch_file_id
                }
                
                # Add sync tracking
                values = add_sync_tracking(values, is_update=True)
                
                update_query = text("""
                    UPDATE winch_data 
                    SET settings = :settings, notes = :notes, sync_status = :sync_status
                    WHERE winch_file_id = :winch_file_id
                """)
                conn.execute(update_query, values)
                conn.commit()
            st.success("Winch file updated successfully!")
            st.rerun()
        except Exception as e:
            st.error(f"Error updating winch file: {e}")

if __name__ == "__main__":
    edit_winch_data()