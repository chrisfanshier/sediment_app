"""
File Sync to Central - Upload actual data files after metadata sync
Run on ship: streamlit run file_sync.py
"""

import streamlit as st
import os
import requests
from sqlalchemy import text
from db_util import get_connection
from config import ROOT_DIRECTORY
import socket
import pandas as pd

# Central upload endpoint
CENTRAL_UPLOAD_URL = "http://10.129.222.192:5910/upload_file"
CENTRAL_HEALTH_URL = "http://10.129.222.192:5910/health"

# Tables with files to sync
FILE_TABLES = [
    ('sensor_files', 'file_id', 'file_path'),
    ('winch_data', 'winch_file_id', 'file_path'),
    ('mscl_files', 'file_id', 'file_path'),
]

st.set_page_config(page_title="Sync Files to Central", layout="wide")
st.title("📁 Sync Data Files to Central")
st.info("Upload actual data files for records that have been metadata-synced")

# Sidebar - Connection info
st.sidebar.header("Central File Server")
st.sidebar.code(CENTRAL_UPLOAD_URL, language="text")

if st.sidebar.button("🔌 Test Connection"):
    try:
        response = requests.get(CENTRAL_HEALTH_URL, timeout=5)
        if response.status_code == 200:
            st.sidebar.success("✅ Central server reachable")
        else:
            st.sidebar.error(f"❌ Status {response.status_code}")
    except:
        st.sidebar.error("❌ Cannot reach central server")

st.sidebar.divider()
st.sidebar.caption(f"**Ship:** {socket.gethostname()}")
st.sidebar.caption(f"**Local Root:** {ROOT_DIRECTORY}")

# Function to check if file has been uploaded
def is_file_uploaded(table_name, record_id):
    """Check if file has already been successfully uploaded"""
    with get_connection() as conn:
        query = text("""
            SELECT upload_id, uploaded_at 
            FROM file_upload_tracking
            WHERE table_name = :table_name 
            AND record_id = :record_id
            AND upload_status = 'success'
        """)
        result = conn.execute(query, {"table_name": table_name, "record_id": record_id}).fetchone()
        return result

# Function to mark file as uploaded
def mark_file_uploaded(table_name, record_id, relative_path, file_size_bytes, status='success', error_msg=None):
    """Record successful file upload in tracking table"""
    try:
        with get_connection() as conn:
            query = text("""
                INSERT INTO file_upload_tracking 
                (table_name, record_id, relative_path, file_size_bytes, upload_status, error_message)
                VALUES (:table_name, :record_id, :relative_path, :file_size_bytes, :status, :error_msg)
                ON CONFLICT (table_name, record_id) 
                DO UPDATE SET 
                    uploaded_at = CURRENT_TIMESTAMP,
                    upload_status = :status,
                    file_size_bytes = :file_size_bytes,
                    error_message = :error_msg
            """)
            conn.execute(query, {
                "table_name": table_name,
                "record_id": record_id,
                "relative_path": relative_path,
                "file_size_bytes": file_size_bytes,
                "status": status,
                "error_msg": error_msg
            })
            conn.commit()
            return True
    except Exception as e:
        st.error(f"Failed to update upload tracking: {e}")
        return False

