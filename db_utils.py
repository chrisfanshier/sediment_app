import psycopg2
import pandas as pd

def get_connection():
    return psycopg2.connect(
        host="localhost",
        database="sediment_cores",
        user="postgres",
        password="madmaxfuryroad"
    )

def fetch_cores():
    with get_connection() as conn:
        query = "SELECT core_id, core_name FROM cores ORDER BY core_name"
        return pd.read_sql(query, conn)

def insert_core(data):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO cores (core_name, ship_name, latitude, longitude,
                    water_depth_m, max_tension_kg, retrieval_date, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, data)
        conn.commit()

def insert_file(core_id, file_name, file_path):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO files (core_id, file_name, file_path)
                VALUES (%s, %s, %s)
            """, (core_id, file_name, file_path))
        conn.commit()