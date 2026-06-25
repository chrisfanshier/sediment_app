from sqlalchemy import create_engine, text
import pandas as pd
from datetime import date

# Database connection string
DB_URL = "postgresql://postgres:madmaxfuryroad@localhost/shipside"

# Create a SQLAlchemy engine
engine = create_engine(DB_URL)

def get_connection():
    """Get a database connection."""
    return engine.connect()

def fetch_cores(only_created_on_ship=False):
    """Fetch cores with cruise_name from cruises table.
       If only_created_on_ship is True, only return cores created on ship.
    """
    query = """
        SELECT c.core_id, c.core_name, c.core_dredge, cr.cruise_name
        FROM cores c
        JOIN cruises cr ON c.cruise_id = cr.cruise_id
    """
    if only_created_on_ship:
        query += " WHERE c.created_on_ship = TRUE"
    query += " ORDER BY cr.cruise_name, c.core_name"
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
def get_cores_with_sections(only_created_on_ship=False):
    """Get cores that have sections. If only_created_on_ship is True, only return ship-created cores."""
    with get_connection() as conn:
        query = """
            SELECT DISTINCT c.core_id, c.core_name, cr.cruise_name, COUNT(s.section_id) as section_count
            FROM cores c
            JOIN sections s ON c.core_id = s.core_id
            JOIN cruises cr ON c.cruise_id = cr.cruise_id
        """
        if only_created_on_ship:
            query += " WHERE c.created_on_ship = TRUE"
        query += """
            GROUP BY c.core_id, c.core_name, cr.cruise_name
            ORDER BY cr.cruise_name, c.core_name
        """
        result = conn.execute(text(query))
        return result.fetchall()

def get_sections_for_core(core_id):
    """Get all sections for a specific core"""
    with get_connection() as conn:
        query = text("""
            SELECT section_id, section_number, section_length, split, top_cum_length, bottom_cum_length 
            FROM sections 
            WHERE core_id = :core_id 
            ORDER BY section_number
        """)
        result = conn.execute(query, {"core_id": core_id})
        return result.fetchall()

def insert_section(core_id, section_number, section_length, top_cum_length, bottom_cum_length, split=False):
    """Insert a new section into the database"""
    with get_connection() as conn:
        query = text("""
            INSERT INTO sections (core_id, section_number, section_length, split, top_cum_length, bottom_cum_length)
            VALUES (:core_id, :section_number, :section_length, :split, :top_cum_length, :bottom_cum_length)
        """)
        conn.execute(query, {
            "core_id": core_id,
            "section_number": section_number,
            "section_length": section_length,
            "split": split,
            "top_cum_length": top_cum_length,
            "bottom_cum_length": bottom_cum_length
        })
        conn.commit()

def update_section(section_id, section_length, top_cum_length, bottom_cum_length, split):
    """Update an existing section"""
    with get_connection() as conn:
        values = {
            'section_length': section_length,
            'top_cum_length': top_cum_length,
            'bottom_cum_length': bottom_cum_length,
            'split': split,
            'section_id': section_id
        }
        
        # Add sync tracking for update
        values = add_sync_tracking(values, is_update=True)
        
        query = text("""
            UPDATE sections 
            SET section_length = :section_length,
                split = :split,
                top_cum_length = :top_cum_length,
                bottom_cum_length = :bottom_cum_length,
                sync_status = :sync_status
            WHERE section_id = :section_id
        """)
        conn.execute(query, values)
        conn.commit()

def delete_section(section_id):
    """Delete a section from the database"""
    with get_connection() as conn:
        query = text("DELETE FROM sections WHERE section_id = :section_id")
        conn.execute(query, {"section_id": section_id})
        conn.commit()

def add_new_section(core_id, section_number, section_length, top_cum_length, bottom_cum_length, split=False):
    """Add a new section to existing core (alias for insert_section for clarity)"""
    insert_section(core_id, section_number, section_length, top_cum_length, bottom_cum_length, split=split)

def delete_all_sections_for_core(core_id):
    """Delete all sections for a specific core"""
    with get_connection() as conn:
        query = text("DELETE FROM sections WHERE core_id = :core_id")
        conn.execute(query, {"core_id": core_id})
        conn.commit()

def fetch_cruise_options(only_created_on_ship=False):
    """Fetch cruise options with vessel information for dropdown.
       If only_created_on_ship is True, only return cruises created on ship.
    """
    try:
        with get_connection() as conn:
            query = """
            SELECT cr.cruise_id, cr.cruise_name, v.vessel_name, v.vessel_id
            FROM cruises cr
            LEFT JOIN vessels v ON cr.vessel_id = v.vessel_id
            """
            if only_created_on_ship:
                query += " WHERE cr.created_on_ship = TRUE"
            query += " ORDER BY cr.cruise_name"
            cruises = conn.execute(text(query)).fetchall()
            return cruises
    except Exception as e:
        print(f"Error fetching cruise options: {e}")
        return []
    
