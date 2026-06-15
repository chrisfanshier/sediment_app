import streamlit as st
import pandas as pd
import os
import json
from db_util import get_connection, fetch_cores, fetch_cruise_options, add_sync_tracking, insert_usbl_file, insert_core_media, update_core_media_association, fetch_core_media_registered, fetch_capture_devices
from sqlalchemy import text
from config import ROOT_DIRECTORY, SUBDIRECTORIES, get_full_path, WINCH_FORMATS
from utils import parse_usbl_first_last

# --- Add Manage Files Page ---
st.title("📂 Manage Associated Data Files")
st.write("You can upload and manage files related to sediment cores and winch data here.")

# Define the upload_file function
def upload_file(file, file_type):
    # Get the subdirectory for the selected file type
    subdirectory = SUBDIRECTORIES.get(file_type)
    if not subdirectory:
        raise ValueError(f"Unknown file type: {file_type}")

    # Construct the full directory path
    upload_dir = os.path.join(ROOT_DIRECTORY, subdirectory)

    # Ensure the directory exists
    os.makedirs(upload_dir, exist_ok=True)

    # Save the file to the appropriate directory
    file_path = os.path.join(upload_dir, file.name)
    with open(file_path, "wb") as f:
        f.write(file.getbuffer())

    # Return only the relative directory (not the full path)
    return subdirectory

# ── Media file extension sets ─────────────────────────────────────────────────
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp",
                    ".heic", ".heif", ".raw", ".arw", ".cr2", ".nef", ".dng"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".mts", ".m2ts",
                    ".mpg", ".mpeg", ".wmv", ".lrv", ".360"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

