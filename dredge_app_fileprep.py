#!/usr/bin/env python3
"""
Generate Dredge App input files for all cores in a cruise
Creates USBL and sensor CSV files for time series analysis and spatial linking
"""

import argparse
import sys
import os
import json
import pandas as pd
from sqlalchemy import text
from db_util import get_connection
from config import get_full_path
from utils import (
    load_usbl_file, 
    add_utm_coords, 
    process_rsk_data, 
    process_star_oddi_data,
    parse_winch_dat
)


def get_cruise_info(cruise_name):
    """Get cruise_id and verify cruise exists"""
    with get_connection() as conn:
        result = pd.read_sql(
            text("SELECT cruise_id, cruise_name FROM cruises WHERE cruise_name = :cruise_name"),
            conn,
            params={"cruise_name": cruise_name}
        )
    
    if result.empty:
        print(f"❌ Error: Cruise '{cruise_name}' not found in database")
        sys.exit(1)
    
    return int(result.iloc[0]['cruise_id']), result.iloc[0]['cruise_name']


def get_cores_and_files(cruise_id):
    """Get all cores, USBL files, sensor files, and winch files for a cruise"""
    with get_connection() as conn:
        # Get cores
        cores = pd.read_sql(
            text("SELECT * FROM cores WHERE cruise_id = :cruise_id ORDER BY core_name"),
            conn,
            params={"cruise_id": cruise_id}
        )
        
        # Get USBL files
        usbl_files = pd.read_sql(
            text("SELECT usbl_file_id, file_name, file_path, start_time, end_time "
                 "FROM usbl_files WHERE cruise_id = :cruise_id"),
            conn,
            params={"cruise_id": cruise_id}
        )
        
        # Get winch files
        winch_files = pd.read_sql(
            text("SELECT winch_file_id, file_name, file_path, start_time, end_time, settings "
                 "FROM winch_data WHERE cruise_id = :cruise_id ORDER BY start_time"),
            conn,
            params={"cruise_id": cruise_id}
        )
    
    if cores.empty:
        print(f"❌ Error: No cores found for this cruise")
        sys.exit(1)
    
    if usbl_files.empty:
        print(f"❌ Error: No USBL files found for this cruise")
        sys.exit(1)
    
    return cores, usbl_files, winch_files


def parse_core_times(cores):
    """Parse core start/end times"""
    # Find date/time columns
    date_col = next((c for c in ("date", "core_date") if c in cores.columns), None)
    launch_col = next((c for c in ("time_launched", "time_launch", "time_launched_utc") if c in cores.columns), None)
    recover_col = next((c for c in ("time_recovered", "time_recover", "time_recovered_utc") if c in cores.columns), None)
    
    if not (date_col and launch_col and recover_col):
        print(f"❌ Error: Cores missing required date/time columns")
        print(f"   Available columns: {list(cores.columns)}")
        sys.exit(1)
    
    df = cores.copy()
    df[launch_col] = df[launch_col].astype(str)
    df[recover_col] = df[recover_col].astype(str)
    
    # Parse datetimes
    df["start_datetime"] = pd.to_datetime(df[date_col], errors="coerce") + pd.to_timedelta(df[launch_col], errors="coerce")
    df["end_datetime"] = pd.to_datetime(df[date_col], errors="coerce") + pd.to_timedelta(df[recover_col], errors="coerce")
    
    # Handle invalid times
    bad = df[["start_datetime", "end_datetime"]].isna().any(axis=1)
    if bad.any():
        print(f"⚠️  Warning: Skipping {bad.sum()} cores with invalid date/time")
        df = df.loc[~bad].copy()
    
    # Handle midnight rollover
    df.loc[df["end_datetime"] < df["start_datetime"], "end_datetime"] += pd.Timedelta(days=1)
    
    return df


