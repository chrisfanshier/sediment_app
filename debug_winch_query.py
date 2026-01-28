import pandas as pd
from sqlalchemy import create_engine, text

# Your database connection
DB_URL = "postgresql://postgres:madmaxfuryroad@localhost/sediment_cores"
engine = create_engine(DB_URL)

cruise_id = 25  # RR2509 cruise_id from your example

with engine.connect() as conn:
    winch_query = text("""
        SELECT winch_file_id, file_name, file_path, start_time, end_time, settings
        FROM winch_data
        WHERE cruise_id = :cruise_id
        ORDER BY start_time
    """)
    winch_files_df = pd.read_sql(winch_query, conn, params={"cruise_id": cruise_id})

print("=" * 80)
print("STEP 1: Raw data from database")
print("=" * 80)
print(f"DataFrame shape: {winch_files_df.shape}")
print(f"\nFirst 3 rows:")
print(winch_files_df[['file_name', 'start_time', 'end_time']].head(3))
print(f"\nstart_time dtype: {winch_files_df['start_time'].dtype}")
print(f"end_time dtype: {winch_files_df['end_time'].dtype}")
print(f"\nstart_time first value type: {type(winch_files_df['start_time'].iloc[0])}")
print(f"start_time first value: {winch_files_df['start_time'].iloc[0]}")
print(f"start_time first value repr: {repr(winch_files_df['start_time'].iloc[0])}")

print("\n" + "=" * 80)
print("STEP 2: After pd.to_datetime with utc=True")
print("=" * 80)
winch_files_df["start_time"] = pd.to_datetime(winch_files_df["start_time"], errors="coerce", utc=True)
winch_files_df["end_time"] = pd.to_datetime(winch_files_df["end_time"], errors="coerce", utc=True)
print(f"start_time dtype: {winch_files_df['start_time'].dtype}")
print(f"start_time first value: {winch_files_df['start_time'].iloc[0]}")
print(f"\nFirst 3 rows:")
print(winch_files_df[['file_name', 'start_time', 'end_time']].head(3))

print("\n" + "=" * 80)
print("STEP 3: After tz_localize(None)")
print("=" * 80)
winch_files_df["start_time"] = winch_files_df["start_time"].dt.tz_localize(None)
winch_files_df["end_time"] = winch_files_df["end_time"].dt.tz_localize(None)
print(f"start_time dtype: {winch_files_df['start_time'].dtype}")
print(f"start_time first value: {winch_files_df['start_time'].iloc[0]}")
print(f"\nFirst 3 rows:")
print(winch_files_df[['file_name', 'start_time', 'end_time']].head(3))

print("\n" + "=" * 80)
print("STEP 4: Retry WITHOUT utc=True")
print("=" * 80)

# Re-query to get fresh data
with engine.connect() as conn:
    winch_query = text("""
        SELECT winch_file_id, file_name, file_path, start_time, end_time, settings
        FROM winch_data
        WHERE cruise_id = :cruise_id
        ORDER BY start_time
    """)
    winch_files_df = pd.read_sql(winch_query, conn, params={"cruise_id": cruise_id})

# Parse WITHOUT utc=True
winch_files_df["start_time"] = pd.to_datetime(winch_files_df["start_time"], errors="coerce")
winch_files_df["end_time"] = pd.to_datetime(winch_files_df["end_time"], errors="coerce")

print(f"start_time dtype: {winch_files_df['start_time'].dtype}")
print(f"start_time first value: {winch_files_df['start_time'].iloc[0]}")
print(f"\nFirst 5 rows:")
print(winch_files_df[['file_name', 'start_time', 'end_time']].head(5))

# Then handle timezone if present
if pd.api.types.is_datetime64_any_dtype(winch_files_df["start_time"]):
    if winch_files_df["start_time"].dt.tz is not None:
        winch_files_df["start_time"] = winch_files_df["start_time"].dt.tz_localize(None)
if pd.api.types.is_datetime64_any_dtype(winch_files_df["end_time"]):
    if winch_files_df["end_time"].dt.tz is not None:
        winch_files_df["end_time"] = winch_files_df["end_time"].dt.tz_localize(None)

print(f"\nAfter tz_localize(None):")
print(winch_files_df[['file_name', 'start_time', 'end_time']].head(5))


print("\n" + "=" * 80)
print("STEP 6: Examine the exact string format")
print("=" * 80)

# Re-query
with engine.connect() as conn:
    winch_query = text("""
        SELECT winch_file_id, file_name, file_path, start_time, end_time, settings
        FROM winch_data
        WHERE cruise_id = :cruise_id
        ORDER BY start_time
    """)
    winch_files_df = pd.read_sql(winch_query, conn, params={"cruise_id": cruise_id})

# Look at row 1 (the one with timezone)
row1_start = winch_files_df['start_time'].iloc[1]
print(f"Row 1 start_time:")
print(f"  Value: {row1_start}")
print(f"  Repr: {repr(row1_start)}")
print(f"  Length: {len(row1_start)}")
print(f"  Bytes: {row1_start.encode('utf-8')}")

# Try parsing just that one value
test_parse = pd.to_datetime(row1_start, errors='coerce')
print(f"\nDirect parse result: {test_parse}")
print(f"Direct parse type: {type(test_parse)}")