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
                SELECT c.core_name, s.file_path
                FROM cores c
                JOIN sensor_files s ON c.core_id = s.core_id
                WHERE s.sensor_type ILIKE '%RBR%';
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
        query = text("SELECT * FROM cores ORDER BY core_id DESC LIMIT 1")
        result = conn.execute(query).fetchone()
        if result:
            # Use _asdict() to convert the Row object to a dictionary
            return result._asdict()
        return None

def get_mscl_core_files():
    """Fetch MSCL core files from the database."""
    try:
        with engine.connect() as connection:
            query = """
                SELECT c.core_name, m.file_path, m.file_name, m.remarks
                FROM cores c
                JOIN mscl_files m ON c.core_id = m.core_id
                ORDER BY c.core_name, m.file_name;
            """
            df = pd.read_sql(query, connection)
            return df
    except Exception as e:
        raise RuntimeError(f"Error fetching MSCL file data: {e}")

def get_sensor_core_files():
    """Fetch all sensor core files from the database."""
    try:
        with engine.connect() as connection:
            query = """
                SELECT c.core_name, s.file_path, s.file_name, s.sensor_type, s.sensor_location, s.remarks
                FROM cores c
                JOIN sensor_files s ON c.core_id = s.core_id
                ORDER BY c.core_name, s.file_name;
            """
            df = pd.read_sql(query, connection)
            return df
    except Exception as e:
        raise RuntimeError(f"Error fetching sensor file data: {e}")

def get_star_oddi_core_files():
    """Fetch Star Oddi sensor core files from the database."""
    try:
        with engine.connect() as connection:
            query = """
                SELECT c.core_name, s.file_path, s.file_name, s.sensor_location, s.remarks
                FROM cores c
                JOIN sensor_files s ON c.core_id = s.core_id
                WHERE s.sensor_type ILIKE '%Star%Oddi%';
            """
            df = pd.read_sql(query, connection)
            return df
    except Exception as e:
        raise RuntimeError(f"Error fetching Star Oddi file data: {e}")

def get_existing_sections(core_id):
    """Get existing sections for a core"""
    with get_connection() as conn:
        query = text("""
            SELECT section_number, section_length, top_cum_length, bottom_cum_length 
            FROM sections 
            WHERE core_id = :core_id 
            ORDER BY section_number
        """)
        result = conn.execute(query, {"core_id": core_id})
        return result.fetchall()

def get_cores_with_sections():
    """Get cores that have sections"""
    with get_connection() as conn:
        query = text("""
            SELECT DISTINCT c.core_id, c.core_name, c.cruise, COUNT(s.section_id) as section_count
            FROM cores c
            JOIN sections s ON c.core_id = s.core_id
            GROUP BY c.core_id, c.core_name, c.cruise
            ORDER BY c.cruise, c.core_name
        """)
        result = conn.execute(query)
        return result.fetchall()

def get_sections_for_core(core_id):
    """Get all sections for a specific core"""
    with get_connection() as conn:
        query = text("""
            SELECT section_id, section_number, section_length, top_cum_length, bottom_cum_length 
            FROM sections 
            WHERE core_id = :core_id 
            ORDER BY section_number
        """)
        result = conn.execute(query, {"core_id": core_id})
        return result.fetchall()

def insert_section(core_id, section_number, section_length, top_cum_length, bottom_cum_length):
    """Insert a new section into the database"""
    with get_connection() as conn:
        query = text("""
            INSERT INTO sections (core_id, section_number, section_length, top_cum_length, bottom_cum_length)
            VALUES (:core_id, :section_number, :section_length, :top_cum_length, :bottom_cum_length)
        """)
        conn.execute(query, {
            "core_id": core_id,
            "section_number": section_number,
            "section_length": section_length,
            "top_cum_length": top_cum_length,
            "bottom_cum_length": bottom_cum_length
        })
        conn.commit()

def update_section(section_id, section_length, top_cum_length, bottom_cum_length):
    """Update a section in the database"""
    with get_connection() as conn:
        query = text("""
            UPDATE sections 
            SET section_length = :section_length, 
                top_cum_length = :top_cum_length, 
                bottom_cum_length = :bottom_cum_length
            WHERE section_id = :section_id
        """)
        conn.execute(query, {
            "section_id": section_id,
            "section_length": section_length,
            "top_cum_length": top_cum_length,
            "bottom_cum_length": bottom_cum_length
        })
        conn.commit()

def delete_section(section_id):
    """Delete a section from the database"""
    with get_connection() as conn:
        query = text("DELETE FROM sections WHERE section_id = :section_id")
        conn.execute(query, {"section_id": section_id})
        conn.commit()

def add_new_section(core_id, section_number, section_length, top_cum_length, bottom_cum_length):
    """Add a new section to existing core (alias for insert_section for clarity)"""
    insert_section(core_id, section_number, section_length, top_cum_length, bottom_cum_length)

def delete_all_sections_for_core(core_id):
    """Delete all sections for a specific core"""
    with get_connection() as conn:
        query = text("DELETE FROM sections WHERE core_id = :core_id")
        conn.execute(query, {"core_id": core_id})
        conn.commit()