def match_usbl_to_core(core_row, usbl_files):
    """Find USBL files that overlap with core deployment time"""
    mask = (usbl_files["start_time"] <= core_row["end_datetime"]) & \
           (usbl_files["end_time"] >= core_row["start_datetime"])
    return usbl_files.loc[mask, "file_name"].tolist()


def load_core_usbl(matched_files, usbl_files):
    """Load and concatenate all USBL data for matched files"""
    usbl_dfs = []
    
    for fname in matched_files:
        row = usbl_files[usbl_files["file_name"] == fname]
        if not row.empty:
            file_path = row.iloc[0].get("file_path", "")
            relative_path = os.path.join(file_path, fname)
            full_path = get_full_path(relative_path)
            
            try:
                df = load_usbl_file(full_path)
                if df is not None:
                    usbl_dfs.append(df)
            except Exception as e:
                print(f"      ⚠️  Warning: Could not load {fname}: {e}")
    
    if not usbl_dfs:
        return None
    
    all_usbl = pd.concat(usbl_dfs)
    all_usbl = all_usbl.sort_index()
    
    return all_usbl


def create_usbl_export(usbl_df, core_name):
    """Create USBL export file with UTM coordinates"""
    # Reset index to get datetime as column
    usbl_export = usbl_df.reset_index()
    
    # Ensure datetime is timezone-aware UTC
    usbl_export['datetime'] = pd.to_datetime(usbl_export['datetime'])
    if usbl_export['datetime'].dt.tz is None:
        usbl_export['datetime'] = usbl_export['datetime'].dt.tz_localize('UTC')
    
    # Auto-detect UTM zone from this core's data
    mean_lon = usbl_export['longitude_deg'].mean()
    mean_lat = usbl_export['latitude_deg'].mean()
    utm_zone = int((mean_lon + 180) / 6) + 1
    northern = mean_lat >= 0
    
    # Add UTM coordinates
    usbl_export = add_utm_coords(
        usbl_export,
        lat_col="latitude_deg",
        lon_col="longitude_deg",
        utm_zone=utm_zone,
        northern=northern
    )
    
    # Rename X_Center/Y_Center to easting/northing
    if 'X_Center' in usbl_export.columns:
        usbl_export['easting'] = usbl_export['X_Center']
        usbl_export['northing'] = usbl_export['Y_Center']
    
    # Required columns
    required_cols = ['datetime', 'latitude_deg', 'longitude_deg', 
                     'easting', 'northing', 
                     'hor_err_major', 'hor_err_minor', 'hor_err_dir']
    
    # Optional columns
    optional_cols = ['depth_m', 'beacon_name', 'fix_status', 'depth_error']
    
    # Check for missing required columns
    missing_cols = [col for col in required_cols if col not in usbl_export.columns]
    if missing_cols:
        raise ValueError(f"USBL data missing required columns: {', '.join(missing_cols)}")
    
    # Build final column list
    final_cols = required_cols + [c for c in optional_cols if c in usbl_export.columns]
    usbl_export_final = usbl_export[final_cols]
    
    # Format datetime to milliseconds for CSV export
    usbl_export_csv = usbl_export_final.copy()
    usbl_export_csv['datetime'] = usbl_export_csv['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S.%f').str[:-3] + '+00:00'
    
    return usbl_export_csv


