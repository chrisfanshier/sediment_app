"""
Portable Database Manager - Streamlit interface for managing portable/offline databases.

This module provides a user interface for:
- Creating portable databases for field operations
- Viewing sync status
- Syncing data back to the central server
- Switching between portable and connected modes
"""

import streamlit as st
import os
from datetime import datetime

from database_manager import DatabaseManager, DatabaseMode, get_database_manager
from sync_manager import SyncManager, ConflictResolution, get_portable_status


def portable_database_manager():
    """Main Streamlit page for portable database management"""
    
    st.title("📱 Portable Database Manager")
    st.write("Manage offline databases for field operations at sea.")
    
    # Get current database status
    db_manager = get_database_manager()
    
    # Display current mode
    st.sidebar.header("Current Status")
    
    if db_manager.mode is None:
        db_manager.initialize()
    
    if db_manager.is_portable_mode:
        st.sidebar.success("🔌 **Mode:** Portable (SQLite)")
        st.sidebar.info("Working in offline mode")
    else:
        st.sidebar.info("🌐 **Mode:** Connected (PostgreSQL)")
    
    # Main content tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "📥 Create Portable DB", 
        "📤 Sync to Server",
        "📊 Sync Status", 
        "⚙️ Settings"
    ])
    
    with tab1:
        create_portable_database_ui()
    
    with tab2:
        sync_to_server_ui()
    
    with tab3:
        sync_status_ui()
    
    with tab4:
        settings_ui()


def create_portable_database_ui():
    """UI for creating a portable database for field operations"""
    
    st.header("Create Portable Database")
    st.write("""
    Create a self-contained SQLite database for field operations. This database will include:
    - All reference data (vessels, core types, wire types)
    - Selected cruises and their associated cores, sections, and files
    """)
    
    db_manager = get_database_manager()
    
    # Only allow creation when connected to PostgreSQL
    if db_manager.is_portable_mode:
        st.warning("⚠️ You are currently in portable mode. Switch to connected mode to create a new portable database.")
        if st.button("Switch to Connected Mode"):
            if db_manager.switch_mode(DatabaseMode.POSTGRES):
                st.success("Switched to connected mode!")
                st.rerun()
            else:
                st.error("Failed to connect to PostgreSQL server.")
        return
    
    # Cruise selection
    st.subheader("Select Cruises to Export")
    
    try:
        # Fetch available cruises
        from db_util import get_connection
        with get_connection() as conn:
            from sqlalchemy import text
            cruises_query = """
                SELECT cr.cruise_id, cr.cruise_name, v.vessel_name, 
                       COUNT(DISTINCT c.core_id) as core_count
                FROM cruises cr
                LEFT JOIN vessels v ON cr.vessel_id = v.vessel_id
                LEFT JOIN cores c ON cr.cruise_id = c.cruise_id
                GROUP BY cr.cruise_id, cr.cruise_name, v.vessel_name
                ORDER BY cr.cruise_name
            """
            cruises = conn.execute(text(cruises_query)).fetchall()
        
        if not cruises:
            st.warning("No cruises found in the database.")
            return
        
        # Display cruises with selection
        st.write("Select the cruises you want to include in the portable database:")
        
        # Create selection UI
        selected_cruises = []
        for cruise in cruises:
            cruise_id, cruise_name, vessel_name, core_count = cruise
            label = f"{cruise_name}"
            if vessel_name:
                label += f" ({vessel_name})"
            label += f" - {core_count} cores"
            
            if st.checkbox(label, key=f"cruise_{cruise_id}"):
                selected_cruises.append(cruise_id)
        
        # Option to select all
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Select All"):
                st.session_state.select_all_cruises = True
                st.rerun()
        with col2:
            if st.button("Clear Selection"):
                st.session_state.select_all_cruises = False
                st.rerun()
        
        st.divider()
        
        # Output configuration
        st.subheader("Output Configuration")
        
        default_filename = f"portable_sediment_{datetime.now().strftime('%Y%m%d')}.db"
        output_filename = st.text_input("Database filename", value=default_filename)
        
        # Ensure it has .db extension
        if not output_filename.endswith('.db'):
            output_filename += '.db'
        
        # Create button
        st.divider()
        
        if st.button("🚀 Create Portable Database", type="primary"):
            if not selected_cruises:
                st.warning("Please select at least one cruise to export.")
            else:
                with st.spinner("Creating portable database..."):
                    try:
                        sync_manager = SyncManager()
                        results = sync_manager.prepare_for_field_work(
                            cruise_ids=selected_cruises,
                            output_path=output_filename
                        )
                        
                        if results["success"]:
                            st.success(f"✅ Portable database created: `{output_filename}`")
                            
                            # Show export summary
                            st.subheader("Export Summary")
                            for table, count in results["exported_counts"].items():
                                st.write(f"• **{table}:** {count} records")
                            
                            # Download button
                            if os.path.exists(output_filename):
                                with open(output_filename, 'rb') as f:
                                    st.download_button(
                                        label="📥 Download Database File",
                                        data=f,
                                        file_name=output_filename,
                                        mime="application/octet-stream"
                                    )
                        else:
                            st.error("Failed to create portable database")
                            for error in results.get("errors", []):
                                st.error(error)
                                
                    except Exception as e:
                        st.error(f"Error creating portable database: {str(e)}")
                        
    except Exception as e:
        st.error(f"Error connecting to database: {str(e)}")
        st.info("Make sure you're connected to the PostgreSQL server.")