def add_sync_tracking(values_dict, created_on_ship=True, is_update=False):
    """
    Add sync tracking columns to a values dictionary for insert/update.
    
    Args:
        values_dict: Dictionary of column:value pairs
        created_on_ship: Whether this record was created on ship (default True)
        is_update: If True, only add sync_status (for updates, triggers handle the rest)
    
    Returns:
        Modified values_dict with sync tracking columns
    """
    if is_update:
        # For updates, only set sync_status (triggers handle modified_at)
        values_dict['sync_status'] = 'pending'
    else:
        # For inserts, set both columns
        values_dict['created_on_ship'] = created_on_ship
        values_dict['sync_status'] = 'pending' if created_on_ship else 'synced'
    
    return values_dict


def _to_naive_utc(dt):
    """Convert a datetime to a naive UTC datetime (strip tzinfo)."""
    if dt is None:
        return None
    ts = pd.to_datetime(dt, utc=True)
    py = ts.to_pydatetime()
    return py.replace(tzinfo=None)


def insert_usbl_file(cruise_id, file_name, file_path, sampling_device, transponder_type, remarks, start_time=None, end_time=None):
    """Insert USBL file metadata with sync tracking. start_time/end_time are Python datetimes or None."""
    with get_connection() as conn:
        values = {
            "cruise_id": cruise_id,
            "file_name": file_name,
            "file_path": file_path,
            "sampling_device": sampling_device or None,
            "transponder_type": transponder_type or None,
            "remarks": remarks or None,
            "start_time": _to_naive_utc(start_time),
            "end_time": _to_naive_utc(end_time)
        }
        # Add sync tracking
        values = add_sync_tracking(values)

        query = text("""
            INSERT INTO usbl_files (
                cruise_id, file_name, file_path, sampling_device, transponder_type, remarks, start_time, end_time,
                created_on_ship, sync_status
            ) VALUES (
                :cruise_id, :file_name, :file_path, :sampling_device, :transponder_type, :remarks, :start_time, :end_time,
                :created_on_ship, :sync_status
            )
        """)
        conn.execute(query, values)
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
    """Insert a new core_media record with sync tracking."""
    with get_connection() as conn:
        values = {
            "core_id": core_id,
            "file_name": file_name,
            "file_path": file_path,
            "media_type": media_type,
            "file_size_bytes": file_size_bytes,
            "capture_device_id": capture_device_id,
            "remarks": remarks or None
        }
        # Add sync tracking
        values = add_sync_tracking(values)

        query = text("""
            INSERT INTO core_media (core_id, file_name, file_path, media_type, file_size_bytes, capture_device_id, remarks,
                                    created_on_ship, sync_status)
            VALUES (:core_id, :file_name, :file_path, :media_type, :file_size_bytes, :capture_device_id, :remarks,
                    :created_on_ship, :sync_status)
        """)
        conn.execute(query, values)
        conn.commit()


def update_core_media_association(media_id, core_id, capture_device_id, remarks):
    """Update the core association, capture device, and remarks for an existing core_media record."""
    with get_connection() as conn:
        values = {
            "media_id": media_id,
            "core_id": core_id,
            "capture_device_id": capture_device_id,
            "remarks": remarks or None
        }
        # Add sync tracking for update
        values = add_sync_tracking(values, is_update=True)

        query = text("""
            UPDATE core_media
            SET core_id = :core_id,
                capture_device_id = :capture_device_id,
                remarks = :remarks,
                sync_status = :sync_status
            WHERE media_id = :media_id
        """)
        conn.execute(query, values)
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


def get_mgr_export_data(cruise_name: str) -> list:
    """Returns rows for MGR metadata export for a given cruise."""
    query = text("""
        WITH split_expand AS (
            SELECT
                s.core_id, s.section_number, s.section_length,
                s.top_cum_length, s.bottom_cum_length, s.remarks,
                wa.working_archive, wa.wa_suffix, wa.sort_order
            FROM sections s
            CROSS JOIN LATERAL (
                SELECT 'Round' AS working_archive, 'R' AS wa_suffix, 1 AS sort_order WHERE s.split = FALSE
                UNION ALL
                SELECT 'Working', 'W', 1 WHERE s.split = TRUE
                UNION ALL
                SELECT 'Archive', 'A', 2 WHERE s.split = TRUE
            ) wa
        )
        SELECT
            cr.cruise_name, v.vessel_name, cr.chief_scientist,
            c.core_name,
            ct.core_type_name AS recovery_method,
            regexp_replace(c.core_name, '^[A-Z0-9]+-([A-Z]+)\\d+.*$', '\\1') AS core_abbreviation,
            c.date AS date_collected,
            c.time_launched AS time_collected_utc,
            c.latitude, c.longitude, c.water_depth_m,
            se.section_number, se.working_archive,
            c.core_name || '-' || se.section_number || se.wa_suffix AS section_name,
            NULL::text AS alternate_section_name,
            se.section_length, se.top_cum_length, se.bottom_cum_length,
            NULL::numeric AS core_diameter_cm,
            NULL::text AS core_tube_material,
            se.remarks
        FROM split_expand se
        JOIN cores c         ON se.core_id     = c.core_id
        JOIN cruises cr      ON c.cruise_id    = cr.cruise_id
        JOIN vessels v       ON cr.vessel_id   = v.vessel_id
        LEFT JOIN core_types ct ON c.core_type_id = ct.core_type_id
        WHERE cr.cruise_name = :cruise_name
          AND c.core_dredge  = 'core'
        ORDER BY c.core_name, se.section_number, se.sort_order
    """)
    with get_connection() as conn:
        return conn.execute(query, {"cruise_name": cruise_name}).fetchall()