def load_sensor_files(core_id):
    """Load all sensor files for a core"""
    with get_connection() as conn:
        sensor_query = text("""
            SELECT file_id, file_name, file_path, sensor_type, sensor_location
            FROM sensor_files
            WHERE core_id = :core_id
            ORDER BY file_name
        """)
        sensor_files_df = pd.read_sql(sensor_query, conn, params={"core_id": core_id})
    
    sensor_data_dict = {}
    
    for _, sensor_row in sensor_files_df.iterrows():
        file_name = sensor_row['file_name']
        file_path = sensor_row['file_path']
        sensor_type = sensor_row['sensor_type'] if sensor_row['sensor_type'] else "Unknown"
        
        relative_path = os.path.join(file_path, file_name)
        file_ext = os.path.splitext(file_name)[1].lower()
        sensor_type_lower = sensor_type.lower()
        
        try:
            if file_ext == '.rsk' or 'rbr' in sensor_type_lower:
                df = process_rsk_data(relative_path)
            elif file_ext in ['.dat', '.acc'] or 'star-oddi' in sensor_type_lower or 'staroddi' in sensor_type_lower:
                df = process_star_oddi_data(relative_path)
            else:
                continue
            
            if df is not None:
                if 'datetime' not in df.columns:
                    if 'Timestamp' in df.columns:
                        df['datetime'] = df['Timestamp']
                    else:
                        continue
                
                # Remove timezone
                df['datetime'] = pd.to_datetime(df['datetime']).dt.tz_localize(None)
                sensor_data_dict[file_name] = df
                
        except Exception as e:
            print(f"      ⚠️  Warning: Could not load sensor file {file_name}: {str(e)}")
    
    return sensor_data_dict


def load_winch_files(cruise_id, usbl_start, usbl_end, winch_files_df):
    """Load winch files overlapping with USBL time range"""
    if winch_files_df.empty:
        return None
    
    # Parse timestamps
    def parse_and_strip_tz(x):
        dt = pd.to_datetime(x, errors="coerce")
        if dt is pd.NaT:
            return dt
        if hasattr(dt, 'tz') and dt.tz is not None:
            return dt.tz_localize(None)
        return dt
    
    winch_files_df["start_time"] = winch_files_df["start_time"].apply(parse_and_strip_tz)
    winch_files_df["end_time"] = winch_files_df["end_time"].apply(parse_and_strip_tz)
    
    # Find overlapping winch files
    overlap_mask = (
        (winch_files_df['start_time'] <= usbl_end) & 
        (winch_files_df['end_time'] >= usbl_start)
    )
    overlapping_winch = winch_files_df[overlap_mask]
    
    if overlapping_winch.empty:
        return None
    
    winch_dfs = []
    
    for _, winch_row in overlapping_winch.iterrows():
        file_name = winch_row['file_name']
        file_path = winch_row['file_path']
        settings = winch_row['settings']
        
        try:
            # Parse settings
            try:
                settings_dict = json.loads(settings) if settings else {}
            except json.JSONDecodeError:
                settings_dict = {}
            
            # Construct full file path
            relative_path = os.path.join(file_path, file_name)
            full_file_path = get_full_path(relative_path)
            
            # Use settings from database or fallback
            if settings_dict:
                parsing_settings = {
                    "delimiter": settings_dict.get("delimiter", ","),
                    "header_lines": settings_dict.get("header_lines", 0),
                    "columns": settings_dict.get("columns", []),
                    "datetime_code": settings_dict.get("datetime_code", "pd.to_datetime(df['datetime'])")
                }
                if "numeric_columns" in settings_dict:
                    parsing_settings["numeric_columns"] = settings_dict["numeric_columns"]
            else:
                file_ext = os.path.splitext(file_name)[1].lower()
                if file_ext == '.dat':
                    parsing_settings = {
                        "delimiter": r"\s+",
                        "header_lines": 0,
                        "datetime_code": "pd.to_datetime(df[['year', 'month', 'day', 'hour', 'minute', 'second']])"
                    }
                else:
                    parsing_settings = {
                        "delimiter": ",",
                        "header_lines": 0,
                        "datetime_code": "pd.to_datetime(df['datetime'])"
                    }
            
            # Parse the file
            df = parse_winch_dat(full_file_path, parsing_settings)
            
            if df is not None:
                if 'datetime' not in df.columns:
                    continue
                
                df['source_file'] = file_name
                winch_dfs.append(df)
                
        except Exception as e:
            print(f"      ⚠️  Warning: Could not load winch file {file_name}: {str(e)}")
    
    if not winch_dfs:
        return None
    
    # Concatenate and trim to USBL time range
    all_winch = pd.concat(winch_dfs, ignore_index=True)
    all_winch = all_winch.sort_values('datetime').reset_index(drop=True)
    all_winch['datetime'] = pd.to_datetime(all_winch['datetime']).dt.tz_localize(None)
    
    # Trim to USBL time range
    trim_mask = (all_winch['datetime'] >= usbl_start) & (all_winch['datetime'] <= usbl_end)
    trimmed_winch = all_winch[trim_mask].copy()
    
    if trimmed_winch.empty:
        return None
    
    return trimmed_winch


