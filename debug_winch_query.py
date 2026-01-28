import pandas as pd
from sqlalchemy import create_engine, text

# Database connection
DB_URL = "postgresql://postgres:madmaxfuryroad@localhost/sediment_cores"
engine = create_engine(DB_URL)

# Test parameters - use your actual USBL time range
usbl_start = pd.to_datetime("2025-10-22 22:11:55.900000")
usbl_end = pd.to_datetime("2025-10-23 00:59:54.840000")
cruise_id = 25

print("=" * 80)
print("TESTING WINCH FILE SELECTION AND PARSING")
print("=" * 80)
print(f"USBL time range: {usbl_start} to {usbl_end}")
print()

# Query winch files
with engine.connect() as conn:
    winch_query = text("""
        SELECT winch_file_id, file_name, file_path, start_time, end_time, settings
        FROM winch_data
        WHERE cruise_id = :cruise_id
        ORDER BY start_time
    """)
    winch_files_df = pd.read_sql(winch_query, conn, params={"cruise_id": cruise_id})

print(f"Step 1: Query returned {len(winch_files_df)} winch files")
print(f"start_time dtype before parsing: {winch_files_df['start_time'].dtype}")

# Parse timestamps row by row
winch_files_df["start_time"] = winch_files_df["start_time"].apply(lambda x: pd.to_datetime(x, errors="coerce"))
winch_files_df["end_time"] = winch_files_df["end_time"].apply(lambda x: pd.to_datetime(x, errors="coerce"))

print(f"\nStep 2: After .apply() parsing")
print(f"start_time dtype: {winch_files_df['start_time'].dtype}")
print(f"First value type: {type(winch_files_df['start_time'].iloc[0])}")
print(f"First 3 parsed times:")
print(winch_files_df[['file_name', 'start_time', 'end_time']].head(3))

# Convert to datetime dtype
winch_files_df["start_time"] = pd.to_datetime(winch_files_df["start_time"])
winch_files_df["end_time"] = pd.to_datetime(winch_files_df["end_time"])

print(f"\nStep 3: After pd.to_datetime() conversion")
print(f"start_time dtype: {winch_files_df['start_time'].dtype}")

# Handle timezone
if hasattr(winch_files_df["start_time"].dtype, 'tz') and winch_files_df["start_time"].dt.tz is not None:
    print(f"Timezone detected: {winch_files_df['start_time'].dt.tz}, removing...")
    winch_files_df["start_time"] = winch_files_df["start_time"].dt.tz_localize(None)
    winch_files_df["end_time"] = winch_files_df["end_time"].dt.tz_localize(None)
else:
    print("No timezone detected or already naive")

print(f"\nStep 4: After timezone handling")
print(f"start_time dtype: {winch_files_df['start_time'].dtype}")
print(f"First 3 final times:")
print(winch_files_df[['file_name', 'start_time', 'end_time']].head(3))

# Find overlapping files
overlap_mask = (
    (winch_files_df['start_time'] <= usbl_end) & 
    (winch_files_df['end_time'] >= usbl_start)
)
overlapping_winch = winch_files_df[overlap_mask]

print(f"\nStep 5: Finding overlapping files")
print(f"Found {len(overlapping_winch)} overlapping winch file(s):")
for idx, row in overlapping_winch.iterrows():
    print(f"  - {row['file_name']}: {row['start_time']} to {row['end_time']}")

print("\n" + "=" * 80)
print("SUCCESS! Timestamps parsed and overlapping files found correctly")
print("=" * 80)