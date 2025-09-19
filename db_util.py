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