def create_sensor_export(sensor_data_dict, winch_data):
    """Create combined sensor/winch export file"""
    # Collect all unique datetimes
    all_datetimes = []
    
    if sensor_data_dict:
        for df in sensor_data_dict.values():
            all_datetimes.append(df['datetime'])
    
    if winch_data is not None:
        all_datetimes.append(winch_data['datetime'])
    
    if not all_datetimes:
        return None
    
    # Combine and get unique sorted datetimes
    combined_times = pd.concat(all_datetimes).drop_duplicates().sort_values()
    sensor_export = pd.DataFrame({'datetime': combined_times})
    
    # Merge sensor files with prefixed columns
    if sensor_data_dict:
        for file_name, df in sensor_data_dict.items():
            numeric_cols = [col for col in df.select_dtypes(include=['number']).columns 
                           if col.lower() not in ['index', 'datetime']]
            
            # Create clean prefix from filename
            prefix = file_name.replace('.', '_').replace('-', '_').replace(' ', '_')
            rename_map = {col: f"{prefix}_{col}" for col in numeric_cols}
            
            df_to_merge = df[['datetime'] + numeric_cols].rename(columns=rename_map)
            sensor_export = pd.merge(sensor_export, df_to_merge, on='datetime', how='outer')
    
    # Merge winch data with WINCH_ prefix
    if winch_data is not None:
        exclude_cols = ['index', 'datetime', 'date', 'time', 'year', 'month', 'day', 
                       'hour', 'minute', 'second', 'source_file']
        winch_numeric_cols = [col for col in winch_data.select_dtypes(include=['number']).columns 
                             if col.lower() not in exclude_cols]
        
        rename_map = {col: f"WINCH_{col}" for col in winch_numeric_cols}
        winch_to_merge = winch_data[['datetime'] + winch_numeric_cols].rename(columns=rename_map)
        sensor_export = pd.merge(sensor_export, winch_to_merge, on='datetime', how='outer')
    
    # Sort and ensure timezone-aware
    sensor_export = sensor_export.sort_values('datetime').reset_index(drop=True)
    sensor_export['datetime'] = pd.to_datetime(sensor_export['datetime'])
    if sensor_export['datetime'].dt.tz is None:
        sensor_export['datetime'] = sensor_export['datetime'].dt.tz_localize('UTC')
    
    # Format datetime to milliseconds for CSV export
    sensor_export_csv = sensor_export.copy()
    sensor_export_csv['datetime'] = sensor_export_csv['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S.%f').str[:-3] + '+00:00'
    
    return sensor_export_csv


