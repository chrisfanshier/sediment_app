import psycopg2
import pandas as pd

def get_connection():
    """Establish a connection to the PostgreSQL database."""
    return psycopg2.connect(
        host="localhost",
        database="sediment_cores",
        user="postgres",
        password="madmaxfuryroad"
    )

def fetch_cores():
    """Fetch the cores table from the database."""
    with get_connection() as conn:
        query = "SELECT * FROM cores ORDER BY core_name"
        return pd.read_sql(query, conn)