def get_media_type(filename):
    """Detect image or video from file extension."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    elif ext in VIDEO_EXTENSIONS:
        return "video"
    return None

# convert pandas Timestamp / datetime-like to timezone-aware Python datetime (UTC)
def _to_utc_py(dt):
    if dt is None:
        return None
    ts = pd.to_datetime(dt)
    # pandas Timestamp has .tz; localize if naive, else convert
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.to_pydatetime()

# Define the insert functions for specialized tables
def insert_mscl_file(core_id, file_name, file_path, file_type, remarks):
    with get_connection() as conn:
        values = {
            "core_id": core_id,
            "file_name": file_name,
            "file_path": file_path,
            "file_type": file_type,
            "remarks": remarks or None
        }
        # Add sync tracking
        values = add_sync_tracking(values)
        
        query = text("""
            INSERT INTO mscl_files (core_id, file_name, file_path, file_type, remarks, created_on_ship, sync_status)
            VALUES (:core_id, :file_name, :file_path, :file_type, :remarks, :created_on_ship, :sync_status)
        """)
        conn.execute(query, values)
        conn.commit()

def insert_sensor_file(core_id, file_name, file_path, file_type, sensor_location, sensor_type, remarks):
    with get_connection() as conn:
        values = {
            "core_id": core_id,
            "file_name": file_name,
            "file_path": file_path,
            "file_type": file_type,
            "sensor_location": sensor_location or None,
            "sensor_type": sensor_type or None,
            "remarks": remarks or None
        }
        # Add sync tracking
        values = add_sync_tracking(values)
        
        query = text("""
            INSERT INTO sensor_files (core_id, file_name, file_path, file_type, sensor_location, sensor_type, remarks, created_on_ship, sync_status)
            VALUES (:core_id, :file_name, :file_path, :file_type, :sensor_location, :sensor_type, :remarks, :created_on_ship, :sync_status)
        """)
        conn.execute(query, values)
        conn.commit()

def insert_winch_data(file_name, file_path, cruise_id, start_time, end_time, settings, notes=None):
    """Insert winch data metadata into the database"""
    with get_connection() as conn:
        values = {
            "file_name": file_name,
            "file_path": file_path,
            "cruise_id": cruise_id,
            "start_time": start_time,
            "end_time": end_time,
            "settings": settings,
            "notes": notes
        }
        # Add sync tracking
        values = add_sync_tracking(values)
        
        query = text('''
            INSERT INTO winch_data (
                file_name, file_path, cruise_id, start_time, end_time, settings, notes, created_on_ship, sync_status
            ) VALUES (:file_name, :file_path, :cruise_id, :start_time, :end_time, :settings, :notes, :created_on_ship, :sync_status)
        ''')
        conn.execute(query, values)
        conn.commit()

# Step 1: Select file category first
file_category = st.selectbox("Select File Category", ["MSCL Data", "Sensor Data", "Winch Data", "USBL Data", "Photos & Video"])

if file_category in ["MSCL Data", "Sensor Data"]:
    # For core-related files, fetch and select core
    cores = fetch_cores(only_created_on_ship=True)
    if cores.empty:
        st.warning("No cores found. Please add cores first.")
        st.stop()
    
    core_options = {f"{name} (ID: {id})": id for id, name in zip(cores['core_id'], cores['core_name'])}
    selected_core_label = st.selectbox("Select Core to Associate File With", list(core_options.keys()))
    selected_core_id = core_options[selected_core_label]

elif file_category == "Winch Data":
    # For winch files, fetch and select cruise
    cruises = fetch_cruise_options(only_created_on_ship=True)
    if not cruises:
        st.warning("No cruises found. Please add a cruise first.")
        st.stop()
    
    cruise_options = ["Select Cruise"] + [f"{cruise.cruise_name} - {cruise.vessel_name} (ID: {cruise.cruise_id})" for cruise in cruises]
    cruise_choice = st.selectbox("Choose a cruise*", cruise_options)
    
    if cruise_choice != "Select Cruise":
        cruise_id = int(cruise_choice.split("ID: ")[1].rstrip(")"))
        cruise_name = cruise_choice.split(" - ")[0]
        st.success(f"✅ Selected cruise: **{cruise_name}**")
    else:
        st.warning("Please select a cruise to continue.")
        st.stop()

# File processing based on category
if file_category == "MSCL Data":
    st.subheader("📊 MSCL Data File")
    
    file_type = "MSCL Data"
    uploaded_file = st.file_uploader("Upload MSCL Data File", key="mscl_uploader")
    remarks = st.text_area("MSCL Remarks", placeholder="Enter MSCL-specific remarks...")
    
    if uploaded_file is not None:
        if st.button("Save MSCL File"):
            with st.spinner(f"Processing MSCL file '{uploaded_file.name}'..."):
                uploaded_file_path = upload_file(uploaded_file, "MSCL Data")
                insert_mscl_file(selected_core_id, uploaded_file.name, uploaded_file_path, file_type, remarks)
                st.success(f"MSCL file '{uploaded_file.name}' saved successfully!")

elif file_category == "Sensor Data":
    st.subheader("🌡️ Sensor Data File")
    
    file_type = st.selectbox("Sensor Brand", ["RBR Sensor", "Star-Oddi Sensor"])
    
    if file_type == "RBR Sensor":
        file_extensions = ["rsk"]
    elif file_type == "Star-Oddi Sensor":
        file_extensions = ["dat", "acc", "txt", "csv"]
    
    sensor_location_options = [
        "Weight Stand",
        "Release Device", 
        "Trigger Core/Weight",
        "Other Location"
    ]
    sensor_location = st.selectbox("Sensor Location", ["Select Location..."] + sensor_location_options)
    if sensor_location == "Select Location...":
        sensor_location = None
    elif sensor_location == "Other Location":
        sensor_location = st.text_input("Specify Other Location")

    st.write("**Sensor Measurements (select all that apply):**")
    measurements = {
        "Temperature": st.checkbox("Temperature"),
        "Depth/Pressure": st.checkbox("Depth/Pressure"),
        "Acceleration": st.checkbox("Acceleration"),
        "Tilt": st.checkbox("Tilt")
    }
    
    selected_measurements = [measurement for measurement, selected in measurements.items() if selected]
    sensor_type = ", ".join(selected_measurements) if selected_measurements else None
    
    uploaded_file = st.file_uploader("Upload Sensor Data File", type=file_extensions, key="sensor_uploader")
    remarks = st.text_area("Sensor Remarks", placeholder="Enter sensor-specific remarks...")
    
    missing_fields = []
    if not sensor_location:
        missing_fields.append("Sensor Location")
    if not selected_measurements:
        missing_fields.append("Sensor Measurements")
    
    if uploaded_file is not None:
        if missing_fields:
            st.warning(f"Please complete the following fields: {', '.join(missing_fields)}")
        else:
            if st.button("Save Sensor File"):
                with st.spinner(f"Processing sensor file '{uploaded_file.name}'..."):
                    uploaded_file_path = upload_file(uploaded_file, file_type)
                    insert_sensor_file(
                        selected_core_id, 
                        uploaded_file.name, 
                        uploaded_file_path, 
                        file_type,
                        sensor_location, 
                        sensor_type,
                        remarks
                    )
                    st.success(f"Sensor file '{uploaded_file.name}' saved successfully!")

elif file_category == "Winch Data":
    st.subheader("🚢 Winch Data File")
    
    uploaded_file = st.file_uploader("Upload Winch File")

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
                df_preview = pd.read_csv(uploaded_file, sep='\s+', skiprows=header_lines, nrows=20, header=None)
            else:
                df_preview = pd.read_csv(
                    uploaded_file,
                    delimiter=delimiter,
                    skiprows=header_lines,
                    nrows=20,
                    header=None,
                    on_bad_lines='skip',
                    encoding='utf-8'
                )
            st.write("Raw Preview (first 20 rows):", df_preview)
        except Exception as e:
            st.error(f"Error reading file: {e}")
            st.stop()

        # Column renaming with format default
        st.subheader("Rename Columns")
        default_columns = str(selected_format["columns"]) if selected_format["columns"] else "[]"
        colnames_input = st.text_area(
            "Enter column names as a Python list (e.g., ['year', 'month', 'day', ...])",
            value=default_columns
        )
        try:
            colnames = eval(colnames_input)
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
                uploaded_file.seek(0)
                if delimiter == r"\s+":
                    df = pd.read_csv(uploaded_file, sep='\s+', skiprows=header_lines, names=colnames, low_memory=False)
                else:
                    df = pd.read_csv(
                        uploaded_file,
                        delimiter=delimiter,
                        skiprows=header_lines,
                        names=colnames,
                        low_memory=False,
                        on_bad_lines='skip',
                        encoding='utf-8'
                    )

                # Execute datetime creation
                exec(f"df['datetime'] = {datetime_code}")
                
                # Convert numeric columns if specified in format
                if "numeric_columns" in selected_format:
                    numeric_cols = selected_format["numeric_columns"]
                    for col in numeric_cols:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col].astype(str).str.strip(), errors='coerce')
                            st.info(f"✅ Converted '{col}' to numeric")
                
                st.write("Preview with datetime column (first 20 rows):", df.head())

                # Calculate time range
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

        # Save winch file + metadata
        if st.button("Save Winch File"):
            if not colnames:
                st.error("❌ Please specify column names before saving")
            elif not datetime_code.strip():
                st.error("❌ Please specify datetime creation code before saving")
            elif start_datetime is None:
                st.error("❌ Please test datetime creation successfully before saving")
            else:
                try:
                    with st.spinner(f"Processing winch file '{uploaded_file.name}'..."):
                        # Save file using the same pattern as other files
                        uploaded_file_path = upload_file(uploaded_file, "Winch Data")

                        # Prepare settings as JSON - include numeric_columns from format
                        settings_dict = {
                            "delimiter": delimiter,
                            "header_lines": header_lines,
                            "columns": colnames,
                            "datetime_code": datetime_code,
                            "total_records": len(df),
                            "duration_hours": (end_datetime - start_datetime).total_seconds() / 3600
                        }
                        
                        # Add numeric_columns if present in selected format
                        if "numeric_columns" in selected_format:
                            settings_dict["numeric_columns"] = selected_format["numeric_columns"]
                        
                        settings = json.dumps(settings_dict)

                        # Insert metadata
                        insert_winch_data(
                            uploaded_file.name,
                            uploaded_file_path,
                            cruise_id,
                            str(start_datetime),
                            str(end_datetime),
                            settings,
                            notes
                        )

                        st.success(f"✅ Winch file '{uploaded_file.name}' saved successfully!")
                        st.write(f"**File saved to:** `{os.path.join(ROOT_DIRECTORY, uploaded_file_path, uploaded_file.name)}`")
                        st.write(f"**Cruise:** {cruise_name}")
                        st.write(f"**Records:** {len(df):,} data points")

                except Exception as e:
                    st.error(f"❌ Error saving file: {e}")
                    import traceback
                    st.code(traceback.format_exc())

elif file_category == "USBL Data":
    st.subheader("📡 USBL Data File")

    # Choose cruise (foreign key) — same pattern as Winch
    cruises = fetch_cruise_options(only_created_on_ship=True)
    if not cruises:
        st.warning("No cruises found. Please add a cruise first.")
        st.stop()

    cruise_options = ["Select Cruise"] + [f"{r[1]} - {r[2]} (ID: {r[0]})" for r in cruises]
    cruise_choice = st.selectbox("Choose a cruise*", cruise_options, key="usbl_cruise")

    if cruise_choice != "Select Cruise":
        cruise_id = int(cruise_choice.split("ID: ")[1].rstrip(")"))
        cruise_name = cruise_choice.split(" - ")[0]
        st.success(f"✅ Selected cruise: **{cruise_name}**")
    else:
        st.warning("Please select a cruise to continue.")
        st.stop()

    sampling_device = st.text_input("Sampling Device (e.g., dredge, multicore, etc)")
    transponder_type = st.text_input("Transponder Type (e.g., Ranger2, etc)")
    remarks = st.text_area("Remarks (optional)", placeholder="Enter any remarks about this USBL file")

    uploaded_files = st.file_uploader("Upload USBL File(s)", type=["csv", "txt", "usbl"], accept_multiple_files=True, key="usbl_uploader")

    if uploaded_files:
        # --- Compute start/end times for each uploaded file and show to user before saving ---
        usbl_rows = []
        for f in uploaded_files:
            try:
                stem = os.path.splitext(f.name)[0]
                parts = stem.split("_")
                date_str = parts[1] if len(parts) > 1 else None

                # Primary: parse first/last timestamps from file (handles midnight rollover)
                f.seek(0)
                start_dt, end_dt = parse_usbl_first_last(f, f.name)

                # Fallback: previous per-line datetime parsing using csv column if helper fails
                if start_dt is None or end_dt is None:
                    f.seek(0)
                    df_times = pd.read_csv(
                        f,
                        header=None,
                        usecols=[1],
                        names=["utc_time"],
                        dtype=str,
                        on_bad_lines='skip'
                    )

                    if date_str:
                        dt_series = pd.to_datetime(
                            date_str + " " + df_times["utc_time"].astype(str),
                            format="%Y%m%d %H%M%S.%f",
                            utc=True,
                            errors="coerce"
                        )
                        if dt_series.isna().all():
                            dt_series = pd.to_datetime(
                                date_str + " " + df_times["utc_time"].astype(str),
                                format="%Y%m%d %H%M%S",
                                utc=True,
                                errors="coerce"
                            )
                    else:
                        dt_series = pd.to_datetime(df_times["utc_time"].astype(str), utc=True, errors="coerce")

                    if dt_series.dropna().empty:
                        start_dt = None
                        end_dt = None
                    else:
                        start_dt = dt_series.min()
                        end_dt = dt_series.max()
            except Exception:
                start_dt = None
                end_dt = None
            finally:
                try:
                    f.seek(0)
                except Exception:
                    pass

            usbl_rows.append({
                "file_obj": f,
                "file_name": f.name,
                # keep pandas.Timestamp (or None); convert to Python datetime when inserting
                "start_time": start_dt,
                "end_time": end_dt
            })

        # show preview of detected times
        preview_df = pd.DataFrame([
            {
                "file_name": r["file_name"],
                "start_time": (r["start_time"].isoformat() if r["start_time"] is not None else None),
                "end_time": (r["end_time"].isoformat() if r["end_time"] is not None else None)
            } for r in usbl_rows
        ])
        st.write("Detected start/end times from uploaded USBL files:")
        st.table(preview_df)

        # allow user to save after previewing computed times
        if st.button("Save USBL File(s)"):
             try:
                 with st.spinner(f"Processing {len(usbl_rows)} USBL file(s)..."):
                     saved = []
                     for r in usbl_rows:
                         f = r["file_obj"]
                         uploaded_file_path = upload_file(f, "USBL Data")
                         insert_usbl_file(
                             cruise_id=cruise_id,
                             file_name=r["file_name"],
                             file_path=uploaded_file_path,
                             sampling_device=sampling_device,
                             transponder_type=transponder_type,
                             remarks=remarks,
                             start_time=_to_utc_py(r["start_time"]),
                             end_time=_to_utc_py(r["end_time"])
                         )
                         saved.append(os.path.join(ROOT_DIRECTORY, uploaded_file_path, r["file_name"]))
                     st.success(f"Saved {len(saved)} USBL file(s) successfully!")
                     for p in saved:
                         st.write(f"- {p}")
             except Exception as e:
                 st.error(f"Error saving USBL file(s): {e}")

elif file_category == "Photos & Video":
    st.subheader("📷 Photos & Video")

    default_scan_dir = os.path.join(ROOT_DIRECTORY, SUBDIRECTORIES.get("Photos & Video", "core_media"))
    scan_dir_input = st.text_input(
        "Directory to scan",
        value=default_scan_dir,
        help="Defaults to the core_media directory. Change to scan a different folder."
    )

    if st.button("🔍 Scan for Files"):
        if not os.path.isdir(scan_dir_input):
            st.error(f"Directory not found: {scan_dir_input}")
        else:
            found_files = []
            for fname in sorted(os.listdir(scan_dir_input)):
                ext = os.path.splitext(fname)[1].lower()
                if ext in MEDIA_EXTENSIONS:
                    fpath = os.path.join(scan_dir_input, fname)
                    found_files.append({
                        "file_name": fname,
                        "full_path": fpath,
                        "file_size_bytes": os.path.getsize(fpath),
                        "media_type": get_media_type(fname)
                    })

            try:
                scan_dir_relative = os.path.relpath(scan_dir_input, ROOT_DIRECTORY)
            except ValueError:
                scan_dir_relative = scan_dir_input

            registered = fetch_core_media_registered(scan_dir_relative)

            st.session_state["media_scan_results"] = found_files
            st.session_state["media_registered"] = registered
            st.session_state["media_scan_dir_relative"] = scan_dir_relative

            if "media_core_assignments" not in st.session_state:
                st.session_state["media_core_assignments"] = {}
            if "media_device_assignments" not in st.session_state:
                st.session_state["media_device_assignments"] = {}
            if "media_remarks_assignments" not in st.session_state:
                st.session_state["media_remarks_assignments"] = {}

            for f in found_files:
                fname = f["file_name"]
                if fname in registered:
                    if fname not in st.session_state["media_core_assignments"]:
                        st.session_state["media_core_assignments"][fname] = registered[fname]["core_id"]
                    if fname not in st.session_state["media_device_assignments"]:
                        st.session_state["media_device_assignments"][fname] = registered[fname]["capture_device_id"]
                    if fname not in st.session_state["media_remarks_assignments"]:
                        st.session_state["media_remarks_assignments"][fname] = registered[fname]["remarks"] or ""

            if not found_files:
                st.warning("No image or video files found in that directory.")
            else:
                st.success(f"Found {len(found_files)} file(s) — {len(registered)} already registered.")

    if st.session_state.get("media_scan_results"):
        found_files = st.session_state["media_scan_results"]
        registered  = st.session_state["media_registered"]

        cores = fetch_cores(only_created_on_ship=True)
        core_options_map    = {f"{name} (ID: {id})": id for id, name in zip(cores['core_id'], cores['core_name'])}
        core_id_to_label    = {v: k for k, v in core_options_map.items()}
        core_select_options = ["— Select Core —"] + list(core_options_map.keys())

        capture_devices       = fetch_capture_devices()
        device_options_map    = {row.device_name: row.capture_device_id for row in capture_devices}
        device_id_to_name     = {v: k for k, v in device_options_map.items()}
        device_select_options = ["— Select Device —"] + list(device_options_map.keys())

        unregistered_files = [f for f in found_files if f["file_name"] not in registered]
        registered_files   = [f for f in found_files if f["file_name"] in registered]
        sorted_files       = unregistered_files + registered_files

        st.markdown("---")
        st.markdown(
            f"**{len(unregistered_files)} unregistered** &nbsp;|&nbsp; "
            f"**{len(registered_files)} already registered**"
        )
        st.markdown("---")

        h1, h2, h3, h4 = st.columns([3, 2, 2, 2])
        h1.markdown("**File**")
        h2.markdown("**Core**")
        h3.markdown("**Capture Device**")
        h4.markdown("**Remarks**")
        st.markdown("---")

        for f in sorted_files:
            fname         = f["file_name"]
            is_registered = fname in registered
            db_record     = registered.get(fname, {})

            col1, col2, col3, col4 = st.columns([3, 2, 2, 2])

            with col1:
                icon    = "🖼️" if f["media_type"] == "image" else "🎥"
                size_mb = f["file_size_bytes"] / (1024 * 1024)
                status  = f"✅ *Registered — {db_record.get('core_name', '')}*" if is_registered else "⬜ *Unregistered*"
                st.markdown(f"{icon} **{fname}**  \n{status}  \n{size_mb:.1f} MB")

            with col2:
                current_core_id = st.session_state["media_core_assignments"].get(fname)
                current_label   = core_id_to_label.get(current_core_id, "— Select Core —")
                current_idx     = core_select_options.index(current_label) if current_label in core_select_options else 0
                chosen_core_label = st.selectbox(
                    f"core_{fname}", options=core_select_options, index=current_idx,
                    key=f"core_select_{fname}", label_visibility="collapsed"
                )
                st.session_state["media_core_assignments"][fname] = (
                    core_options_map[chosen_core_label] if chosen_core_label != "— Select Core —" else None
                )

            with col3:
                current_device_id   = st.session_state["media_device_assignments"].get(fname)
                current_device_name = device_id_to_name.get(current_device_id, "— Select Device —")
                current_device_idx  = device_select_options.index(current_device_name) if current_device_name in device_select_options else 0
                chosen_device_label = st.selectbox(
                    f"device_{fname}", options=device_select_options, index=current_device_idx,
                    key=f"device_select_{fname}", label_visibility="collapsed"
                )
                st.session_state["media_device_assignments"][fname] = (
                    device_options_map[chosen_device_label] if chosen_device_label != "— Select Device —" else None
                )

            with col4:
                current_remarks = st.session_state["media_remarks_assignments"].get(fname, "")
                remarks_val = st.text_input(
                    f"remarks_{fname}", value=current_remarks, placeholder="Remarks (optional)",
                    key=f"remarks_{fname}", label_visibility="collapsed"
                )
                st.session_state["media_remarks_assignments"][fname] = remarks_val

            st.markdown("---")

        if st.button("💾 Save Associations"):
            scan_dir_relative = st.session_state.get("media_scan_dir_relative", "")
            inserted = updated = skipped = 0
            missing_fields = []

            for f in found_files:
                fname            = f["file_name"]
                chosen_core_id   = st.session_state["media_core_assignments"].get(fname)
                chosen_device_id = st.session_state["media_device_assignments"].get(fname)
                chosen_remarks   = st.session_state["media_remarks_assignments"].get(fname) or None
                db_record        = registered.get(fname)

                if chosen_core_id is None and chosen_device_id is None:
                    skipped += 1
                    continue

                if chosen_core_id is None:
                    missing_fields.append(f"{fname}: Core not selected")
                    continue
                if chosen_device_id is None:
                    missing_fields.append(f"{fname}: Capture device not selected")
                    continue

                if db_record is None:
                    insert_core_media(
                        core_id=chosen_core_id,
                        file_name=fname,
                        file_path=scan_dir_relative,
                        media_type=f["media_type"],
                        file_size_bytes=f["file_size_bytes"],
                        capture_device_id=chosen_device_id,
                        remarks=chosen_remarks
                    )
                    inserted += 1

                elif (db_record["core_id"] == chosen_core_id and
                      db_record["capture_device_id"] == chosen_device_id and
                      (db_record["remarks"] or "") == (chosen_remarks or "")):
                    skipped += 1

                else:
                    update_core_media_association(
                        media_id=db_record["media_id"],
                        core_id=chosen_core_id,
                        capture_device_id=chosen_device_id,
                        remarks=chosen_remarks
                    )
                    updated += 1

            if missing_fields:
                st.warning("⚠️ Some files are partially filled in and were skipped:\n" +
                           "\n".join(f"- {m}" for m in missing_fields))

            parts = []
            if inserted:
                parts.append(f"{inserted} new record(s) saved")
            if updated:
                parts.append(f"{updated} record(s) updated")
            if skipped:
                parts.append(f"{skipped} skipped")

            if parts:
                if inserted or updated:
                    st.success("✅ " + " | ".join(parts))
                else:
                    st.info("ℹ️ " + " | ".join(parts))