def main():
    parser = argparse.ArgumentParser(
        description="Generate Dredge App input files for all cores in a cruise"
    )
    parser.add_argument(
        "--cruise_name",
        required=True,
        help="Name of cruise to process"
    )
    
    args = parser.parse_args()
    
    # Get output directory
    output_dir = get_full_path("drg_app_input")
    os.makedirs(output_dir, exist_ok=True)
    
    # Get cruise info
    print(f"🔍 Looking up cruise: {args.cruise_name}")
    cruise_id, cruise_name = get_cruise_info(args.cruise_name)
    print(f"✓ Found cruise_id: {cruise_id}")
    
    # Get cores and files
    print(f"📊 Loading cores and data files...")
    cores, usbl_files, winch_files = get_cores_and_files(cruise_id)
    print(f"✓ Found {len(cores)} cores, {len(usbl_files)} USBL files, {len(winch_files)} winch files")
    
    # Parse core times
    cores_with_times = parse_core_times(cores)
    print(f"✓ Parsed times for {len(cores_with_times)} cores")
    
    # Parse USBL file times
    usbl_files["start_time"] = pd.to_datetime(usbl_files["start_time"], errors="coerce")
    usbl_files["end_time"] = pd.to_datetime(usbl_files["end_time"], errors="coerce")
    
    print(f"📁 Output directory: {output_dir}")
    print()
    
    # Process each core
    cores_processed = 0
    cores_skipped = 0
    usbl_files_created = 0
    sensor_files_created = 0
    
    for idx, core in cores_with_times.iterrows():
        core_name = core.get("core_name", f"core_{idx}")
        core_id = int(core["core_id"])
        print(f"Processing {core_name}...")
        
        try:
            # Match and load USBL data
            matched_usbl_files = match_usbl_to_core(core, usbl_files)
            
            if not matched_usbl_files:
                print(f"   ⊘ No USBL files - skipping")
                cores_skipped += 1
                continue
            
            usbl_data = load_core_usbl(matched_usbl_files, usbl_files)
            
            if usbl_data is None or usbl_data.empty:
                print(f"   ⊘ No USBL data - skipping")
                cores_skipped += 1
                continue
            
            # Create USBL export
            usbl_export = create_usbl_export(usbl_data, core_name)
            usbl_filename = f"{core_name}_dredgeapp_usbl.csv"
            usbl_path = os.path.join(output_dir, usbl_filename)
            usbl_export.to_csv(usbl_path, index=False)
            usbl_files_created += 1
            print(f"   ✓ USBL: {len(usbl_export)} points")
            
            # Get USBL time range for sensor/winch matching
            usbl_times = usbl_data.reset_index()
            usbl_times['datetime'] = pd.to_datetime(usbl_times['datetime']).dt.tz_localize(None)
            usbl_start = usbl_times['datetime'].min()
            usbl_end = usbl_times['datetime'].max()
            
            # Load sensor data
            sensor_data_dict = load_sensor_files(core_id)
            
            # Load winch data
            winch_data = load_winch_files(cruise_id, usbl_start, usbl_end, winch_files)
            
            # Create sensor export if we have sensor or winch data
            if sensor_data_dict or winch_data is not None:
                sensor_export = create_sensor_export(sensor_data_dict, winch_data)
                
                if sensor_export is not None and not sensor_export.empty:
                    sensor_filename = f"{core_name}_dredgeapp_sensor.csv"
                    sensor_path = os.path.join(output_dir, sensor_filename)
                    sensor_export.to_csv(sensor_path, index=False)
                    sensor_files_created += 1
                    
                    # Count sources
                    sensor_count = len(sensor_data_dict) if sensor_data_dict else 0
                    winch_count = 1 if winch_data is not None else 0
                    print(f"   ✓ Sensor: {len(sensor_export)} records ({sensor_count} sensor + {winch_count} winch)")
                else:
                    print(f"   ⚠️  No sensor/winch data to export")
            else:
                print(f"   ⚠️  No sensor/winch data available")
            
            cores_processed += 1
            
        except Exception as e:
            print(f"   ❌ Error processing {core_name}: {str(e)}")
            cores_skipped += 1
    
    print()
    print(f"{'='*60}")
    print(f"✅ Export complete!")
    print(f"   Cores processed: {cores_processed}")
    print(f"   Cores skipped: {cores_skipped}")
    print(f"   USBL files created: {usbl_files_created}")
    print(f"   Sensor files created: {sensor_files_created}")
    print(f"   Output directory: {output_dir}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()