# Function to get files needing sync
def get_files_to_sync():
    files_data = []
    
    with get_connection() as conn:
        for table_name, id_column, path_column in FILE_TABLES:
            # Build query
            if table_name == 'sensor_files':
                query = text(f"""
                    SELECT sf.{id_column}, sf.{path_column}, sf.central_id, 
                           sf.file_name, c.core_name
                    FROM {table_name} sf
                    LEFT JOIN cores c ON sf.core_id = c.core_id
                    WHERE sf.sync_status = 'synced'
                    AND sf.created_on_ship = TRUE
                """)
            elif table_name == 'winch_data':
                query = text(f"""
                    SELECT wd.{id_column}, wd.{path_column}, wd.central_id,
                           wd.file_name, cr.cruise_name
                    FROM {table_name} wd
                    LEFT JOIN cruises cr ON wd.cruise_id = cr.cruise_id
                    WHERE wd.sync_status = 'synced'
                    AND wd.created_on_ship = TRUE
                """)
            elif table_name == 'mscl_files':
                query = text(f"""
                    SELECT mf.{id_column}, mf.{path_column}, mf.central_id,
                           mf.file_name, c.core_name
                    FROM {table_name} mf
                    LEFT JOIN cores c ON mf.core_id = c.core_id
                    WHERE mf.sync_status = 'synced'
                    AND mf.created_on_ship = TRUE
                """)
            
            records = conn.execute(query).fetchall()
            
            for record in records:
                record_id = record[0]
                relative_path = record[1]
                central_id = record[2]
                file_name = record[3]
                associated_name = record[4]
                
                if relative_path and file_name:
                    # Combine directory path with filename
                    full_relative_path = os.path.join(relative_path, file_name)
                    local_full_path = os.path.join(ROOT_DIRECTORY, full_relative_path)
                    
                    file_exists = os.path.exists(local_full_path)
                    
                    # Check if already uploaded
                    upload_info = is_file_uploaded(table_name, record_id)
                    
                    # Get file size
                    if file_exists:
                        try:
                            file_size = os.path.getsize(local_full_path)
                            size_mb = round(file_size / (1024*1024), 2)
                        except Exception as e:
                            file_size = 0
                            size_mb = 0.0
                    else:
                        file_size = 0
                        size_mb = 0.0
                    
                    # Determine status
                    if not file_exists:
                        status = '❌ Missing'
                    elif upload_info:
                        status = f'✅ Uploaded {upload_info[1].strftime("%Y-%m-%d")}'
                    else:
                        status = '⏳ Pending'
                    
                    files_data.append({
                        'table': table_name,
                        'id_column': id_column,
                        'record_id': record_id,
                        'central_id': central_id,
                        'relative_path': full_relative_path,
                        'file_name': file_name,
                        'associated_name': associated_name if associated_name else 'N/A',
                        'local_path': local_full_path,
                        'exists': file_exists,
                        'size_bytes': file_size,
                        'size_mb': size_mb,
                        'uploaded': upload_info is not None,
                        'upload_date': upload_info[1] if upload_info else None,
                        'status': status
                    })
    
    return files_data

# Get files
if st.button("🔍 Scan for Files"):
    st.cache_data.clear()

files = get_files_to_sync()

# Display summary
st.header("📊 Files from Synced Metadata")

if not files:
    st.info("No files found. Make sure metadata has been synced first using ship_sync.py")