def sync_to_server_ui():
    """UI for syncing a portable database back to the server"""
    
    st.header("Sync Portable Database to Server")
    st.write("""
    Import data from a portable SQLite database back to the central PostgreSQL server.
    This will upload all new and modified records created during field operations.
    """)
    
    db_manager = get_database_manager()
    
    # Check if we can connect to PostgreSQL
    if db_manager.is_portable_mode:
        st.warning("⚠️ Currently in portable mode. Attempting to connect to server...")
        
    # File upload option
    st.subheader("Upload Portable Database")
    
    uploaded_file = st.file_uploader(
        "Select portable database file to sync",
        type=['db'],
        help="Upload the SQLite database file created for field operations"
    )
    
    # Or select existing file
    st.write("**Or select an existing file:**")
    
    # List .db files in current directory
    db_files = [f for f in os.listdir('.') if f.endswith('.db')]
    if db_files:
        selected_file = st.selectbox(
            "Select database file",
            [""] + db_files
        )
    else:
        selected_file = ""
        st.info("No .db files found in current directory")
    
    # Conflict resolution strategy
    st.subheader("Conflict Resolution")
    conflict_strategy = st.radio(
        "How should conflicts be handled?",
        [
            ("local_wins", "Local Wins - Field data takes priority"),
            ("server_wins", "Server Wins - Server data takes priority"),
            ("manual", "Manual Review - Flag conflicts for review")
        ],
        format_func=lambda x: x[1]
    )
    
    st.divider()
    
    # Determine which file to use
    sync_file = None
    if uploaded_file:
        # Save uploaded file temporarily
        temp_path = f"temp_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        with open(temp_path, 'wb') as f:
            f.write(uploaded_file.getvalue())
        sync_file = temp_path
        st.info(f"Using uploaded file: {uploaded_file.name}")
    elif selected_file:
        sync_file = selected_file
        st.info(f"Using selected file: {selected_file}")
    
    # Preview sync status before syncing
    if sync_file:
        st.subheader("Preview")
        status = get_portable_status(sync_file)
        
        if status.get("error"):
            st.error(f"Error reading database: {status['error']}")
        else:
            st.write(f"**Last sync:** {status.get('last_sync', 'Never')}")
            st.write(f"**Total pending records:** {status.get('total_pending', 0)}")
            
            if status.get('pending_records'):
                st.write("**Pending records by table:**")
                for table, count in status['pending_records'].items():
                    if count > 0:
                        st.write(f"  • {table}: {count}")
    
    # Sync button
    if st.button("🔄 Sync to Server", type="primary", disabled=not sync_file):
        if sync_file:
            with st.spinner("Syncing to server..."):
                try:
                    sync_manager = SyncManager()
                    
                    # Map conflict strategy
                    conflict_map = {
                        "local_wins": ConflictResolution.LOCAL_WINS,
                        "server_wins": ConflictResolution.SERVER_WINS,
                        "manual": ConflictResolution.MANUAL
                    }
                    
                    results = sync_manager.sync_from_field(
                        sqlite_path=sync_file,
                        conflict_resolution=conflict_map.get(conflict_strategy[0], ConflictResolution.LOCAL_WINS)
                    )
                    
                    if results["success"]:
                        st.success("✅ Sync completed successfully!")
                        
                        # Show import summary
                        st.subheader("Sync Summary")
                        for table, count in results.get("imported_counts", {}).items():
                            if count > 0:
                                st.write(f"• **{table}:** {count} records imported")
                        
                        if results.get("conflicts"):
                            st.warning(f"⚠️ {len(results['conflicts'])} conflicts detected")
                            with st.expander("View Conflicts"):
                                for conflict in results["conflicts"]:
                                    st.json(conflict)
                    else:
                        st.error("Sync completed with errors")
                        for error in results.get("errors", []):
                            st.error(error)
                            
                except Exception as e:
                    st.error(f"Error during sync: {str(e)}")
                    
                finally:
                    # Clean up temp file if created
                    if uploaded_file and os.path.exists(temp_path):
                        os.remove(temp_path)


