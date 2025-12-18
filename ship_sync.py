"""
Ship-Side Sync - Push pending metadata to central database
Run on ship: streamlit run ship_sync.py
Access at: http://localhost:8501
"""

import streamlit as st
from sqlalchemy import text
import requests
import json
from datetime import datetime
import pandas as pd
from db_util import get_connection
import socket
from decimal import Decimal

# Central server endpoint
CENTRAL_SYNC_URL = "http://10.129.222.192:5910/sync"
CENTRAL_HEALTH_URL = "http://10.129.222.192:5910/health"

# Tables to sync in dependency order
SYNC_TABLES = [
    ('vessels', 'vessel_id'),
    ('cruises', 'cruise_id'),
    ('cores', 'core_id'),
    ('sections', 'section_id'),
    ('mscl_files', 'file_id'),
    ('sensor_files', 'file_id'),
    ('winch_data', 'winch_file_id'),
]

st.set_page_config(page_title="Sync to Central", layout="wide")

st.title("📤 Sync to Central Database")
st.info("Push your pending changes to the central database")

# Get ship name
ship_name = st.text_input(
    "Ship/Cruise Name", 
    value=socket.gethostname(), 
    help="Identifies this ship in sync logs"
)

# Sidebar - Connection info
st.sidebar.header("Central Database")
st.sidebar.code(CENTRAL_SYNC_URL, language="text")

if st.sidebar.button("🔌 Test Connection to Central"):
    try:
        response = requests.get(CENTRAL_HEALTH_URL, timeout=5)
        if response.status_code == 200:
            st.sidebar.success("✅ Central server is reachable")
            result = response.json()
            st.sidebar.caption(f"Server time: {result.get('timestamp', 'N/A')}")
        else:
            st.sidebar.error(f"❌ Central returned status {response.status_code}")
    except requests.exceptions.RequestException as e:
        st.sidebar.error("❌ Cannot reach central server")
        st.sidebar.caption("Check VPN connection")

st.sidebar.divider()
st.sidebar.caption("**Ship Database (Local)**")
with get_connection() as conn:
    try:
        core_count = conn.execute(text("SELECT COUNT(*) FROM cores")).scalar()
        st.sidebar.metric("Total Cores", core_count)
    except:
        st.sidebar.warning("Could not query local database")

# Check pending changes
st.header("📊 Pending Changes on This Ship")

total_pending = 0
pending_data = {}

cols = st.columns(len(SYNC_TABLES))

for idx, (table_name, id_column) in enumerate(SYNC_TABLES):
    try:
        with get_connection() as conn:
            count_query = text(f"""
                SELECT COUNT(*) FROM {table_name} 
                WHERE sync_status = 'pending'
            """)
            count = conn.execute(count_query).scalar()
            total_pending += count
            
            with cols[idx]:
                st.metric(table_name.replace('_', ' ').title(), count)
            
            if count > 0:
                # Get pending records
                data_query = text(f"""
                    SELECT * FROM {table_name}
                    WHERE sync_status = 'pending'
                    ORDER BY created_at
                """)
                records = conn.execute(data_query).fetchall()
                pending_data[table_name] = records
                
    except Exception as e:
        with cols[idx]:
            st.metric(table_name.replace('_', ' ').title(), "Error")
            st.caption(str(e)[:50])

# Show details of pending changes
if total_pending > 0:
    with st.expander("📋 View Pending Records"):
        for table_name, id_column in SYNC_TABLES:
            if table_name in pending_data and len(pending_data[table_name]) > 0:
                st.subheader(f"{table_name} ({len(pending_data[table_name])} records)")
                df = pd.DataFrame([dict(r._mapping) for r in pending_data[table_name]])
                # Show first 10 records
                st.dataframe(df.head(10), use_container_width=True)
                if len(df) > 10:
                    st.caption(f"... and {len(df) - 10} more records")

# Sync button
st.divider()

if total_pending == 0:
    st.success("✅ No pending changes to sync!")
    st.info("Create new cores, sections, or upload files to generate pending changes.")
