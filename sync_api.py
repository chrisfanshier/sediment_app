"""
Ship-to-Central Sync - Streamlit UI
Run on ship: streamlit run ship_sync.py
"""

import streamlit as st
import requests
from sqlalchemy import text
from db_util import get_connection
from datetime import datetime
import socket

# Central sync endpoint
CENTRAL_SYNC_URL = "http://10.129.222.192:5910/sync"
CENTRAL_HEALTH_URL = "http://10.129.222.192:5910/health"

# Tables that can be synced (in dependency order)
SYNC_TABLES = {
    'vessels': 'vessel_id',
    'cruises': 'cruise_id', 
    'cores': 'core_id',
    'sections': 'section_id',
    'mscl_files': 'file_id',
    'sensor_files': 'file_id',
    'winch_data': 'winch_file_id',
}

st.set_page_config(page_title="Sync to Central", layout="wide")
st.title("🔄 Sync Metadata to Central Database")
st.info("Sync metadata records to central. Files are synced separately using file_sync.py")

# Sidebar - Connection info
st.sidebar.header("Central Database")
st.sidebar.code(CENTRAL_SYNC_URL, language="text")

if st.sidebar.button("🔌 Test Connection"):
    try:
        response = requests.get(CENTRAL_HEALTH_URL, timeout=5)
        if response.status_code == 200:
            st.sidebar.success("✅ Central database reachable")
        else:
            st.sidebar.error(f"❌ Status {response.status_code}")
    except:
        st.sidebar.error("❌ Cannot reach central database")

st.sidebar.divider()
st.sidebar.caption(f"**Ship:** {socket.gethostname()}")


