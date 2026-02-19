"""
Standalone script to batch export sensor data for cores with sensor files.
Generates CSV exports similar to multiplot_st.py for selected cruise.
"""

import os
import pandas as pd
from datetime import datetime
from sqlalchemy import text
from db_util import get_connection
from utils import process_rsk_data, process_star_oddi_data
from config import get_full_path

def should_include_column(col_name):
    """Check if column should be included based on keywords"""
    col_lower = col_name.lower()
    keywords = ['depth', 'pressure', 'acceleration', 'g', 'tilt']
    return any(keyword in col_lower for keyword in keywords)

def load_sensor_data(sensor_file_id):
    """Load sensor data from database and file"""
    with get_connection() as conn:
        query = text("""
            SELECT sf.*, c.core_name 
            FROM sensor_files sf 
            JOIN cores c ON sf.core_id = c.core_id 
            WHERE sf.file_id = :file_id
        """)
        sensor_info = conn.execute(query, {"file_id": sensor_file_id}).fetchone()
    
    if not sensor_info:
        return None, None
    
    relative_path = os.path.join(sensor_info.file_path, sensor_info.file_name)
    file_ext = os.path.splitext(sensor_info.file_name)[1].lower()
    sensor_type = sensor_info.sensor_type.lower() if sensor_info.sensor_type else ""
    
    try:
        if file_ext == '.rsk' or 'rbr' in sensor_type:
            df = process_rsk_data(relative_path)
        elif file_ext in ['.dat', '.acc'] or 'star-oddi' in sensor_type or 'staroddi' in sensor_type:
            df = process_star_oddi_data(relative_path)
        else:
            return None, None

        if df is not None:
            if 'datetime' not in df.columns:
                if 'Timestamp' in df.columns:
                    df['datetime'] = df['Timestamp']
                else:
                    df['datetime'] = pd.date_range(start='2024-01-01', periods=len(df), freq='1s')
            return df, sensor_info
        else:
            return None, None
    except Exception as e:
        print(f"  ❌ Error loading sensor data: {e}")
        return None, None

def get_cruises():
    """Get list of available cruises"""
    with get_connection() as conn:
        query = text("""
            SELECT DISTINCT c.cruise_id, c.cruise_name, v.vessel_name
            FROM cruises c
            LEFT JOIN vessels v ON c.vessel_id = v.vessel_id
            ORDER BY c.cruise_name
        """)
        result = conn.execute(query)
        return result.fetchall()

def get_cores_for_cruise(cruise_id):
    """Get cores with core_type_id = 1 and sensor files"""
    with get_connection() as conn:
        query = text("""
            SELECT DISTINCT c.core_id, c.core_name, ct.core_type_name,
                   c.core_length, c.trigger_core_length, c.trigger_line_length,
                   c.scope, c.pig_weights, w.wire_type
            FROM cores c
            LEFT JOIN core_types ct ON c.core_type_id = ct.core_type_id
            LEFT JOIN sensor_files sf ON c.core_id = sf.core_id
            LEFT JOIN wire w ON c.wire_type_id = w.wire_type_id
            WHERE c.cruise_id = :cruise_id 
            AND c.core_type_id = 1
            AND sf.file_id IS NOT NULL
            ORDER BY c.core_name
        """)
        result = conn.execute(query, {"cruise_id": cruise_id})
        return result.fetchall()

def get_sensor_files_for_core(core_id):
    """Get all sensor files for a core"""
    with get_connection() as conn:
        query = text("""
            SELECT file_id, file_name, sensor_type, sensor_location 
            FROM sensor_files 
            WHERE core_id = :core_id 
            ORDER BY file_name
        """)
        result = conn.execute(query, {"core_id": core_id})
        return result.fetchall()

