#!/usr/bin/env python3
"""
Export entire cruise USBL data to GeoPackage
Creates one GeoPackage with separate layers for each core (points + ellipses)
"""

import argparse
import sys
import os
import pandas as pd
import geopandas as gpd
from sqlalchemy import text
from shapely.geometry import Point
from db_util import get_connection
from config import get_full_path
from utils import load_usbl_file, add_utm_coords, ellipse_polygon


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
    
    return result.iloc[0]['cruise_id'], result.iloc[0]['cruise_name']


def get_cores_and_usbl(cruise_id):
    """Get all cores and USBL files for a cruise"""
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
    
    if cores.empty:
        print(f"❌ Error: No cores found for this cruise")
        sys.exit(1)
    
    if usbl_files.empty:
        print(f"❌ Error: No USBL files found for this cruise")
        sys.exit(1)
    
    return cores, usbl_files


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
                print(f"   ⚠️  Warning: Could not load {fname}: {e}")
    
    if not usbl_dfs:
        return None
    
    all_usbl = pd.concat(usbl_dfs)
    all_usbl = all_usbl.sort_index()
    
    return all_usbl


def determine_utm_zone(all_cores_usbl):
    """Auto-detect UTM zone from mean position of all cores"""
    mean_lon = all_cores_usbl['longitude_deg'].mean()
    mean_lat = all_cores_usbl['latitude_deg'].mean()
    
    utm_zone = int((mean_lon + 180) / 6) + 1
    northern = mean_lat >= 0
    
    hemisphere = "Northern" if northern else "Southern"
    epsg = f"EPSG:326{utm_zone:02d}" if northern else f"EPSG:327{utm_zone:02d}"
    
    print(f"🗺️  Auto-detected UTM zone: {utm_zone} {hemisphere} Hemisphere ({epsg})")
    
    return utm_zone, northern, epsg


def create_point_layer(usbl_df, core_name, epsg):
    """Create GeoDataFrame of USBL points"""
    gdf = gpd.GeoDataFrame(
        usbl_df.reset_index(),
        geometry=[Point(lon, lat) for lon, lat in zip(usbl_df['longitude_deg'], usbl_df['latitude_deg'])],
        crs="EPSG:4326"
    )
    
    # Convert to UTM
    gdf = gdf.to_crs(epsg)
    
    # Add datetime as string for export
    if 'datetime' in gdf.columns:
        gdf['datetime_str'] = pd.to_datetime(gdf['datetime']).astype(str)
    
    return gdf


def create_ellipse_layer(usbl_df, utm_zone, northern, epsg, n_points=12):
    """Create GeoDataFrame of error ellipses"""
    # Add UTM coordinates
    ellipse_df = add_utm_coords(
        usbl_df,
        lat_col="latitude_deg",
        lon_col="longitude_deg",
        utm_zone=utm_zone,
        northern=northern
    )
    
    # Build ellipse polygons
    geometries = [
        ellipse_polygon(
            row.X_Center, row.Y_Center, 
            row.hor_err_major, row.hor_err_minor, row.hor_err_dir,
            n_points=n_points
        )
        for idx, row in ellipse_df.iterrows()
    ]
    
    gdf = gpd.GeoDataFrame(
        ellipse_df,
        geometry=geometries,
        crs=epsg
    )
    
    # Add datetime as string for export
    if 'datetime' in gdf.columns:
        gdf['datetime_str'] = pd.to_datetime(gdf['datetime']).astype(str)
    
    return gdf