else:
    st.warning(f"**Total pending records:** {total_pending}")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        st.write("This will send all pending metadata changes to the central database.")
        st.caption("Records will be marked as 'synced' after successful transfer.")
    
    with col2:
        sync_button = st.button("🚀 Sync to Central", type="primary", use_container_width=True)
    
    if sync_button:
        # Build sync payload
        sync_payload = {
            'ship_name': ship_name,
            'timestamp': datetime.now().isoformat(),
            'data': {}
        }
        
        # Convert records to JSON-serializable format
        for table_name, id_column in SYNC_TABLES:
            if table_name in pending_data:
                sync_payload['data'][table_name] = []
                
                for record in pending_data[table_name]:
                    record_dict = dict(record._mapping)
                    
                    ship_id = record_dict[id_column]
                    central_id = record_dict.get('central_id')
                    
                    # Remove sync columns
                    sync_columns = ['created_on_ship', 'sync_status', 'created_at', 
                                  'modified_at', 'last_synced_at', 'file_synced', 'central_id']
                    
                    clean_data = {}
                    for key, value in record_dict.items():
                        if key not in sync_columns and key != id_column:
                            # Handle special types - UPDATED TO HANDLE DECIMAL
                            import math
                            
                            if value is None:
                                clean_data[key] = None
                            elif isinstance(value, Decimal):
                                # Convert Decimal to float
                                clean_data[key] = float(value)
                            elif isinstance(value, float) and math.isnan(value):
                                clean_data[key] = None
                            elif hasattr(value, 'isoformat'):  # datetime
                                clean_data[key] = value.isoformat()
                            else:
                                clean_data[key] = value
                    
                    sync_payload['data'][table_name].append({
                        'ship_id': ship_id,
                        'central_id': central_id,
                        'data': clean_data
                    })
        
        # Send to central
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            status_text.text("📡 Sending data to central server...")
            
            response = requests.post(
                CENTRAL_SYNC_URL,
                json=sync_payload,
                timeout=120  # 2 minute timeout
            )
            
            progress_bar.progress(0.5)
            
            if response.status_code == 200:
                result = response.json()
                
                status_text.text("✅ Central server processed data. Updating local database...")
                
                # Update ship database with results
                synced_count = 0
                
                # Create lookup dict ONCE outside the loop
                table_to_id = {table: id_col for table, id_col in SYNC_TABLES}
                
                with get_connection() as conn:
                    for table_name, mappings in result.get('id_mappings', {}).items():
                        if table_name in table_to_id:
                            id_column = table_to_id[table_name]
                            
                            for ship_id_str, central_id in mappings.items():
                                ship_id = int(ship_id_str)
                                
                                update_query = text(f"""
                                    UPDATE {table_name}
                                    SET sync_status = 'synced',
                                        central_id = :central_id,
                                        last_synced_at = CURRENT_TIMESTAMP
                                    WHERE {id_column} = :ship_id
                                """)
                                conn.execute(update_query, {
                                    'ship_id': ship_id,
                                    'central_id': central_id
                                })
                                synced_count += 1
                    
                    conn.commit()
                
                progress_bar.progress(1.0)
                status_text.empty()
                
                st.success(f"✅ Successfully synced {result['synced_count']} records to central!")
                
                if result.get('error_count', 0) > 0:
                    st.warning(f"⚠️ {result['error_count']} records had errors")
                    if 'errors' in result:
                        with st.expander("View Errors"):
                            for error in result['errors']:
                                st.text(f"  - {error}")
                
                # Show summary
                st.subheader("📈 Sync Summary")
                summary_data = []
                for table_name, count in result.get('table_counts', {}).items():
                    if count > 0:
                        summary_data.append({
                            "Table": table_name,
                            "Records Synced": count
                        })
                
                if summary_data:
                    st.table(pd.DataFrame(summary_data))
                
                st.balloons()
                
                # Log locally
                try:
                    with get_connection() as conn:
                        log_query = text("""
                            INSERT INTO sync_log 
                            (sync_timestamp, sync_direction, table_name, records_synced, 
                             conflicts_detected, status)
                            VALUES (CURRENT_TIMESTAMP, 'to_central', :ship_name, 
                                   :synced, :errors, :status)
                        """)
                        conn.execute(log_query, {
                            'ship_name': ship_name,
                            'synced': result['synced_count'],
                            'errors': result.get('error_count', 0),
                            'status': result['status']
                        })
                        conn.commit()
                except Exception as e:
                    st.caption(f"Note: Could not log sync locally ({str(e)})")
                
                # Auto-refresh after 2 seconds to show updated counts
                import time
                time.sleep(2)
                st.rerun()
                
            else:
                st.error(f"❌ Central server error: {response.status_code}")
                st.code(response.text)
                
        except requests.exceptions.Timeout:
            st.error("❌ Request timed out. Central server may be slow or unreachable.")
            st.caption("Try again or check your network connection.")
        except requests.exceptions.ConnectionError:
            st.error("❌ Cannot connect to central server")
            st.caption("Make sure you're connected to VPN and central server is running.")
        except Exception as e:
            st.error(f"❌ Sync failed: {str(e)}")
            import traceback
            with st.expander("Error Details"):
                st.code(traceback.format_exc())
        finally:
            progress_bar.empty()
            status_text.empty()

# Show local sync history
st.divider()
st.header("📜 Recent Syncs from This Ship")

try:
    with get_connection() as conn:
        history = conn.execute(text("""
            SELECT sync_timestamp, table_name as description, 
                   records_synced, conflicts_detected, status
            FROM sync_log
            WHERE sync_direction = 'to_central'
            ORDER BY sync_timestamp DESC
            LIMIT 10
        """)).fetchall()
        
        if history:
            df = pd.DataFrame([dict(r._mapping) for r in history])
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No sync history yet. After your first sync, it will appear here.")
except Exception as e:
    st.warning(f"Could not load sync history: {e}")

# Footer
st.divider()
st.caption(f"🚢 Ship: {ship_name}")
st.caption(f"📡 Central: {CENTRAL_SYNC_URL}")
st.caption(f"💾 Local DB: {get_connection().engine.url.database}")