def create_export_dataframe(sensor_files_info, core_name):
    """Create export dataframe with all matching columns from all sensor files"""
    
    export_data = []
    skipped_files = []
    included_files = []
    
    print(f"\n  Processing {len(sensor_files_info)} sensor files...")
    
    for sensor_info in sensor_files_info:
        file_id = sensor_info.file_id
        file_name = sensor_info.file_name
        
        print(f"    📄 {file_name}...", end=" ")
        
        df, info = load_sensor_data(file_id)
        
        if df is None:
            print("❌ Failed to parse")
            skipped_files.append((file_name, "Failed to parse"))
            continue
        
        # Find columns that match our keywords
        cols_to_export = [col for col in df.columns if col != 'datetime' and should_include_column(col)]
        
        if not cols_to_export:
            print("⚠️  No matching columns")
            skipped_files.append((file_name, "No matching columns (depth/pressure/acceleration/g/tilt)"))
            continue
        
        print(f"✅ {len(cols_to_export)} columns: {', '.join(cols_to_export)}")
        
        # Create file identifier
        if info.sensor_location:
            file_identifier = f"{info.sensor_location}_{info.file_name}"
        else:
            file_identifier = info.file_name
        
        # Export matching columns
        for col in cols_to_export:
            if col in df.columns and not df[col].isna().all():
                df_export = df[['datetime', col]].copy()
                df_export.rename(columns={col: f"{file_identifier}_{col}"}, inplace=True)
                export_data.append(df_export)
        
        included_files.append(file_name)
    
    # Merge all data on datetime
    if export_data:
        print(f"\n  📊 Merging {len(export_data)} column(s)...")
        final_export = export_data[0]
        for df_next in export_data[1:]:
            final_export = pd.merge(final_export, df_next, on='datetime', how='outer')
        
        # Sort by datetime
        final_export = final_export.sort_values('datetime').reset_index(drop=True)
        
        print(f"  ✅ Final: {len(final_export):,} rows × {len(final_export.columns):,} columns")
        
        return final_export, included_files, skipped_files
    else:
        return pd.DataFrame(), included_files, skipped_files