def get_pending_records(table_name, id_column):
    """
    Get records that need syncing.
    CRITICAL: For child tables, replace ship's FK IDs with parent's central_id
    """
    with get_connection() as conn:
        
        # WINCH_DATA: Replace cruise_id with cruise's central_id
        if table_name == 'winch_data':
            query = text("""
                SELECT 
                    wd.winch_file_id as ship_id,
                    wd.central_id,
                    wd.file_name,
                    wd.file_path,
                    wd.cruise_id as ship_cruise_id,
                    c.central_id as cruise_central_id,
                    wd.date,
                    wd.created_on_ship,
                    wd.sync_status,
                    wd.last_synced_at
                FROM winch_data wd
                LEFT JOIN cruises c ON wd.cruise_id = c.cruise_id
                WHERE wd.sync_status = 'pending'
                AND wd.created_on_ship = TRUE
            """)
            
            records = []
            for row in conn.execute(query):
                row_dict = dict(row._mapping)
                ship_id = row_dict.pop('ship_id')
                central_id = row_dict.pop('central_id')
                ship_cruise_id = row_dict.pop('ship_cruise_id')
                cruise_central_id = row_dict.pop('cruise_central_id')
                
                # Use cruise's central_id if available, otherwise ship's cruise_id
                if cruise_central_id:
                    row_dict['cruise_id'] = cruise_central_id
                else:
                    row_dict['cruise_id'] = ship_cruise_id
                    # Warning: parent not synced yet
                    st.warning(f"⚠️ Winch file {ship_id} references cruise {ship_cruise_id} which hasn't been synced yet!")
                
                records.append({
                    'ship_id': ship_id,
                    'central_id': central_id,
                    'data': row_dict
                })
            
            return records
        
        # CORES: Replace cruise_id with cruise's central_id
        elif table_name == 'cores':
            query = text("""
                SELECT 
                    co.core_id as ship_id,
                    co.central_id,
                    co.*,
                    cr.central_id as cruise_central_id,
                    co.cruise_id as ship_cruise_id
                FROM cores co
                LEFT JOIN cruises cr ON co.cruise_id = cr.cruise_id
                WHERE co.sync_status = 'pending'
                AND co.created_on_ship = TRUE
            """)
            
            records = []
            for row in conn.execute(query):
                row_dict = dict(row._mapping)
                ship_id = row_dict.pop('ship_id')
                central_id = row_dict.pop('central_id')
                cruise_central_id = row_dict.pop('cruise_central_id')
                ship_cruise_id = row_dict.pop('ship_cruise_id')
                
                # Use cruise's central_id if available
                if cruise_central_id:
                    row_dict['cruise_id'] = cruise_central_id
                else:
                    row_dict['cruise_id'] = ship_cruise_id
                    st.warning(f"⚠️ Core {row_dict.get('core_name')} references cruise that hasn't been synced yet!")
                
                records.append({
                    'ship_id': ship_id,
                    'central_id': central_id,
                    'data': row_dict
                })
            
            return records
        
        # MSCL_FILES: Replace core_id with core's central_id
        elif table_name == 'mscl_files':
            query = text("""
                SELECT 
                    mf.file_id as ship_id,
                    mf.central_id,
                    mf.*,
                    co.central_id as core_central_id,
                    mf.core_id as ship_core_id
                FROM mscl_files mf
                LEFT JOIN cores co ON mf.core_id = co.core_id
                WHERE mf.sync_status = 'pending'
                AND mf.created_on_ship = TRUE
            """)
            
            records = []
            for row in conn.execute(query):
                row_dict = dict(row._mapping)
                ship_id = row_dict.pop('ship_id')
                central_id = row_dict.pop('central_id')
                core_central_id = row_dict.pop('core_central_id')
                ship_core_id = row_dict.pop('ship_core_id')
                
                if core_central_id:
                    row_dict['core_id'] = core_central_id
                else:
                    row_dict['core_id'] = ship_core_id
                    st.warning(f"⚠️ MSCL file {ship_id} references core that hasn't been synced yet!")
                
                records.append({
                    'ship_id': ship_id,
                    'central_id': central_id,
                    'data': row_dict
                })
            
            return records
        
        # SENSOR_FILES: Replace core_id with core's central_id
        elif table_name == 'sensor_files':
            query = text("""
                SELECT 
                    sf.file_id as ship_id,
                    sf.central_id,
                    sf.*,
                    co.central_id as core_central_id,
                    sf.core_id as ship_core_id
                FROM sensor_files sf
                LEFT JOIN cores co ON sf.core_id = co.core_id
                WHERE sf.sync_status = 'pending'
                AND sf.created_on_ship = TRUE
            """)
            
            records = []
            for row in conn.execute(query):
                row_dict = dict(row._mapping)
                ship_id = row_dict.pop('ship_id')
                central_id = row_dict.pop('central_id')
                core_central_id = row_dict.pop('core_central_id')
                ship_core_id = row_dict.pop('ship_core_id')
                
                if core_central_id:
                    row_dict['core_id'] = core_central_id
                else:
                    row_dict['core_id'] = ship_core_id
                    st.warning(f"⚠️ Sensor file {ship_id} references core that hasn't been synced yet!")
                
                records.append({
                    'ship_id': ship_id,
                    'central_id': central_id,
                    'data': row_dict
                })
            
            return records
        
        # SECTIONS: Replace core_id with core's central_id
        elif table_name == 'sections':
            query = text("""
                SELECT 
                    s.section_id as ship_id,
                    s.central_id,
                    s.*,
                    co.central_id as core_central_id,
                    s.core_id as ship_core_id
                FROM sections s
                LEFT JOIN cores co ON s.core_id = co.core_id
                WHERE s.sync_status = 'pending'
                AND s.created_on_ship = TRUE
            """)
            
            records = []
            for row in conn.execute(query):
                row_dict = dict(row._mapping)
                ship_id = row_dict.pop('ship_id')
                central_id = row_dict.pop('central_id')
                core_central_id = row_dict.pop('core_central_id')
                ship_core_id = row_dict.pop('ship_core_id')
                
                if core_central_id:
                    row_dict['core_id'] = core_central_id
                else:
                    row_dict['core_id'] = ship_core_id
                    st.warning(f"⚠️ Section {ship_id} references core that hasn't been synced yet!")
                
                records.append({
                    'ship_id': ship_id,
                    'central_id': central_id,
                    'data': row_dict
                })
            
            return records
        
        # DEFAULT: Tables without FK dependencies (vessels, cruises)
        else:
            query = text(f"""
                SELECT {id_column} as ship_id, central_id, *
                FROM {table_name}
                WHERE sync_status = 'pending'
                AND created_on_ship = TRUE
            """)
            
            records = []
            for row in conn.execute(query):
                row_dict = dict(row._mapping)
                ship_id = row_dict.pop('ship_id')
                central_id = row_dict.pop('central_id')
                
                records.append({
                    'ship_id': ship_id,
                    'central_id': central_id,
                    'data': row_dict
                })
            
            return records


def update_synced_records(table_name, id_column, id_mappings):
    """Update local records with central_id and sync status"""
    with get_connection() as conn:
        for ship_id, central_id in id_mappings.items():
            query = text(f"""
                UPDATE {table_name}
                SET central_id = :central_id,
                    sync_status = 'synced',
                    last_synced_at = CURRENT_TIMESTAMP
                WHERE {id_column} = :ship_id
            """)
            conn.execute(query, {"central_id": central_id, "ship_id": ship_id})
        conn.commit()