def sync_status_ui():
    """UI for viewing sync status of current or selected database"""
    
    st.header("Sync Status")
    
    db_manager = get_database_manager()
    
    # Current database status
    st.subheader("Current Database")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if db_manager.is_portable_mode:
            st.metric("Mode", "Portable (SQLite)", delta="Offline")
        else:
            st.metric("Mode", "Connected (PostgreSQL)", delta="Online")
    
    with col2:
        status = db_manager.get_sync_status()
        total_pending = sum(status.get("pending_counts", {}).values())
        st.metric("Pending Records", total_pending)
    
    # Detailed status
    if status.get("pending_counts"):
        st.subheader("Pending Records by Table")
        for table, count in status["pending_counts"].items():
            if count > 0:
                st.progress(min(count / 100, 1.0))
                st.write(f"**{table}:** {count} records pending")
    
    # Check a specific database file
    st.divider()
    st.subheader("Check Portable Database Status")
    
    db_files = [f for f in os.listdir('.') if f.endswith('.db')]
    if db_files:
        selected_db = st.selectbox("Select database to check", [""] + db_files)
        
        if selected_db:
            status = get_portable_status(selected_db)
            
            st.write(f"**Database:** {selected_db}")
            st.write(f"**Exists:** {'Yes' if status.get('database_exists') else 'No'}")
            st.write(f"**Last Sync:** {status.get('last_sync', 'Never')}")
            st.write(f"**Total Pending:** {status.get('total_pending', 0)}")
            
            if status.get('pending_records'):
                with st.expander("Pending Records Details"):
                    for table, count in status['pending_records'].items():
                        st.write(f"• {table}: {count} pending, {status.get('synced_records', {}).get(table, 0)} synced")
    else:
        st.info("No portable database files found in current directory.")


def settings_ui():
    """UI for portable database settings"""
    
    st.header("Settings")
    
    db_manager = get_database_manager()
    
    # Mode switching
    st.subheader("Database Mode")
    
    current_mode = "Portable (SQLite)" if db_manager.is_portable_mode else "Connected (PostgreSQL)"
    st.write(f"**Current mode:** {current_mode}")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🌐 Switch to Connected Mode", 
                    disabled=db_manager.is_connected_mode):
            if db_manager.switch_mode(DatabaseMode.POSTGRES):
                st.success("Switched to connected mode!")
                st.rerun()
            else:
                st.error("Failed to connect to PostgreSQL. Check your connection settings.")
    
    with col2:
        if st.button("📱 Switch to Portable Mode", 
                    disabled=db_manager.is_portable_mode):
            # Select which database to use
            db_files = [f for f in os.listdir('.') if f.endswith('.db')]
            if db_files:
                if db_manager.switch_mode(DatabaseMode.SQLITE):
                    st.success("Switched to portable mode!")
                    st.rerun()
            else:
                st.warning("No portable database found. Create one first.")
    
    st.divider()
    
    # Environment settings display
    st.subheader("Environment Configuration")
    
    st.write("**PostgreSQL URL:**")
    postgres_url = os.getenv("DATABASE_URL", "postgresql://postgres:***@localhost/sediment_cores")
    # Hide password
    display_url = postgres_url.split('@')[0].rsplit(':', 1)[0] + ':***@' + postgres_url.split('@')[1] if '@' in postgres_url else postgres_url
    st.code(display_url)
    
    st.write("**SQLite Path:**")
    sqlite_path = os.getenv("SQLITE_DATABASE_PATH", "portable_sediment.db")
    st.code(sqlite_path)
    
    st.write("**Database Mode Override:**")
    mode_override = os.getenv("SEDIMENT_DB_MODE", "auto")
    st.code(mode_override)
    
    st.info("""
    **Environment Variables:**
    - `DATABASE_URL`: PostgreSQL connection string
    - `SQLITE_DATABASE_PATH`: Path to SQLite database file  
    - `SEDIMENT_DB_MODE`: Force mode (`postgres`, `sqlite`, or `auto`)
    """)
    
    st.divider()
    
    # Help section
    st.subheader("📖 Usage Guide")
    
    with st.expander("How to use the portable database system"):
        st.markdown("""
        ### Creating a Portable Database
        
        1. Connect to the PostgreSQL server (the default when online)
        2. Go to "Create Portable DB" tab
        3. Select the cruises you want to take to the field
        4. Download the generated .db file
        5. Copy the file to your field laptop
        
        ### Working in the Field (Offline)
        
        1. Set environment variable: `SEDIMENT_DB_MODE=sqlite`
        2. Set `SQLITE_DATABASE_PATH` to your database file
        3. Run the Streamlit apps as normal
        4. All new data will be saved to the SQLite database
        
        ### Syncing Back to Server
        
        1. Return from field with your portable database
        2. Go to "Sync to Server" tab
        3. Upload or select your portable database file
        4. Choose conflict resolution strategy
        5. Click "Sync to Server"
        
        ### Notes
        
        - Reference data (vessels, core types) is read-only in portable mode
        - New cruises, cores, sections, and file metadata can be created offline
        - Conflicts are flagged when the same record exists on both systems
        """)


# Entry point for running as standalone page
if __name__ == "__main__":
    st.set_page_config(
        page_title="Portable Database Manager",
        page_icon="📱",
        layout="wide"
    )
    portable_database_manager()