def main():
    parser = argparse.ArgumentParser(
        description="Export entire cruise USBL data to GeoPackage with points and error ellipses"
    )
    parser.add_argument(
        "--cruise_name",
        required=True,
        help="Name of cruise to export"
    )
    parser.add_argument(
        "--output",
        help="Output filename (default: <cruise_name>_usbl.gpkg)"
    )
    parser.add_argument(
        "--ellipse_points",
        type=int,
        default=12,
        help="Number of points per ellipse polygon (default: 12)"
    )
    
    args = parser.parse_args()
    
    # Get cruise info
    print(f"🔍 Looking up cruise: {args.cruise_name}")
    cruise_id, cruise_name = get_cruise_info(args.cruise_name)
    print(f"✓ Found cruise_id: {cruise_id}")
    
    # Get cores and USBL files
    print(f"📊 Loading cores and USBL files...")
    cores, usbl_files = get_cores_and_usbl(cruise_id)
    print(f"✓ Found {len(cores)} cores, {len(usbl_files)} USBL files")
    
    # Parse core times
    cores_with_times = parse_core_times(cores)
    print(f"✓ Parsed times for {len(cores_with_times)} cores")
    
    # Parse USBL file times
    usbl_files["start_time"] = pd.to_datetime(usbl_files["start_time"], errors="coerce")
    usbl_files["end_time"] = pd.to_datetime(usbl_files["end_time"], errors="coerce")
    
    # Collect all USBL data to determine UTM zone
    print(f"📍 Loading USBL data to determine UTM zone...")
    all_cores_usbl_list = []
    
    for idx, core in cores_with_times.iterrows():
        matched_files = match_usbl_to_core(core, usbl_files)
        if matched_files:
            usbl_data = load_core_usbl(matched_files, usbl_files)
            if usbl_data is not None:
                all_cores_usbl_list.append(usbl_data)
    
    if not all_cores_usbl_list:
        print(f"❌ Error: No USBL data found for any cores")
        sys.exit(1)
    
    all_cores_usbl = pd.concat(all_cores_usbl_list)
    utm_zone, northern, epsg = determine_utm_zone(all_cores_usbl)
    
    # Determine output directory and filename
    usbl_dir = get_full_path("usbl_data")
    
    if args.output:
        # If user provides full path, use it as-is
        if os.path.isabs(args.output):
            output_file = args.output
        else:
            # If relative path, put it in usbl_data directory
            output_file = os.path.join(usbl_dir, args.output)
    else:
        output_file = os.path.join(usbl_dir, f"{cruise_name}_usbl.gpkg")
    
    # Remove existing file if it exists
    if os.path.exists(output_file):
        print(f"🗑️  Removing existing file: {output_file}")
        os.remove(output_file)
    
    print(f"📦 Creating GeoPackage: {output_file}")
    print(f"🔧 Using {args.ellipse_points} points per ellipse")
    print()
    
    # Process each core
    cores_processed = 0
    cores_skipped = 0
    
    for idx, core in cores_with_times.iterrows():
        core_name = core.get("core_name", f"core_{idx}")
        print(f"Processing {core_name}...", end=" ")
        
        # Match USBL files
        matched_files = match_usbl_to_core(core, usbl_files)
        
        if not matched_files:
            print("⊘ No USBL files")
            cores_skipped += 1
            continue
        
        # Load USBL data
        usbl_data = load_core_usbl(matched_files, usbl_files)
        
        if usbl_data is None or usbl_data.empty:
            print("⊘ No USBL data")
            cores_skipped += 1
            continue
        
        try:
            # Create point layer
            points_gdf = create_point_layer(usbl_data, core_name, epsg)
            points_layer = f"{core_name}_points"
            points_gdf.to_file(output_file, layer=points_layer, driver="GPKG")
            
            # Create ellipse layer
            ellipses_gdf = create_ellipse_layer(usbl_data, utm_zone, northern, epsg, n_points=args.ellipse_points)
            ellipses_layer = f"{core_name}_ellipses"
            ellipses_gdf.to_file(output_file, layer=ellipses_layer, driver="GPKG")
            
            print(f"✓ {len(usbl_data)} points")
            cores_processed += 1
            
        except Exception as e:
            print(f"❌ Error: {e}")
            cores_skipped += 1
    
    print()
    print(f"{'='*60}")
    print(f"✅ Export complete!")
    print(f"   Processed: {cores_processed} cores")
    print(f"   Skipped: {cores_skipped} cores")
    print(f"   Output: {output_file}")
    print(f"   Layers: {cores_processed * 2} ({cores_processed} points + {cores_processed} ellipses)")
    print(f"   CRS: {epsg}")
    
    # Get file size
    if os.path.exists(output_file):
        file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
        print(f"   File size: {file_size_mb:.1f} MB")
    
    print(f"{'='*60}")


if __name__ == "__main__":
    main()