def main():
    """Main execution function"""
    print("=" * 80)
    print("SEDIMENT APP - BATCH SENSOR DATA EXPORT")
    print("=" * 80)
    
    # Get available cruises
    print("\n📋 Fetching available cruises...")
    cruises = get_cruises()
    
    if not cruises:
        print("❌ No cruises found in database")
        return
    
    print(f"\n✅ Found {len(cruises)} cruise(s):\n")
    for idx, cruise in enumerate(cruises, 1):
        vessel = cruise.vessel_name if cruise.vessel_name else "Unknown Vessel"
        print(f"  {idx}. {cruise.cruise_name} - {vessel}")
    
    # Prompt for cruise selection
    while True:
        try:
            selection = input(f"\nSelect cruise (1-{len(cruises)}): ").strip()
            cruise_idx = int(selection) - 1
            if 0 <= cruise_idx < len(cruises):
                selected_cruise = cruises[cruise_idx]
                break
            else:
                print(f"❌ Please enter a number between 1 and {len(cruises)}")
        except ValueError:
            print("❌ Please enter a valid number")
        except KeyboardInterrupt:
            print("\n\n❌ Export cancelled by user")
            return
    
    cruise_id = selected_cruise.cruise_id
    cruise_name = selected_cruise.cruise_name
    vessel_name = selected_cruise.vessel_name if selected_cruise.vessel_name else "Unknown"
    
    print(f"\n{'=' * 80}")
    print(f"Selected: {cruise_name} - {vessel_name}")
    print(f"{'=' * 80}")
    
    # Get cores for this cruise
    print(f"\n🔍 Finding cores with sensor files (core_type_id = 1)...")
    cores = get_cores_for_cruise(cruise_id)
    
    if not cores:
        print(f"❌ No cores found with sensor files for {cruise_name}")
        return
    
    print(f"✅ Found {len(cores)} core(s) to process:\n")
    for core in cores:
        print(f"  - {core.core_name} ({core.core_type_name})")
    
    # Create output directory
    output_dir = f"{cruise_name}_sensor_export"
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n📁 Output directory: {output_dir}/")
    
    # Process each core
    export_summary = []
    
    for core in cores:
        print(f"\n{'─' * 80}")
        print(f"🔬 Processing: {core.core_name}")
        print(f"{'─' * 80}")
        
        # Get sensor files for this core
        sensor_files = get_sensor_files_for_core(core.core_id)
        
        if not sensor_files:
            print(f"  ⚠️  No sensor files found for {core.core_name}")
            continue
        
        print(f"  Found {len(sensor_files)} sensor file(s)")
        
        # Create export dataframe
        export_df, included_files, skipped_files = create_export_dataframe(sensor_files, core.core_name)
        
        if export_df.empty:
            print(f"  ❌ No data to export for {core.core_name}")
            export_summary.append({
                'core': core.core_name,
                'status': 'FAILED',
                'reason': 'No exportable data',
                'files_included': 0,
                'files_skipped': len(skipped_files)
            })
            continue
        
        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"sensor_export_{cruise_name}_{core.core_name}_{timestamp}.csv"
        filepath = os.path.join(output_dir, filename)
        
        # Create CSV with metadata header
        with open(filepath, 'w') as f:
            # Write metadata as comments
            f.write(f"# Export from Sediment App - Batch Export\n")
            f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Cruise: {cruise_name} - {vessel_name}\n")
            f.write(f"# Core: {core.core_name}\n")
            f.write(f"# Core Type: {core.core_type_name}\n")
            # Always include these fields
            def _val(attr):
                v = getattr(core, attr, None)
                return v if v is not None else "N/A"
            f.write(f"# Core length: {_val('core_length')}\n")
            f.write(f"# Trigger core length: {_val('trigger_core_length')}\n")
            f.write(f"# Trigger line length: {_val('trigger_line_length')}\n")
            f.write(f"# Scope: {_val('scope')}\n")
            f.write(f"# Pig weights: {_val('pig_weights')}\n")
            f.write(f"# Wire type: {_val('wire_type')}\n")
            f.write(f"# Sensor files included: {len(included_files)}\n")
            for fname in included_files:
                f.write(f"#   - {fname}\n")
            f.write(f"# Columns: Depth, Pressure, Acceleration, g, Tilt\n")
            f.write(f"# NOTE: Unprocessed raw data (no offsets applied)\n")
            f.write(f"# Data shape: {len(export_df):,} rows × {len(export_df.columns):,} columns\n")
            if export_df['datetime'].notna().any():
                f.write(f"# Time range: {export_df['datetime'].min()} to {export_df['datetime'].max()}\n")
            if skipped_files:
                f.write(f"#\n# Skipped files:\n")
                for fname, reason in skipped_files:
                    f.write(f"#   - {fname}: {reason}\n")
            f.write("#\n")
            
            # Write the actual data
            export_df.to_csv(f, index=False, float_format='%.6f')
        
        print(f"\n  💾 Saved: {filename}")
        print(f"  📊 Size: {len(export_df):,} rows × {len(export_df.columns):,} columns")
        
        # Add to summary
        export_summary.append({
            'core': core.core_name,
            'status': 'SUCCESS',
            'filename': filename,
            'rows': len(export_df),
            'columns': len(export_df.columns),
            'files_included': len(included_files),
            'files_skipped': len(skipped_files)
        })
    
    # Print final summary
    print(f"\n{'=' * 80}")
    print("EXPORT SUMMARY")
    print(f"{'=' * 80}\n")
    
    successful = sum(1 for s in export_summary if s['status'] == 'SUCCESS')
    failed = sum(1 for s in export_summary if s['status'] == 'FAILED')
    
    print(f"✅ Successful exports: {successful}")
    print(f"❌ Failed exports: {failed}")
    print(f"📁 Output directory: {output_dir}/")
    
    if successful > 0:
        print(f"\n📊 Export Details:")
        for summary in export_summary:
            if summary['status'] == 'SUCCESS':
                print(f"\n  {summary['core']}:")
                print(f"    File: {summary['filename']}")
                print(f"    Data: {summary['rows']:,} rows × {summary['columns']:,} columns")
                print(f"    Included: {summary['files_included']} sensor files")
                if summary['files_skipped'] > 0:
                    print(f"    Skipped: {summary['files_skipped']} files")
    
    if failed > 0:
        print(f"\n⚠️  Failed Exports:")
        for summary in export_summary:
            if summary['status'] == 'FAILED':
                print(f"  - {summary['core']}: {summary['reason']}")
    
    print(f"\n{'=' * 80}")
    print("Export complete!")
    print(f"{'=' * 80}\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Export cancelled by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()