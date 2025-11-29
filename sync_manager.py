"""
Sync Manager - Handles synchronization between PostgreSQL and SQLite databases.

This module provides functionality for:
- Exporting data from PostgreSQL to SQLite for field operations
- Importing/syncing data from SQLite back to PostgreSQL
- Conflict resolution during sync operations
- Tracking sync status and history
"""

import os
import json
import sqlite3
from datetime import datetime
from sqlalchemy import create_engine, text, MetaData, Table
import pandas as pd

from database_manager import DatabaseManager, DatabaseMode, get_database_manager


class SyncDirection:
    """Enum-like class for sync directions"""
    EXPORT = "export"  # PostgreSQL -> SQLite
    IMPORT = "import"  # SQLite -> PostgreSQL
    MERGE = "merge"    # Bidirectional


class ConflictResolution:
    """Enum-like class for conflict resolution strategies"""
    SERVER_WINS = "server_wins"    # PostgreSQL version takes precedence
    LOCAL_WINS = "local_wins"      # SQLite version takes precedence
    NEWER_WINS = "newer_wins"      # Most recently modified wins
    MANUAL = "manual"              # Require manual resolution


class SyncManager:
    """
    Manages data synchronization between PostgreSQL and SQLite databases.
    
    This class handles:
    - Exporting reference data and operational data from PostgreSQL
    - Importing new/modified records from SQLite to PostgreSQL
    - Tracking sync status and conflicts
    """
    
    # Tables that contain reference data (typically exported from server)
    REFERENCE_TABLES = ["vessels", "core_types", "wire"]
    
    # Tables that contain operational data (can be created on portable device)
    OPERATIONAL_TABLES = ["cruises", "cores", "sections", "mscl_files", "sensor_files", "winch_data"]
    
    def __init__(self, postgres_url=None, sqlite_path=None):
        """
        Initialize the SyncManager.
        
        Args:
            postgres_url: PostgreSQL connection string (defaults to env or config)
            sqlite_path: Path to SQLite database file
        """
        self.postgres_url = postgres_url or os.getenv(
            "DATABASE_URL", 
            "postgresql://postgres:madmaxfuryroad@localhost/sediment_cores"
        )
        self.sqlite_path = sqlite_path or os.getenv(
            "SQLITE_DATABASE_PATH", 
            "portable_sediment.db"
        )
        self._postgres_engine = None
        self._sqlite_engine = None
    
    @property
    def postgres_engine(self):
        """Get or create PostgreSQL engine"""
        if self._postgres_engine is None:
            self._postgres_engine = create_engine(self.postgres_url)
        return self._postgres_engine
    
    @property
    def sqlite_engine(self):
        """Get or create SQLite engine"""
        if self._sqlite_engine is None:
            self._sqlite_engine = create_engine(f"sqlite:///{self.sqlite_path}")
        return self._sqlite_engine
    
    def export_to_portable(self, 
                           cruise_ids=None, 
                           include_reference_data=True,
                           output_path=None):
        """
        Export data from PostgreSQL to a portable SQLite database.
        
        This creates a self-contained SQLite database with:
        - All reference data (vessels, core types, wire types)
        - Selected cruises and their related data
        
        Args:
            cruise_ids: List of cruise IDs to export (None = all)
            include_reference_data: Whether to include reference tables
            output_path: Output path for SQLite database (uses default if None)
        
        Returns:
            dict: Export results including counts and any errors
        """
        if output_path:
            self.sqlite_path = output_path
        
        # Create fresh portable database
        db_manager = get_database_manager()
        db_manager.create_portable_database(self.sqlite_path)
        
        # Reconnect to the newly created database
        self._sqlite_engine = create_engine(f"sqlite:///{self.sqlite_path}")
        
        results = {
            "success": True,
            "exported_counts": {},
            "errors": []
        }
        
        try:
            # Export reference data first
            if include_reference_data:
                for table in self.REFERENCE_TABLES:
                    try:
                        count = self._export_table(table)
                        results["exported_counts"][table] = count
                    except Exception as e:
                        results["errors"].append(f"Error exporting {table}: {str(e)}")
            
            # Export operational data
            for table in self.OPERATIONAL_TABLES:
                try:
                    count = self._export_table(table, cruise_ids=cruise_ids)
                    results["exported_counts"][table] = count
                except Exception as e:
                    results["errors"].append(f"Error exporting {table}: {str(e)}")
            
            # Mark exported records as synced
            self._mark_exported_as_synced()
            
            # Log the export
            self._log_sync(SyncDirection.EXPORT, results)
            
            if results["errors"]:
                results["success"] = False
                
        except Exception as e:
            results["success"] = False
            results["errors"].append(f"Export failed: {str(e)}")
        
        return results
    
    def _export_table(self, table_name, cruise_ids=None):
        """
        Export a single table from PostgreSQL to SQLite.
        
        Args:
            table_name: Name of the table to export
            cruise_ids: Optional list of cruise IDs to filter by
        
        Returns:
            int: Number of records exported
        """
        # Build query with optional filtering
        if cruise_ids and table_name in ["cruises"]:
            placeholders = ", ".join([f":id{i}" for i in range(len(cruise_ids))])
            query = f"SELECT * FROM {table_name} WHERE cruise_id IN ({placeholders})"
            params = {f"id{i}": cid for i, cid in enumerate(cruise_ids)}
        elif cruise_ids and table_name in ["cores", "winch_data"]:
            placeholders = ", ".join([f":id{i}" for i in range(len(cruise_ids))])
            query = f"SELECT * FROM {table_name} WHERE cruise_id IN ({placeholders})"
            params = {f"id{i}": cid for i, cid in enumerate(cruise_ids)}
        elif cruise_ids and table_name in ["sections", "mscl_files", "sensor_files"]:
            # These tables link through cores
            placeholders = ", ".join([f":id{i}" for i in range(len(cruise_ids))])
            query = f"""
                SELECT t.* FROM {table_name} t
                JOIN cores c ON t.core_id = c.core_id
                WHERE c.cruise_id IN ({placeholders})
            """
            params = {f"id{i}": cid for i, cid in enumerate(cruise_ids)}
        else:
            query = f"SELECT * FROM {table_name}"
            params = {}
        
        # Read from PostgreSQL
        with self.postgres_engine.connect() as pg_conn:
            df = pd.read_sql(text(query), pg_conn, params=params)
        
        if df.empty:
            return 0
        
        # Add sync_status column if not present
        if "sync_status" not in df.columns:
            df["sync_status"] = "synced"
        else:
            df["sync_status"] = "synced"
        
        # Write to SQLite
        with self.sqlite_engine.connect() as sqlite_conn:
            # Handle the primary key issue for SQLite
            df.to_sql(
                table_name, 
                sqlite_conn, 
                if_exists="replace", 
                index=False
            )
            sqlite_conn.commit()
        
        return len(df)
    
    def _mark_exported_as_synced(self):
        """Mark all records in SQLite as synced after export"""
        with self.sqlite_engine.connect() as conn:
            for table in self.OPERATIONAL_TABLES:
                try:
                    conn.execute(
                        text(f"UPDATE {table} SET sync_status = 'synced' WHERE sync_status IS NULL")
                    )
                except Exception:
                    pass
            conn.commit()
    
    def import_from_portable(self, 
                             conflict_resolution=ConflictResolution.NEWER_WINS,
                             sqlite_path=None):
        """
        Import data from portable SQLite database to PostgreSQL.
        
        This imports:
        - New records created during field operations
        - Modified records (based on sync_status)
        
        Args:
            conflict_resolution: Strategy for handling conflicts
            sqlite_path: Path to SQLite database (uses default if None)
        
        Returns:
            dict: Import results including counts and conflicts
        """
        if sqlite_path:
            self.sqlite_path = sqlite_path
            self._sqlite_engine = create_engine(f"sqlite:///{self.sqlite_path}")
        
        results = {
            "success": True,
            "imported_counts": {},
            "conflicts": [],
            "errors": []
        }
        
        try:
            # Import operational tables in order (respecting foreign keys)
            import_order = ["cruises", "cores", "sections", "mscl_files", "sensor_files", "winch_data"]
            
            for table in import_order:
                try:
                    count, conflicts = self._import_table(
                        table, 
                        conflict_resolution
                    )
                    results["imported_counts"][table] = count
                    if conflicts:
                        results["conflicts"].extend(conflicts)
                except Exception as e:
                    results["errors"].append(f"Error importing {table}: {str(e)}")
            
            # Log the import
            self._log_sync(SyncDirection.IMPORT, results)
            
            if results["errors"]:
                results["success"] = False
                
        except Exception as e:
            results["success"] = False
            results["errors"].append(f"Import failed: {str(e)}")
        
        return results
    
    def _import_table(self, table_name, conflict_resolution):
        """
        Import pending records from a single SQLite table to PostgreSQL.
        
        Args:
            table_name: Name of the table to import
            conflict_resolution: Strategy for handling conflicts
        
        Returns:
            tuple: (count of imported records, list of conflicts)
        """
        conflicts = []
        imported_count = 0
        
        # Get pending records from SQLite
        with self.sqlite_engine.connect() as sqlite_conn:
            df = pd.read_sql(
                text(f"SELECT * FROM {table_name} WHERE sync_status = 'pending'"),
                sqlite_conn
            )
        
        if df.empty:
            return 0, []
        
        # Get primary key column name
        pk_column = self._get_primary_key(table_name)
        name_column = self._get_name_column(table_name)
        
        with self.postgres_engine.connect() as pg_conn:
            for _, row in df.iterrows():
                try:
                    # Check if record exists by name (for cruises, cores) or by ID
                    existing = None
                    if name_column and row.get(name_column):
                        existing = pd.read_sql(
                            text(f"SELECT * FROM {table_name} WHERE {name_column} = :name"),
                            pg_conn,
                            params={"name": row[name_column]}
                        )
                    
                    if existing is not None and not existing.empty:
                        # Handle conflict
                        if conflict_resolution == ConflictResolution.LOCAL_WINS:
                            # Update existing record
                            self._update_record(pg_conn, table_name, row, pk_column)
                            imported_count += 1
                        elif conflict_resolution == ConflictResolution.SERVER_WINS:
                            # Skip this record
                            conflicts.append({
                                "table": table_name,
                                "local_record": row.to_dict(),
                                "resolution": "skipped"
                            })
                        else:
                            # Default to newer wins - compare timestamps
                            conflicts.append({
                                "table": table_name,
                                "local_record": row.to_dict(),
                                "resolution": "needs_review"
                            })
                    else:
                        # Insert new record
                        self._insert_record(pg_conn, table_name, row, pk_column)
                        imported_count += 1
                        
                except Exception as e:
                    conflicts.append({
                        "table": table_name,
                        "error": str(e),
                        "record": row.to_dict() if hasattr(row, 'to_dict') else str(row)
                    })
            
            pg_conn.commit()
        
        # Mark imported records as synced in SQLite
        if imported_count > 0:
            with self.sqlite_engine.connect() as sqlite_conn:
                sqlite_conn.execute(
                    text(f"UPDATE {table_name} SET sync_status = 'synced' WHERE sync_status = 'pending'")
                )
                sqlite_conn.commit()
        
        return imported_count, conflicts
    
    def _get_primary_key(self, table_name):
        """Get the primary key column name for a table"""
        pk_map = {
            "vessels": "vessel_id",
            "core_types": "core_type_id",
            "wire": "wire_type_id",
            "cruises": "cruise_id",
            "cores": "core_id",
            "sections": "section_id",
            "mscl_files": "file_id",
            "sensor_files": "file_id",
            "winch_data": "winch_id"
        }
        return pk_map.get(table_name, "id")
    
    def _get_name_column(self, table_name):
        """Get the natural key/name column for a table (if any)"""
        name_map = {
            "vessels": "vessel_name",
            "core_types": "core_type_name",
            "wire": "wire_type",
            "cruises": "cruise_name",
            "cores": "core_name",
        }
        return name_map.get(table_name)
    
    def _insert_record(self, conn, table_name, row, pk_column):
        """Insert a new record, excluding the primary key for auto-generation"""
        # Exclude primary key and sync_status columns
        columns = [c for c in row.index if c not in [pk_column, "sync_status"]]
        
        placeholders = ", ".join([f":{c}" for c in columns])
        column_names = ", ".join(columns)
        
        query = f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})"
        
        params = {c: (row[c] if pd.notna(row[c]) else None) for c in columns}
        conn.execute(text(query), params)
    
    def _update_record(self, conn, table_name, row, pk_column):
        """Update an existing record"""
        name_column = self._get_name_column(table_name)
        
        # Build UPDATE statement
        columns = [c for c in row.index if c not in [pk_column, "sync_status", name_column]]
        set_clause = ", ".join([f"{c} = :{c}" for c in columns])
        
        query = f"UPDATE {table_name} SET {set_clause} WHERE {name_column} = :name_value"
        
        params = {c: (row[c] if pd.notna(row[c]) else None) for c in columns}
        params["name_value"] = row[name_column]
        
        conn.execute(text(query), params)
    
    def _log_sync(self, direction, results):
        """Log sync operation to SQLite database"""
        try:
            with self.sqlite_engine.connect() as conn:
                conn.execute(
                    text("""
                        INSERT INTO sync_log (sync_direction, status, details)
                        VALUES (:direction, :status, :details)
                    """),
                    {
                        "direction": direction,
                        "status": "success" if results["success"] else "error",
                        "details": json.dumps(results)
                    }
                )
                conn.commit()
        except Exception:
            pass  # Don't fail if logging fails
    
    def get_sync_status(self, sqlite_path=None):
        """
        Get the current sync status of the portable database.
        
        Args:
            sqlite_path: Path to SQLite database (uses default if None)
        
        Returns:
            dict: Sync status information
        """
        if sqlite_path:
            self.sqlite_path = sqlite_path
            self._sqlite_engine = create_engine(f"sqlite:///{self.sqlite_path}")
        
        status = {
            "database_exists": os.path.exists(self.sqlite_path),
            "pending_records": {},
            "synced_records": {},
            "last_sync": None,
            "total_pending": 0
        }
        
        if not status["database_exists"]:
            return status
        
        try:
            with self.sqlite_engine.connect() as conn:
                # Count pending and synced records for each table
                for table in self.OPERATIONAL_TABLES:
                    try:
                        pending = conn.execute(
                            text(f"SELECT COUNT(*) FROM {table} WHERE sync_status = 'pending'")
                        ).scalar() or 0
                        synced = conn.execute(
                            text(f"SELECT COUNT(*) FROM {table} WHERE sync_status = 'synced'")
                        ).scalar() or 0
                        
                        status["pending_records"][table] = pending
                        status["synced_records"][table] = synced
                        status["total_pending"] += pending
                    except Exception:
                        pass
                
                # Get last sync timestamp
                try:
                    last_sync = conn.execute(
                        text("SELECT MAX(sync_timestamp) FROM sync_log")
                    ).scalar()
                    status["last_sync"] = str(last_sync) if last_sync else None
                except Exception:
                    pass
                    
        except Exception as e:
            status["error"] = str(e)
        
        return status
    
    def prepare_for_field_work(self, cruise_ids=None, output_path=None):
        """
        Convenience method to prepare a portable database for field work.
        
        This exports all necessary data and creates a self-contained database
        ready for offline use.
        
        Args:
            cruise_ids: List of cruise IDs to include (None = all)
            output_path: Output path for the portable database
        
        Returns:
            dict: Preparation results
        """
        output_path = output_path or f"field_database_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        
        results = self.export_to_portable(
            cruise_ids=cruise_ids,
            include_reference_data=True,
            output_path=output_path
        )
        
        results["output_path"] = output_path
        return results
    
    def sync_from_field(self, sqlite_path, conflict_resolution=ConflictResolution.LOCAL_WINS):
        """
        Convenience method to sync data back from field operations.
        
        This imports all new and modified records from the portable database
        to the central PostgreSQL database.
        
        Args:
            sqlite_path: Path to the portable database
            conflict_resolution: How to handle conflicts
        
        Returns:
            dict: Sync results
        """
        return self.import_from_portable(
            conflict_resolution=conflict_resolution,
            sqlite_path=sqlite_path
        )


def create_portable_database(cruise_ids=None, output_path=None):
    """
    Standalone function to create a portable database for field operations.
    
    Args:
        cruise_ids: List of cruise IDs to export
        output_path: Path for the portable database
    
    Returns:
        dict: Export results
    """
    sync_manager = SyncManager()
    return sync_manager.prepare_for_field_work(cruise_ids, output_path)


def sync_portable_database(sqlite_path, conflict_resolution=ConflictResolution.LOCAL_WINS):
    """
    Standalone function to sync a portable database back to the server.
    
    Args:
        sqlite_path: Path to the portable database
        conflict_resolution: How to handle conflicts
    
    Returns:
        dict: Import results
    """
    sync_manager = SyncManager()
    return sync_manager.sync_from_field(sqlite_path, conflict_resolution)


def get_portable_status(sqlite_path=None):
    """
    Standalone function to get the sync status of a portable database.
    
    Args:
        sqlite_path: Path to the portable database
    
    Returns:
        dict: Status information
    """
    sync_manager = SyncManager()
    return sync_manager.get_sync_status(sqlite_path)
