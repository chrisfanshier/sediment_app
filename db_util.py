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
    """Fetch cores with cruise_name from cruises table."""
    query = """
        SELECT c.core_id, c.core_name, cr.cruise_name, c.core_dredge
        FROM cores c
        JOIN cruises cr ON c.cruise_id = cr.cruise_id
        ORDER BY cr.cruise_name, c.core_name
    """
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
    """Fetch the last record from cores table for carry-forward functionality."""
    try:
        with get_connection() as conn:
            query = """
            SELECT c.vessel_id, c.cruise_id, cr.cruise_name, c.leg, c.station 
            FROM cores c
            LEFT JOIN cruises cr ON c.cruise_id = cr.cruise_id
            ORDER BY c.core_id DESC 
            LIMIT 1
            """
            result = conn.execute(text(query)).fetchone()
            if result:
                return {
                    'vessel_id': result[0],
                    'cruise_id': result[1], 
                    'cruise_name': result[2],
                    'leg': result[3],
                    'station': result[4]
                }
            else:
                return None
    except Exception as e:
        print(f"Error fetching last record: {e}")
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
            SELECT section_number, section_length
            FROM sections
            WHERE core_id = :core_id
            ORDER BY section_number
        """)
        result = conn.execute(query, {"core_id": core_id})
        return result.fetchall()

# filepath: c:\sediment_app\scripts\db_util.py
def get_cores_with_sections():
    """Get cores that have sections"""
    with get_connection() as conn:
        query = text("""
            SELECT DISTINCT c.core_id, c.core_name, cr.cruise_name, COUNT(s.section_id) as section_count
            FROM cores c
            JOIN sections s ON c.core_id = s.core_id
            JOIN cruises cr ON c.cruise_id = cr.cruise_id
            GROUP BY c.core_id, c.core_name, cr.cruise_name
            ORDER BY cr.cruise_name, c.core_name
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

def fetch_cruise_options():
    """Fetch cruise options with vessel information for dropdown."""
    try:
        with get_connection() as conn:
            query = """
            SELECT cr.cruise_id, cr.cruise_name, v.vessel_name, v.vessel_id
            FROM cruises cr
            LEFT JOIN vessels v ON cr.vessel_id = v.vessel_id
            ORDER BY cr.cruise_name
            """
            cruises = conn.execute(text(query)).fetchall()
            return cruises
    except Exception as e:
        print(f"Error fetching cruise options: {e}")
        return []
    

def _to_naive_utc(dt):
    if dt is None:
        return None
    ts = pd.to_datetime(dt, utc=True)
    py = ts.to_pydatetime()
    return py.replace(tzinfo=None)

def insert_usbl_file(cruise_id, file_name, file_path, sampling_device, transponder_type, remarks, start_time=None, end_time=None):
    """Insert USBL file metadata. start_time/end_time are Python datetimes or None."""
    with get_connection() as conn:
        query = text("""
            INSERT INTO usbl_files (
                cruise_id, file_name, file_path, sampling_device, transponder_type, remarks, start_time, end_time
            ) VALUES (
                :cruise_id, :file_name, :file_path, :sampling_device, :transponder_type, :remarks, :start_time, :end_time
            )
        """)
        conn.execute(query, {
            "cruise_id": cruise_id,
            "file_name": file_name,
            "file_path": file_path,
            "sampling_device": sampling_device or None,
            "transponder_type": transponder_type or None,
            "remarks": remarks or None,
            "start_time": _to_naive_utc(start_time),
            "end_time": _to_naive_utc(end_time)
        })
        conn.commit()

# ── Core Media ────────────────────────────────────────────────────────────────
def fetch_capture_devices():
    """Fetch all capture devices for dropdown."""
    with get_connection() as conn:
        result = conn.execute(text("""
            SELECT capture_device_id, device_name
            FROM capture_devices
            ORDER BY device_name
        """))
        return result.fetchall()

def insert_core_media(core_id, file_name, file_path, media_type, file_size_bytes, capture_device_id, remarks):
    """Insert a new core_media record."""
    with get_connection() as conn:
        query = text("""
            INSERT INTO core_media (core_id, file_name, file_path, media_type, file_size_bytes, capture_device_id, remarks)
            VALUES (:core_id, :file_name, :file_path, :media_type, :file_size_bytes, :capture_device_id, :remarks)
        """)
        conn.execute(query, {
            "core_id": core_id,
            "file_name": file_name,
            "file_path": file_path,
            "media_type": media_type,
            "file_size_bytes": file_size_bytes,
            "capture_device_id": capture_device_id,
            "remarks": remarks or None
        })
        conn.commit()


def update_core_media_association(media_id, core_id, capture_device_id, remarks):
    """Update the core association, capture device, and remarks for an existing core_media record."""
    with get_connection() as conn:
        query = text("""
            UPDATE core_media
            SET core_id = :core_id,
                capture_device_id = :capture_device_id,
                remarks = :remarks
            WHERE media_id = :media_id
        """)
        conn.execute(query, {
            "media_id": media_id,
            "core_id": core_id,
            "capture_device_id": capture_device_id,
            "remarks": remarks or None
        })
        conn.commit()


def fetch_core_media_registered(scan_dir_relative):
    """
    Return a dict of {file_name: {media_id, core_id, core_name, capture_device_id, device_name, remarks}}
    for all files already registered in core_media whose file_path matches
    the relative scan directory.
    """
    with get_connection() as conn:
        result = conn.execute(text("""
            SELECT cm.media_id, cm.file_name, cm.core_id, c.core_name,
                   cm.capture_device_id, cd.device_name, cm.remarks
            FROM core_media cm
            LEFT JOIN cores c ON cm.core_id = c.core_id
            LEFT JOIN capture_devices cd ON cm.capture_device_id = cd.capture_device_id
            WHERE cm.file_path = :file_path
        """), {"file_path": scan_dir_relative})
        return {
            row.file_name: {
                "media_id": row.media_id,
                "core_id": row.core_id,
                "core_name": row.core_name,
                "capture_device_id": row.capture_device_id,
                "device_name": row.device_name,
                "remarks": row.remarks
            }
            for row in result
        }
