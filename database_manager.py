"""
Database Manager - Abstraction layer for PostgreSQL and SQLite databases.

This module provides a unified interface for database operations, supporting both:
- PostgreSQL: The central production database
- SQLite: A portable database for offline/remote field operations

The manager handles:
- Connection management for both database types
- Schema initialization for SQLite
- Mode switching between portable and connected modes
"""

import os
import sqlite3
from sqlalchemy import create_engine, text, event
from sqlalchemy.pool import StaticPool
from contextlib import contextmanager


class DatabaseMode:
    """Enum-like class for database modes"""
    POSTGRES = "postgres"
    SQLITE = "sqlite"


class DatabaseManager:
    """
    Manages database connections and operations for both PostgreSQL and SQLite.
    
    This class provides a singleton-like pattern for managing database connections
    across the application, allowing seamless switching between the central
    PostgreSQL database and a portable SQLite database for field operations.
    """
    
    _instance = None
    _engine = None
    _mode = None
    
    # Default connection strings
    DEFAULT_POSTGRES_URL = "postgresql://postgres:madmaxfuryroad@localhost/sediment_cores"
    DEFAULT_SQLITE_PATH = "portable_sediment.db"
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._mode = None
        self._engine = None
        self._postgres_url = os.getenv("DATABASE_URL", self.DEFAULT_POSTGRES_URL)
        self._sqlite_path = os.getenv("SQLITE_DATABASE_PATH", self.DEFAULT_SQLITE_PATH)
        
    @property
    def mode(self):
        """Get the current database mode"""
        return self._mode
    
    @property
    def engine(self):
        """Get the current database engine"""
        return self._engine
    
    @property
    def is_portable_mode(self):
        """Check if currently in portable SQLite mode"""
        return self._mode == DatabaseMode.SQLITE
    
    @property
    def is_connected_mode(self):
        """Check if currently in connected PostgreSQL mode"""
        return self._mode == DatabaseMode.POSTGRES
    
    def initialize(self, mode=None, force=False):
        """
        Initialize the database manager with the specified mode.
        
        Args:
            mode: DatabaseMode.POSTGRES or DatabaseMode.SQLITE
            force: If True, reinitialize even if already initialized
        
        Returns:
            bool: True if initialization successful
        """
        if self._engine is not None and not force:
            return True
        
        # Auto-detect mode if not specified
        if mode is None:
            mode = self._detect_mode()
        
        self._mode = mode
        
        if mode == DatabaseMode.POSTGRES:
            return self._initialize_postgres()
        elif mode == DatabaseMode.SQLITE:
            return self._initialize_sqlite()
        else:
            raise ValueError(f"Unknown database mode: {mode}")
    
    def _detect_mode(self):
        """
        Auto-detect the appropriate database mode.
        
        Checks for:
        1. Environment variable SEDIMENT_DB_MODE
        2. Presence of a portable database file
        3. Ability to connect to PostgreSQL
        """
        # Check environment variable first
        env_mode = os.getenv("SEDIMENT_DB_MODE", "").lower()
        if env_mode == "sqlite" or env_mode == "portable":
            return DatabaseMode.SQLITE
        elif env_mode == "postgres" or env_mode == "postgresql":
            return DatabaseMode.POSTGRES
        
        # If portable database exists, use it
        if os.path.exists(self._sqlite_path):
            return DatabaseMode.SQLITE
        
        # Default to PostgreSQL
        return DatabaseMode.POSTGRES
    
    def _initialize_postgres(self):
        """Initialize PostgreSQL connection"""
        try:
            self._engine = create_engine(self._postgres_url)
            # Test connection
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            print(f"Failed to connect to PostgreSQL: {e}")
            return False
    
    def _initialize_sqlite(self):
        """Initialize SQLite connection and schema"""
        try:
            # Create SQLite engine with appropriate settings
            self._engine = create_engine(
                f"sqlite:///{self._sqlite_path}",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool
            )
            
            # Enable foreign keys for SQLite
            @event.listens_for(self._engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
            
            # Initialize schema if database is new
            self._initialize_sqlite_schema()
            
            return True
        except Exception as e:
            print(f"Failed to initialize SQLite: {e}")
            return False
    
    def _initialize_sqlite_schema(self):
        """Create SQLite schema to mirror PostgreSQL structure"""
        schema_sql = """
        -- Vessels table
        CREATE TABLE IF NOT EXISTS vessels (
            vessel_id INTEGER PRIMARY KEY AUTOINCREMENT,
            vessel_name TEXT NOT NULL UNIQUE,
            vessel_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Core types table
        CREATE TABLE IF NOT EXISTS core_types (
            core_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
            core_type_name TEXT NOT NULL UNIQUE,
            required_fields TEXT,  -- JSON array of required field names
            description TEXT
        );
        
        -- Wire types table
        CREATE TABLE IF NOT EXISTS wire (
            wire_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
            wire_type TEXT NOT NULL UNIQUE
        );
        
        -- Cruises table
        CREATE TABLE IF NOT EXISTS cruises (
            cruise_id INTEGER PRIMARY KEY AUTOINCREMENT,
            cruise_name TEXT NOT NULL UNIQUE,
            vessel_id INTEGER REFERENCES vessels(vessel_id),
            chief_scientist TEXT,
            additional_PI TEXT,
            start_date DATE,
            end_date DATE,
            departure_port TEXT,
            arrival_port TEXT,
            cruise_description TEXT,
            funding_agency TEXT,
            cruise_report_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sync_status TEXT DEFAULT 'pending'
        );
        
        -- Cores table
        CREATE TABLE IF NOT EXISTS cores (
            core_id INTEGER PRIMARY KEY AUTOINCREMENT,
            core_name TEXT NOT NULL UNIQUE,
            vessel_id INTEGER REFERENCES vessels(vessel_id),
            cruise_id INTEGER REFERENCES cruises(cruise_id),
            leg TEXT,
            date DATE,
            station TEXT,
            water_depth_m REAL,
            latitude REAL,
            longitude REAL,
            observer TEXT,
            core_type_id INTEGER REFERENCES core_types(core_type_id),
            time_launched TIME,
            time_on_bottom TIME,
            time_recovered TIME,
            wire_out_on_bottom REAL,
            max_wire_out REAL,
            impact_speed REAL,
            tension_at_surface REAL,
            tension_near_bottom REAL,
            tension_on_bottom REAL,
            pullout_tension REAL,
            notes TEXT,
            wire_type_id INTEGER REFERENCES wire(wire_type_id),
            data_entry_remarks TEXT,
            -- Dynamic fields for different core types
            core_length REAL,
            liner_length REAL,
            trigger_core_length REAL,
            penetration REAL,
            recovery REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sync_status TEXT DEFAULT 'pending'
        );
        
        -- Sections table
        CREATE TABLE IF NOT EXISTS sections (
            section_id INTEGER PRIMARY KEY AUTOINCREMENT,
            core_id INTEGER NOT NULL REFERENCES cores(core_id),
            section_number INTEGER NOT NULL,
            section_length REAL,
            top_cum_length REAL,
            bottom_cum_length REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sync_status TEXT DEFAULT 'pending',
            UNIQUE(core_id, section_number)
        );
        
        -- MSCL files table
        CREATE TABLE IF NOT EXISTS mscl_files (
            file_id INTEGER PRIMARY KEY AUTOINCREMENT,
            core_id INTEGER NOT NULL REFERENCES cores(core_id),
            file_name TEXT NOT NULL,
            file_path TEXT,
            file_type TEXT,
            remarks TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sync_status TEXT DEFAULT 'pending'
        );
        
        -- Sensor files table
        CREATE TABLE IF NOT EXISTS sensor_files (
            file_id INTEGER PRIMARY KEY AUTOINCREMENT,
            core_id INTEGER NOT NULL REFERENCES cores(core_id),
            file_name TEXT NOT NULL,
            file_path TEXT,
            file_type TEXT,
            sensor_location TEXT,
            sensor_type TEXT,
            remarks TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sync_status TEXT DEFAULT 'pending'
        );
        
        -- Winch data table
        CREATE TABLE IF NOT EXISTS winch_data (
            winch_id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL,
            file_path TEXT,
            cruise_id INTEGER REFERENCES cruises(cruise_id),
            start_time TEXT,
            end_time TEXT,
            settings TEXT,  -- JSON
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sync_status TEXT DEFAULT 'pending'
        );
        
        -- Sync log table to track synchronization operations
        CREATE TABLE IF NOT EXISTS sync_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sync_direction TEXT,  -- 'upload', 'download', 'merge'
            table_name TEXT,
            records_synced INTEGER,
            status TEXT,
            details TEXT
        );
        
        -- Create indexes for performance
        CREATE INDEX IF NOT EXISTS idx_cores_cruise ON cores(cruise_id);
        CREATE INDEX IF NOT EXISTS idx_cores_vessel ON cores(vessel_id);
        CREATE INDEX IF NOT EXISTS idx_sections_core ON sections(core_id);
        CREATE INDEX IF NOT EXISTS idx_mscl_core ON mscl_files(core_id);
        CREATE INDEX IF NOT EXISTS idx_sensor_core ON sensor_files(core_id);
        CREATE INDEX IF NOT EXISTS idx_winch_cruise ON winch_data(cruise_id);
        CREATE INDEX IF NOT EXISTS idx_cores_sync ON cores(sync_status);
        CREATE INDEX IF NOT EXISTS idx_cruises_sync ON cruises(sync_status);
        """
        
        with self._engine.connect() as conn:
            # Execute each statement separately for SQLite
            for statement in schema_sql.split(';'):
                statement = statement.strip()
                if statement:
                    conn.execute(text(statement))
            conn.commit()
    
    @contextmanager
    def get_connection(self):
        """
        Get a database connection as a context manager.
        
        Usage:
            with db_manager.get_connection() as conn:
                result = conn.execute(query)
        """
        if self._engine is None:
            self.initialize()
        
        conn = self._engine.connect()
        try:
            yield conn
        finally:
            conn.close()
    
    def switch_mode(self, new_mode):
        """
        Switch between database modes.
        
        Args:
            new_mode: DatabaseMode.POSTGRES or DatabaseMode.SQLITE
        
        Returns:
            bool: True if switch successful
        """
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
        
        return self.initialize(mode=new_mode, force=True)
    
    def create_portable_database(self, output_path=None):
        """
        Create a new portable SQLite database for field operations.
        
        Args:
            output_path: Path for the new database file
        
        Returns:
            str: Path to the created database
        """
        if output_path:
            self._sqlite_path = output_path
        
        # Ensure we're creating a new database
        if os.path.exists(self._sqlite_path):
            os.remove(self._sqlite_path)
        
        # Initialize SQLite database
        original_mode = self._mode
        original_engine = self._engine
        
        self._engine = None
        self._initialize_sqlite()
        
        # Restore original connection if needed
        if original_mode == DatabaseMode.POSTGRES:
            sqlite_path = self._sqlite_path
            self._engine = original_engine
            self._mode = original_mode
            return sqlite_path
        
        return self._sqlite_path
    
    def get_sync_status(self):
        """
        Get the synchronization status of the current database.
        
        Returns:
            dict: Status information including pending records counts
        """
        if self._mode != DatabaseMode.SQLITE:
            return {"mode": self._mode, "sync_required": False}
        
        status = {
            "mode": self._mode,
            "sync_required": False,
            "pending_counts": {}
        }
        
        tables_with_sync = ["cruises", "cores", "sections", "mscl_files", "sensor_files", "winch_data"]
        
        with self.get_connection() as conn:
            for table in tables_with_sync:
                try:
                    result = conn.execute(
                        text(f"SELECT COUNT(*) FROM {table} WHERE sync_status = 'pending'")
                    ).scalar()
                    if result > 0:
                        status["pending_counts"][table] = result
                        status["sync_required"] = True
                except Exception:
                    pass
        
        return status


# Global instance for backward compatibility
_db_manager = None


def get_database_manager():
    """Get the global DatabaseManager instance"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def get_connection():
    """
    Backward-compatible function to get a database connection.
    
    This maintains compatibility with existing code that uses:
        with get_connection() as conn:
            ...
    """
    manager = get_database_manager()
    if manager.engine is None:
        manager.initialize()
    return manager.get_connection()


def get_engine():
    """Get the SQLAlchemy engine"""
    manager = get_database_manager()
    if manager.engine is None:
        manager.initialize()
    return manager.engine
