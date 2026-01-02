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

# Function to get files needing sync
def get_files_to_sync():
    files_data = []
    
    with get_connection() as conn:
        for table_name, id_column, path_column in FILE_TABLES:
            # Build query - just look for synced metadata, ignore file_synced column
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
                ship_id = record[0]
                relative_path = record[1]  # This is just the directory
                central_id = record[2]
                file_name = record[3]
                associated_name = record[4]  # core_name or cruise_name
                
                if relative_path and file_name:
                    # Combine directory path with filename to get full relative path
                    full_relative_path = os.path.join(relative_path, file_name)
                    local_full_path = os.path.join(ROOT_DIRECTORY, full_relative_path)
                    
                    file_exists = os.path.exists(local_full_path)
                    
                    # Only get size if file exists
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
                    
                    files_data.append({
                        'table': table_name,
                        'ship_id': ship_id,
                        'central_id': central_id,
                        'relative_path': full_relative_path,
                        'file_name': file_name,
                        'associated_name': associated_name if associated_name else 'N/A',
                        'local_path': local_full_path,
                        'exists': file_exists,
                        'size_mb': size_mb,
                        'status': '✅ Ready' if file_exists else '❌ Missing'
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
    col1, col2, col3, col4 = st.columns(4)
    
    total_files = len(files)
    ready_files = len([f for f in files if f['exists']])
    missing_files = total_files - ready_files
    total_size = sum([f['size_mb'] for f in files if f['exists']])
    
    col1.metric("Total Files", total_files)
    col2.metric("Ready to Upload", ready_files)
    col3.metric("Missing Locally", missing_files)
    col4.metric("Total Size (MB)", f"{total_size:.1f}")
    
    # Show files in table
    st.subheader("Select Files to Upload")
    
    # Create dataframe for display
    df_display = pd.DataFrame([{
        'Select': False,
        'File Name': f['file_name'],
        'Core/Cruise': f['associated_name'],
        'Table': f['table'],
        'Status': f['status'],
        'Size (MB)': f['size_mb']
    } for f in files])
    
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
    selected_files = [files[i] for i in selected_indices if files[i]['exists']]
    
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
                        
                        # DEBUG OUTPUT
                        st.write("=" * 60)
                        st.write(f"**Uploading file {i+1}:**")
                        st.write(f"- File name: {file_info['file_name']}")
                        st.write(f"- Normalized path: `{normalized_path}`")
                        st.write(f"- Local path: `{file_info['local_path']}`")
                        st.write(f"- Size: {file_info['size_mb']} MB")
                        
                        with open(file_info['local_path'], 'rb') as f:
                            files_payload = {'file': f}
                            data_payload = {'relative_path': normalized_path}
                            
                            response = requests.post(
                                CENTRAL_UPLOAD_URL,
                                files=files_payload,
                                data=data_payload,
                                timeout=120
                            )
                            
                            st.write(f"- Response status: {response.status_code}")
                            st.write(f"- Response: {response.text}")
                        st.write("=" * 60)
                        
                        if response.status_code == 200:
                            uploaded_count += 1
                        else:
                            error_count += 1
                            error_msg = f"{file_info['file_name']}: {response.text}"
                            errors.append(error_msg)
                
                except Exception as e:
                    error_count += 1
                    error_msg = f"{file_info['file_name']}: {str(e)}"
                    errors.append(error_msg)
                
                progress_bar.progress((i + 1) / len(selected_files))
            
            progress_bar.empty()
            status_text.empty()
            
            # Show results
            if uploaded_count > 0:
                st.success(f"✅ Successfully uploaded {uploaded_count} files!")
            if error_count > 0:
                st.error(f"⚠️ {error_count} files failed to upload")
                with st.expander("View Errors"):
                    for error in errors:
                        st.text(error)
    else:
        if ready_files > 0:
            st.info("Select files to upload using the checkboxes above")
        else:
            st.warning("No files are ready to upload (all files are missing locally)")

# Show upload history
st.divider()
st.header("📜 Recently Synced Files")

try:
    with get_connection() as conn:
        # Get recently synced files across all tables
        history_data = []
        for table_name, id_column, path_column in FILE_TABLES:
            query = text(f"""
                SELECT {path_column}, last_file_synced_at
                FROM {table_name}
                WHERE file_synced = TRUE
                AND last_file_synced_at IS NOT NULL
                ORDER BY last_file_synced_at DESC
                LIMIT 20
            """)
            records = conn.execute(query).fetchall()
            for rec in records:
                history_data.append({
                    'File': rec[0],
                    'Synced At': rec[1],
                    'Table': table_name
                })
        
        if history_data:
            history_df = pd.DataFrame(history_data).sort_values('Synced At', ascending=False).head(20)
            st.dataframe(
                history_df,
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No file sync history yet")
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
       - Click "Scan for Files to Sync" to refresh the list
       - Select files with checkboxes
       - Click "Upload Selected Files"
       - Files are marked as `file_synced = TRUE` after upload
    
    ### File Requirements
    
    - Files must exist locally at the path specified in the database
    - Only files from synced metadata records are shown
    - Only files created on this ship (`created_on_ship = TRUE`) are synced
    - Missing files cannot be uploaded (check file paths)
    
    ### Troubleshooting
    
    - **"No files need syncing"**: Either all files are synced, or no metadata has been synced yet
    - **"Missing Locally"**: File path in database doesn't match actual file location
    - **Upload fails**: Check network connection to central server (test with health check button)
    """)