else:
    # Summary metrics
    col1, col2, col3, col4, col5 = st.columns(5)
    
    total_files = len(files)
    uploaded_files = len([f for f in files if f['uploaded']])
    pending_files = len([f for f in files if f['exists'] and not f['uploaded']])
    missing_files = len([f for f in files if not f['exists']])
    pending_size = sum([f['size_mb'] for f in files if f['exists'] and not f['uploaded']])
    
    col1.metric("Total Files", total_files)
    col2.metric("✅ Uploaded", uploaded_files)
    col3.metric("⏳ Pending", pending_files)
    col4.metric("❌ Missing", missing_files)
    col5.metric("To Upload (MB)", f"{pending_size:.1f}")
    
    # Filter options
    st.subheader("Select Files to Upload")
    
    filter_option = st.radio(
        "Show:",
        ["Pending Only", "All Files", "Uploaded Only"],
        horizontal=True
    )
    
    # Filter files
    if filter_option == "Pending Only":
        display_files = [f for f in files if f['exists'] and not f['uploaded']]
    elif filter_option == "Uploaded Only":
        display_files = [f for f in files if f['uploaded']]
    else:
        display_files = files
    
    if not display_files:
        st.info(f"No files to display for filter: {filter_option}")
    else:
        # Create dataframe for display
        df_display = pd.DataFrame([{
            'Select': not f['uploaded'] and f['exists'],  # Auto-select pending files
            'File Name': f['file_name'],
            'Core/Cruise': f['associated_name'],
            'Table': f['table'],
            'Status': f['status'],
            'Size (MB)': f['size_mb']
        } for f in display_files])
        
        # Let user select files
        edited_df = st.data_editor(
            df_display,
            disabled=['File Name', 'Core/Cruise', 'Table', 'Status', 'Size (MB)'],
            hide_index=True,
            use_container_width=True,
            column_config={
                "Select": st.column_config.CheckboxColumn(
                    "Select",
                    help="Select files to upload",
                    default=False,
                ),
                "Size (MB)": st.column_config.NumberColumn(
                    "Size (MB)",
                    format="%.2f"
                )
            }
        )
        
        # Get selected files
        selected_indices = edited_df[edited_df['Select'] == True].index.tolist()
        selected_files = [display_files[i] for i in selected_indices 
                         if display_files[i]['exists'] and not display_files[i]['uploaded']]
        
        st.divider()
        
        # Upload button
        if selected_files:
            selected_size = sum([f['size_mb'] for f in selected_files])
            st.info(f"**{len(selected_files)} files selected** (Total: {selected_size:.1f} MB)")
            
            if st.button("🚀 Upload Selected Files", type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                uploaded_count = 0
                error_count = 0
                errors = []
                
                for i, file_info in enumerate(selected_files):
                    try:
                        if file_info['exists']:
                            status_text.text(f"Uploading {i+1}/{len(selected_files)}: {file_info['file_name']}")
                        
                            # Normalize path
                            normalized_path = file_info['relative_path'].replace('\\', '/')
                            
                            with open(file_info['local_path'], 'rb') as f:
                                files_payload = {'file': f}
                                data_payload = {'relative_path': normalized_path}
                                
                                response = requests.post(
                                    CENTRAL_UPLOAD_URL,
                                    files=files_payload,
                                    data=data_payload,
                                    timeout=120
                                )
                                
                                if response.status_code == 200:
                                    # Mark as uploaded in tracking table
                                    if mark_file_uploaded(
                                        file_info['table'], 
                                        file_info['record_id'],
                                        normalized_path,
                                        file_info['size_bytes']
                                    ):
                                        uploaded_count += 1
                                    else:
                                        error_count += 1
                                        errors.append(f"{file_info['file_name']}: Uploaded but failed to track")
                                else:
                                    error_count += 1
                                    error_msg = f"{file_info['file_name']}: {response.text}"
                                    errors.append(error_msg)
                                    # Track the failure
                                    mark_file_uploaded(
                                        file_info['table'],
                                        file_info['record_id'],
                                        normalized_path,
                                        file_info['size_bytes'],
                                        status='failed',
                                        error_msg=response.text
                                    )
                    
                    except Exception as e:
                        error_count += 1
                        error_msg = f"{file_info['file_name']}: {str(e)}"
                        errors.append(error_msg)
                        # Track the failure
                        mark_file_uploaded(
                            file_info['table'],
                            file_info['record_id'],
                            file_info['relative_path'],
                            file_info['size_bytes'],
                            status='failed',
                            error_msg=str(e)
                        )
                    
                    progress_bar.progress((i + 1) / len(selected_files))
                
                progress_bar.empty()
                status_text.empty()
                
                # Show results
                if uploaded_count > 0:
                    st.success(f"✅ Successfully uploaded {uploaded_count} files!")
                    st.rerun()  # Refresh to show updated status
                if error_count > 0:
                    st.error(f"⚠️ {error_count} files failed to upload")
                    with st.expander("View Errors"):
                        for error in errors:
                            st.text(error)
        else:
            if pending_files > 0:
                st.info("Select files to upload using the checkboxes above")
            else:
                st.success("✅ All available files have been uploaded!")

# Show upload history
st.divider()
st.header("📜 Recent File Uploads")

try:
    with get_connection() as conn:
        query = text("""
            SELECT 
                table_name,
                relative_path,
                file_size_bytes,
                uploaded_at,
                upload_status
            FROM file_upload_tracking
            ORDER BY uploaded_at DESC
            LIMIT 20
        """)
        records = conn.execute(query).fetchall()
        
        if records:
            history_data = [{
                'Table': rec[0],
                'File': os.path.basename(rec[1]),
                'Size (MB)': round(rec[2] / (1024*1024), 2) if rec[2] else 0,
                'Uploaded': rec[3].strftime('%Y-%m-%d %H:%M'),
                'Status': '✅' if rec[4] == 'success' else '❌'
            } for rec in records]
            
            st.dataframe(
                pd.DataFrame(history_data),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No file upload history yet")
except Exception as e:
    st.warning(f"Could not load history: {e}")

# Footer with instructions
st.divider()
with st.expander("ℹ️ How to Use"):
    st.markdown("""
    ### File Sync Workflow
    
    1. **First**, sync metadata using `ship_sync.py`
       - This uploads cruise/core/file metadata to central
       - Records are marked as `sync_status = 'synced'`
    
    2. **Then**, use this app to upload the actual files
       - Click "Scan for Files" to refresh the list
       - Select files with checkboxes (pending files auto-selected)
       - Click "Upload Selected Files"
       - Files are tracked in `file_upload_tracking` table
    
    ### Upload Tracking
    
    - Each successful upload is recorded in a separate tracking table
    - Already-uploaded files are marked with ✅ and upload date
    - Failed uploads are tracked with error messages
    - You can re-upload failed files by selecting them again
    
    ### File Requirements
    
    - Files must exist locally at the path specified in the database
    - Only files from synced metadata records are shown
    - Only files created on this ship (`created_on_ship = TRUE`) are synced
    - Missing files cannot be uploaded (check file paths)
    """)