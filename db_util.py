from sqlalchemy import create_engine, text
import pandas as pd
from datetime import date

# Database connection string
DB_URL = "postgresql://postgres:madmaxfuryroad@localhost/sediment_cores"

# Create a SQLAlchemy engine
engine = create_engine(DB_URL)

def get_connection():
    """Get a database connection."""
    return engine.connect()

def fetch_cores():
    """Fetch the cores table from the database."""
    query = "SELECT * FROM cores ORDER BY core_name"
    with get_connection() as conn:
        return pd.read_sql(query, conn)

def get_rbr_core_files():
    """Fetch RBR sensor core files from the database."""
    try:
        with engine.connect() as connection:
            query = """
                SELECT c.core_name, f.file_path
                FROM cores c
                JOIN files f ON c.core_id = f.core_id
                WHERE f.file_type = 'RBR Sensor';
            """
            df = pd.read_sql(query, connection)

            # Group file paths by core name
            core_files = df.groupby('core_name')['file_path'].apply(list).to_dict()

            # Return relative paths (full paths will be constructed in the calling script)
            return core_files
    except Exception as e:
        raise RuntimeError(f"Error fetching core/file data: {e}")
    
def fetch_dropdown_values():
    """Fetch dropdown values for vessels and core types."""
    with get_connection() as conn:
        # Fetch vessels
        vessels_query = text("SELECT vessel_id, vessel_name FROM vessels ORDER BY vessel_name;")
        vessels = conn.execute(vessels_query).fetchall()

        # Fetch core types
        core_types_query = text("SELECT core_type_id, core_type_name, required_fields FROM core_types ORDER BY core_type_name;")
        core_types = conn.execute(core_types_query).fetchall()

    return vessels, core_types

def get_dynamic_fields_metadata(core_type_id):
    """
    Fetch dynamic fields for the selected core type from the database.
    """
    with get_connection() as conn:
        # Use SQLAlchemy's conn.execute() and text() for the query
        query = text("SELECT required_fields FROM core_types WHERE core_type_id = :core_type_id")
        result = conn.execute(query, {"core_type_id": core_type_id}).fetchone()
        
        if result:
            # Return the required fields (assuming it's stored as JSON or a string)
            return result[0]
    return []

def fetch_last_record():
    """Fetch the most recent record from the cores table."""
    with get_connection() as conn:
        query = "SELECT * FROM cores ORDER BY core_id DESC LIMIT 1"
        result = conn.execute(query).fetchone()
        if result:
            # Convert the result to a dictionary
            return dict(result)
        return None