# Main UI
st.header("📊 Pending Records")

# Count pending records for each table
pending_counts = {}
with get_connection() as conn:
    for table_name in SYNC_TABLES.keys():
        query = text(f"""
            SELECT COUNT(*) 
            FROM {table_name} 
            WHERE sync_status = 'pending' 
            AND created_on_ship = TRUE
        """)
        count = conn.execute(query).scalar()
        pending_counts[table_name] = count

# Display counts
cols = st.columns(len(SYNC_TABLES))
for i, (table_name, count) in enumerate(pending_counts.items()):
    with cols[i]:
        st.metric(table_name, count)

st.divider()

# Table selection
st.subheader("Select Tables to Sync")
selected_tables = st.multiselect(
    "Choose tables:",
    options=list(SYNC_TABLES.keys()),
    default=[t for t, c in pending_counts.items() if c > 0],
    help="Tables are synced in dependency order (parents before children)"
)

if not selected_tables:
    st.info("Select tables to sync")
else:
    # Show what will be synced
    st.write("**Will sync:**")
    for table in selected_tables:
        count = pending_counts[table]
        if count > 0:
            st.write(f"- {table}: {count} records")
    
    st.divider()
    
    # Sync button
    if st.button("🚀 Sync to Central", type="primary", use_container_width=True):
        
        # Build payload
        payload = {
            'ship_name': socket.gethostname(),
            'timestamp': datetime.now().isoformat(),
            'data': {}
        }
        
        total_records = 0
        for table_name in selected_tables:
            id_column = SYNC_TABLES[table_name]
            records = get_pending_records(table_name, id_column)
            if records:
                payload['data'][table_name] = records
                total_records += len(records)
        
        if total_records == 0:
            st.warning("No pending records to sync")
        else:
            st.info(f"Syncing {total_records} records...")
            
            try:
                # Send to central
                response = requests.post(
                    CENTRAL_SYNC_URL,
                    json=payload,
                    timeout=60
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    # Update local records with returned id_mappings
                    if 'id_mappings' in result:
                        for table_name, mappings in result['id_mappings'].items():
                            if mappings:
                                id_column = SYNC_TABLES[table_name]
                                update_synced_records(table_name, id_column, mappings)
                    
                    # Show results
                    if result.get('status') == 'success':
                        st.success(f"✅ Successfully synced {result['synced_count']} records!")
                    else:
                        st.warning(f"⚠️ Partial sync: {result['synced_count']} synced, {result['error_count']} errors")
                    
                    # Show details
                    with st.expander("Sync Details"):
                        st.json(result)
                    
                    # Show errors if any
                    if result.get('errors'):
                        with st.expander("⚠️ Errors"):
                            for error in result['errors']:
                                st.error(error)
                    
                    st.rerun()
                
                else:
                    st.error(f"❌ Sync failed: {response.status_code}")
                    st.code(response.text)
            
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

# Show sync history
st.divider()
st.header("📜 Recent Syncs")

try:
    with get_connection() as conn:
        # Show recently synced records
        for table_name in selected_tables if selected_tables else []:
            id_column = SYNC_TABLES[table_name]
            query = text(f"""
                SELECT {id_column} as ship_id, central_id, last_synced_at, sync_status
                FROM {table_name}
                WHERE sync_status = 'synced'
                AND created_on_ship = TRUE
                ORDER BY last_synced_at DESC
                LIMIT 10
            """)
            records = conn.execute(query).fetchall()
            
            if records:
                st.subheader(f"{table_name}")
                for rec in records:
                    st.text(f"Ship ID {rec[0]} → Central ID {rec[1]} (synced {rec[2]})")
except:
    pass

# Footer
st.divider()
with st.expander("ℹ️ How Sync Works"):
    st.markdown("""
    ### Metadata Sync Process
    
    1. **Select tables** to sync (in dependency order)
    2. **Ship sends** pending records to central
    3. **Central assigns** new IDs and returns mappings
    4. **Ship updates** local records with central_id
    
    ### Foreign Key Handling
    
    - When syncing child records (cores, files, etc.), the ship automatically looks up parent's `central_id`
    - If parent hasn't been synced yet, you'll see a warning
    - **Sync parent tables first** (cruises before cores, cores before files)
    
    ### After Metadata Sync
    
    - Use `file_sync.py` to upload actual data files
    - Only files from synced records will appear in file_sync.py
    """)
