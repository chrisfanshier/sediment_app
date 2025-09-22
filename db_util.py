from sqlalchemy import create_engine
import pandas as pd

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
            core_files = df.groupby('core_name')['file_path'].apply(list).to_dict()
            return core_files
    except Exception as e:
        raise RuntimeError(f"Error fetching core/file data: {e}")
    
def fetch_dropdown_values():
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Fetch vessels
            cur.execute("SELECT vessel_id, vessel_name FROM vessels ORDER BY vessel_name;")
            vessels = cur.fetchall()

            # Fetch core types
            cur.execute("SELECT core_type_id, core_type_name, required_fields FROM core_types ORDER BY core_type_name;")
            core_types = cur.fetchall()

def get_dynamic_fields_metadata(core_type_id):
    """
    Fetch dynamic fields for the selected core type from the database.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Correct query to fetch the required fields
            cur.execute("SELECT required_fields FROM core_types WHERE core_type_id = %s", (core_type_id,))
            core_type_metadata = cur.fetchone()
            if core_type_metadata:
                # Directly return the data since psycopg2 already deserializes the JSON column
                return core_type_metadata[0]
    return []