def get_ct_export_rows(cruise_id: int) -> list:
    """Return CT Manager Database View summary rows filtered to one cruise."""
    with get_connection() as conn:
        result = conn.execute(text("""
            SELECT DISTINCT
                x.core_name,
                x.section_number,
                x.xml_root_tag,
                x.image_type,
                x.processing_stage
            FROM ct_xml x
            LEFT JOIN sections s ON x.section_id = s.section_id
            JOIN cores c ON x.core_id = c.core_id
                OR s.core_id = c.core_id
                OR x.core_name = c.core_name
            WHERE c.cruise_id = :cruise_id
            ORDER BY x.core_name, x.section_number
        """), {"cruise_id": cruise_id})
        rows = [dict(row._mapping) for row in result.fetchall()]

    if not rows:
        return []

    df = pd.DataFrame(rows)
    directory_types = ["CT-Volume", "Helical", "Laminography"]
    image_types = ["giXRayImage", "giCTOrthogonalView"]
    summary_rows = []

    all_pairs = df[["core_name", "section_number"]].drop_duplicates()
    for _, row in all_pairs.iterrows():
        core = row["core_name"]
        section = row["section_number"]
        subdf = df[(df["core_name"] == core) & (df["section_number"] == section)]
        xml_count = len(subdf)

        ct_scan_records = subdf[subdf["xml_root_tag"].isin(["geotek-ct-stack", "geotek-ct-recon"])]
        directories = []
        for dtype in directory_types:
            stages = ct_scan_records.loc[
                ct_scan_records["image_type"] == dtype,
                "processing_stage"
            ].dropna().unique()
            if len(stages) > 0:
                directories.append(f"{dtype} ({', '.join(sorted(stages))})")

        image_records = subdf[subdf["xml_root_tag"] == "geotek-image"]
        images = [itype for itype in image_types if (image_records["image_type"] == itype).any()]

        summary_rows.append((
            core,
            section,
            xml_count,
            "; ".join(directories) if directories else "",
            ", ".join(images) if images else "",
        ))

    return sorted(summary_rows, key=lambda item: (str(item[0]), str(item[1])))


def get_mscl_export_rows(cruise_id: int) -> list:
    """Return one row per core with MSCL file names comma-space concatenated."""
    with get_connection() as conn:
        result = conn.execute(text("""
            SELECT
                c.core_name,
                COALESCE(
                    string_agg(mf.file_name, ', ' ORDER BY mf.file_name)
                    FILTER (WHERE mf.file_id IS NOT NULL),
                    ''
                ) AS file_name
            FROM cores c
            LEFT JOIN mscl_files mf ON mf.core_id = c.core_id
            WHERE c.cruise_id = :cruise_id
            GROUP BY c.core_id, c.core_name
            ORDER BY c.core_name
        """), {"cruise_id": cruise_id})
        return [(row.core_name, row.file_name) for row in result.fetchall()]


def get_core_media_export_rows(cruise_id: int) -> list:
    """Return one row per core with selected core_media fields concatenated."""
    with get_connection() as conn:
        result = conn.execute(text("""
            SELECT
                c.core_name,
                COALESCE(
                    string_agg(cm.file_name, ', ' ORDER BY cm.file_name)
                    FILTER (WHERE cm.media_id IS NOT NULL),
                    ''
                ) AS file_name,
                COALESCE(
                    string_agg(CAST(cm.file_size_bytes AS TEXT), ', ' ORDER BY cm.file_name)
                    FILTER (WHERE cm.file_size_bytes IS NOT NULL),
                    ''
                ) AS file_size_bytes,
                COALESCE(
                    string_agg(cm.remarks, ', ' ORDER BY cm.file_name)
                    FILTER (WHERE cm.remarks IS NOT NULL AND cm.remarks <> ''),
                    ''
                ) AS remarks,
                COALESCE(
                    string_agg(cm.media_type, ', ' ORDER BY cm.file_name)
                    FILTER (WHERE cm.media_type IS NOT NULL),
                    ''
                ) AS media_type
            FROM cores c
            LEFT JOIN core_media cm ON cm.core_id = c.core_id
            WHERE c.cruise_id = :cruise_id
            GROUP BY c.core_id, c.core_name
            ORDER BY c.core_name
        """), {"cruise_id": cruise_id})
        return [
            (row.core_name, row.file_name, row.file_size_bytes, row.remarks, row.media_type)
            for row in result.fetchall()
        ]