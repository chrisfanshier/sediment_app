"""
Prepare ship database after restoring from central backup
Run this ON THE SHIP after importing the central database dump

This script will:
1. Add sync tracking columns and triggers
2. Let you select which cruises to keep (delete the rest)
3. Mark all existing data as synced from central
"""

from db_util import get_connection
from sqlalchemy import text

def add_sync_tracking():
    """Add sync columns and triggers to existing database"""
    
    print("=" * 70)
    print("PREPARING SHIP DATABASE")
    print("=" * 70)
    
    with get_connection() as conn:
        print("\n1. Adding sync tracking columns...")
        
        conn.execute(text("""
            -- Add to vessels
            ALTER TABLE vessels 
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS created_on_ship BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS sync_status VARCHAR(20) DEFAULT 'synced',
                ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP,
                ADD COLUMN IF NOT EXISTS central_id INTEGER;
            
            -- Add to cruises
            ALTER TABLE cruises 
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS created_on_ship BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS sync_status VARCHAR(20) DEFAULT 'synced',
                ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP,
                ADD COLUMN IF NOT EXISTS central_id INTEGER;
            
            -- Add to cores
            ALTER TABLE cores 
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS created_on_ship BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS sync_status VARCHAR(20) DEFAULT 'synced',
                ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP,
                ADD COLUMN IF NOT EXISTS central_id INTEGER;
            
            -- Add to sections
            ALTER TABLE sections 
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS created_on_ship BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS sync_status VARCHAR(20) DEFAULT 'synced',
                ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP,
                ADD COLUMN IF NOT EXISTS central_id INTEGER;
            
            -- Add to mscl_files
            ALTER TABLE mscl_files 
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS created_on_ship BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS sync_status VARCHAR(20) DEFAULT 'synced',
                ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP,
                ADD COLUMN IF NOT EXISTS file_synced BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS central_id INTEGER;
            
            -- Add to sensor_files
            ALTER TABLE sensor_files 
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS created_on_ship BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS sync_status VARCHAR(20) DEFAULT 'synced',
                ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP,
                ADD COLUMN IF NOT EXISTS file_synced BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS central_id INTEGER;
                          
                        -- Add to winch_data
            ALTER TABLE winch_data 
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS created_on_ship BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS sync_status VARCHAR(20) DEFAULT 'synced',
                ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP,
                ADD COLUMN IF NOT EXISTS file_synced BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS central_id INTEGER;

            -- Add to usbl_files
            ALTER TABLE usbl_files
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS created_on_ship BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS sync_status VARCHAR(20) DEFAULT 'synced',
                ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP,
                ADD COLUMN IF NOT EXISTS file_synced BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS central_id INTEGER;

            -- Add to core_media
            ALTER TABLE core_media
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS created_on_ship BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS sync_status VARCHAR(20) DEFAULT 'synced',
                ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP,
                ADD COLUMN IF NOT EXISTS file_synced BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS central_id INTEGER;

            -- Add to capture_devices
            ALTER TABLE capture_devices
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ADD COLUMN IF NOT EXISTS created_on_ship BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS sync_status VARCHAR(20) DEFAULT 'synced',
                ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP,
                ADD COLUMN IF NOT EXISTS central_id INTEGER;
        """))
        conn.commit()
        print("  ✓ Sync columns added")
        
        print("\n2. Populating central_id with original IDs...")
        conn.execute(text("""
            UPDATE vessels SET central_id = vessel_id WHERE central_id IS NULL;
            UPDATE cruises SET central_id = cruise_id WHERE central_id IS NULL;
            UPDATE cores SET central_id = core_id WHERE central_id IS NULL;
            UPDATE sections SET central_id = section_id WHERE central_id IS NULL;
            UPDATE mscl_files SET central_id = file_id WHERE central_id IS NULL;
            UPDATE sensor_files SET central_id = file_id WHERE central_id IS NULL;
            UPDATE winch_data SET central_id = winch_file_id WHERE central_id IS NULL;
            UPDATE usbl_files SET central_id = usbl_file_id WHERE central_id IS NULL;
            UPDATE core_media SET central_id = media_id WHERE central_id IS NULL;
            UPDATE capture_devices SET central_id = capture_device_id WHERE central_id IS NULL;
        """))
        conn.commit()
        print("  ✓ Central IDs populated")
        
        print("\n3. Creating sync log table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sync_log (
                sync_id SERIAL PRIMARY KEY,
                sync_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sync_direction VARCHAR(10),
                table_name VARCHAR(50),
                records_synced INTEGER,
                conflicts_detected INTEGER,
                status VARCHAR(20),
                error_message TEXT
            );
        """))
        conn.commit()
        print("  ✓ Sync log created")
        
        print("\n4. Creating file upload tracking table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS file_upload_tracking (
                upload_id SERIAL PRIMARY KEY,
                table_name VARCHAR(50) NOT NULL,
                record_id INTEGER NOT NULL,
                relative_path TEXT NOT NULL,
                file_size_bytes BIGINT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                upload_status VARCHAR(20) DEFAULT 'success',
                error_message TEXT,
                UNIQUE(table_name, record_id)
            );
            
            CREATE INDEX IF NOT EXISTS idx_file_upload_tracking_lookup 
            ON file_upload_tracking(table_name, record_id);
            
            CREATE INDEX IF NOT EXISTS idx_file_upload_tracking_uploaded_at 
            ON file_upload_tracking(uploaded_at DESC);
        """))
        conn.commit()
        print("  ✓ File upload tracking created")
        
        print("\n5. Creating triggers...")
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION update_modified_at()
            RETURNS TRIGGER AS $$
            BEGIN
                -- If sync is marking as 'synced', don't interfere
                IF NEW.sync_status = 'synced' AND OLD.sync_status = 'pending' THEN
                    RETURN NEW;  -- Let the sync update happen without interference
                END IF;
                
                -- For all other updates, update modified_at and mark pending if created on ship
                NEW.modified_at = CURRENT_TIMESTAMP;
                IF NEW.created_on_ship = TRUE THEN
                    NEW.sync_status = 'pending';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            
            DROP TRIGGER IF EXISTS vessels_modified ON vessels;
            DROP TRIGGER IF EXISTS cruises_modified ON cruises;
            DROP TRIGGER IF EXISTS cores_modified ON cores;
            DROP TRIGGER IF EXISTS sections_modified ON sections;
            DROP TRIGGER IF EXISTS mscl_files_modified ON mscl_files;
            DROP TRIGGER IF EXISTS sensor_files_modified ON sensor_files;
            DROP TRIGGER IF EXISTS winch_data_modified ON winch_data;
            DROP TRIGGER IF EXISTS usbl_files_modified ON usbl_files;
            DROP TRIGGER IF EXISTS core_media_modified ON core_media;
            DROP TRIGGER IF EXISTS capture_devices_modified ON capture_devices;
            
            CREATE TRIGGER vessels_modified BEFORE UPDATE ON vessels 
                FOR EACH ROW EXECUTE FUNCTION update_modified_at();
            CREATE TRIGGER cruises_modified BEFORE UPDATE ON cruises 
                FOR EACH ROW EXECUTE FUNCTION update_modified_at();
            CREATE TRIGGER cores_modified BEFORE UPDATE ON cores 
                FOR EACH ROW EXECUTE FUNCTION update_modified_at();
            CREATE TRIGGER sections_modified BEFORE UPDATE ON sections 
                FOR EACH ROW EXECUTE FUNCTION update_modified_at();
            CREATE TRIGGER mscl_files_modified BEFORE UPDATE ON mscl_files 
                FOR EACH ROW EXECUTE FUNCTION update_modified_at();
            CREATE TRIGGER sensor_files_modified BEFORE UPDATE ON sensor_files 
                FOR EACH ROW EXECUTE FUNCTION update_modified_at();
            CREATE TRIGGER winch_data_modified BEFORE UPDATE ON winch_data
                FOR EACH ROW EXECUTE FUNCTION update_modified_at();
            CREATE TRIGGER usbl_files_modified BEFORE UPDATE ON usbl_files
                FOR EACH ROW EXECUTE FUNCTION update_modified_at();
            CREATE TRIGGER core_media_modified BEFORE UPDATE ON core_media
                FOR EACH ROW EXECUTE FUNCTION update_modified_at();
            CREATE TRIGGER capture_devices_modified BEFORE UPDATE ON capture_devices
                FOR EACH ROW EXECUTE FUNCTION update_modified_at();          
        """))
        conn.commit()
        print("  ✓ Triggers created")

def select_cruises_to_keep():
    """Interactive: select which cruises to keep on ship"""
    
    with get_connection() as conn:
        result = conn.execute(text("""
            SELECT c.cruise_id, c.cruise_name, v.vessel_name, 
                   c.start_date, c.end_date,
                   COUNT(DISTINCT co.core_id) as core_count
            FROM cruises c
            LEFT JOIN vessels v ON c.vessel_id = v.vessel_id
            LEFT JOIN cores co ON c.cruise_id = co.cruise_id
            GROUP BY c.cruise_id, c.cruise_name, v.vessel_name, c.start_date, c.end_date
            ORDER BY c.start_date DESC
        """))
        cruises = result.fetchall()
    
    print(f"\n5. Available cruises ({len(cruises)} total):\n")
    print(f"{'ID':<5} {'Cruise':<30} {'Vessel':<20} {'Cores':<8} {'Dates'}")
    print("-" * 90)
    for c in cruises:
        date_str = f"{c.start_date} to {c.end_date}" if c.start_date else "N/A"
        print(f"{c.cruise_id:<5} {c.cruise_name:<30} {c.vessel_name or 'N/A':<20} {c.core_count:<8} {date_str}")
    
    print("\nEnter cruise IDs to KEEP (comma-separated, or 'all' to keep everything):")
    selection = input("> ").strip()
    
    if selection.lower() == 'all':
        print("  ✓ Keeping all cruises")
        return
    
    try:
        keep_ids = [int(x.strip()) for x in selection.split(',')]
    except ValueError:
        print("Invalid input. Keeping all cruises.")
        return
    
    # Delete unwanted cruises and related data
    with get_connection() as conn:
        all_ids = [c.cruise_id for c in cruises]
        delete_ids = [cid for cid in all_ids if cid not in keep_ids]
        
        if delete_ids:
            delete_str = ','.join(map(str, delete_ids))
            
            print(f"\n  Deleting {len(delete_ids)} unwanted cruises...")

            # Delete ct_xml rows by section_id and core_id to satisfy both constraints
            conn.execute(text(f"DELETE FROM ct_xml WHERE section_id IN (SELECT section_id FROM sections WHERE core_id IN (SELECT core_id FROM cores WHERE cruise_id IN ({delete_str})))"))
            conn.execute(text(f"DELETE FROM ct_xml WHERE core_id IN (SELECT core_id FROM cores WHERE cruise_id IN ({delete_str}))"))
            conn.execute(text(f"DELETE FROM sensor_files WHERE core_id IN (SELECT core_id FROM cores WHERE cruise_id IN ({delete_str}))"))
            conn.execute(text(f"DELETE FROM sensor_data WHERE core_id IN (SELECT core_id FROM cores WHERE cruise_id IN ({delete_str}))"))
            conn.execute(text(f"DELETE FROM mscl_files WHERE core_id IN (SELECT core_id FROM cores WHERE cruise_id IN ({delete_str}))"))
            conn.execute(text(f"DELETE FROM core_media WHERE core_id IN (SELECT core_id FROM cores WHERE cruise_id IN ({delete_str}))"))
            conn.execute(text(f"DELETE FROM files WHERE core_id IN (SELECT core_id FROM cores WHERE cruise_id IN ({delete_str}))"))
            conn.execute(text(f"DELETE FROM associated_files WHERE core_id IN (SELECT core_id FROM cores WHERE cruise_id IN ({delete_str}))"))
            conn.execute(text(f"DELETE FROM physical_properties WHERE core_id IN (SELECT core_id FROM cores WHERE cruise_id IN ({delete_str}))"))
            conn.execute(text(f"DELETE FROM sensor_analysis_results WHERE core_id IN (SELECT core_id FROM cores WHERE cruise_id IN ({delete_str}))"))
            conn.execute(text(f"DELETE FROM recoil_analysis_results WHERE core_id IN (SELECT core_id FROM cores WHERE cruise_id IN ({delete_str}))"))
            conn.execute(text(f"DELETE FROM sections WHERE core_id IN (SELECT core_id FROM cores WHERE cruise_id IN ({delete_str}))"))
            conn.execute(text(f"DELETE FROM cores WHERE cruise_id IN ({delete_str})"))
            conn.execute(text(f"DELETE FROM winch_data WHERE cruise_id IN ({delete_str})"))
            conn.execute(text(f"DELETE FROM usbl_files WHERE cruise_id IN ({delete_str})"))
            conn.execute(text(f"DELETE FROM cruises WHERE cruise_id IN ({delete_str})"))
            
            conn.commit()
            
            print(f"  ✓ Deleted {len(delete_ids)} cruises and their related data")
        else:
            print("  ✓ All cruises selected")

def create_sensor_analysis_table():
    """Create the sensor_analysis_results table for sensor_tool DB export."""
    print("\n4. Creating sensor_analysis_results table...")

    with get_connection() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sensor_analysis_results (
                result_id       SERIAL PRIMARY KEY,
                core_id         INTEGER REFERENCES cores(core_id),
                analyzed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                -- Trip detection (real columns — queried by recoil tool)
                trip_index              INTEGER,
                trip_datetime           TIMESTAMP,

                -- Piston position (real columns — queried by recoil tool)
                start_core_index        INTEGER,
                start_core_datetime     TIMESTAMP,

                -- Calculation results (all real columns — queried/reported directly)
                result_recoil_max       FLOAT,
                result_recoil_time_s    FLOAT,
                result_fall_dist        FLOAT,
                result_suck_in          FLOAT,
                result_recoil_start     FLOAT,
                result_freefall_start   FLOAT,
                result_piston_suck      FLOAT,
                result_seafloor         FLOAT,
                result_piston_alt       FLOAT,
                result_pen_deficit      FLOAT,
                result_freefall_est     FLOAT,
                result_eff_trig_line    FLOAT,
                trigger_pen_m           FLOAT,

                -- Winch alignment (real columns — see migrations/001)
                winch_trip_index        INTEGER,
                winch_trip_datetime     TIMESTAMP,
                winch_time_offset_sec   FLOAT,

                -- All input parameters stored as JSONB (no schema migrations needed)
                -- Keys: depth_offset, time_offset, trip, piston, calc_inputs, calc_notes
                params                  JSONB,

                -- Sync tracking (same pattern as all other tables)
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                modified_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_on_ship BOOLEAN DEFAULT TRUE,
                sync_status     VARCHAR(20) DEFAULT 'pending',
                last_synced_at  TIMESTAMP,
                central_id      INTEGER
            );

            DROP TRIGGER IF EXISTS sensor_analysis_results_modified
                ON sensor_analysis_results;

            CREATE TRIGGER sensor_analysis_results_modified
                BEFORE UPDATE ON sensor_analysis_results
                FOR EACH ROW EXECUTE FUNCTION update_modified_at();
        """))

        # CREATE TABLE IF NOT EXISTS leaves an existing table untouched, so
        # columns added after a database was first prepared must be backfilled.
        conn.execute(text("""
            ALTER TABLE sensor_analysis_results
                ADD COLUMN IF NOT EXISTS result_recoil_time_s  FLOAT,
                ADD COLUMN IF NOT EXISTS result_eff_trig_line  FLOAT,
                ADD COLUMN IF NOT EXISTS winch_trip_index      INTEGER,
                ADD COLUMN IF NOT EXISTS winch_trip_datetime   TIMESTAMP,
                ADD COLUMN IF NOT EXISTS winch_time_offset_sec FLOAT;
        """))
        conn.commit()
    print("  ✓ sensor_analysis_results table ready")


def create_recoil_analysis_results_table():
    """Create the recoil_analysis_results table for the recoil fitting tool."""
    print("\n5. Creating recoil_analysis_results table...")

    with get_connection() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS recoil_analysis_results (
                id                   SERIAL PRIMARY KEY,
                core_id              INTEGER NOT NULL REFERENCES cores(core_id),
                curve_type           VARCHAR(32) NOT NULL,

                deployment_params    JSONB,

                trip_time_epoch      DOUBLE PRECISION,
                fit_end_epoch        DOUBLE PRECISION,

                -- Physics model tuning + outputs (NULL for empirical rows)
                E_gpa                DOUBLE PRECISION,
                C_drag               DOUBLE PRECISION,
                v0_ms                DOUBLE PRECISION,
                peak_displacement_m  DOUBLE PRECISION,
                peak_time_s          DOUBLE PRECISION,
                k_nm                 DOUBLE PRECISION,

                -- Empirical fit parameters (NULL for physics rows)
                A_m                  DOUBLE PRECISION,
                tau_s                DOUBLE PRECISION,
                omega_rads           DOUBLE PRECISION,

                saved_at             TIMESTAMPTZ DEFAULT now(),

                -- Sync tracking
                created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                modified_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_on_ship      BOOLEAN DEFAULT TRUE,
                sync_status          VARCHAR(20) DEFAULT 'pending',
                last_synced_at       TIMESTAMP,
                central_id           INTEGER,

                UNIQUE (core_id, curve_type)
            );

            DROP TRIGGER IF EXISTS recoil_analysis_results_modified
                ON recoil_analysis_results;

            CREATE TRIGGER recoil_analysis_results_modified
                BEFORE UPDATE ON recoil_analysis_results
                FOR EACH ROW EXECUTE FUNCTION update_modified_at();
        """))
        conn.commit()
    print("  ✓ recoil_analysis_results table ready")


def main():
    print("\n")
    print("=" * 70)
    print("SHIP DATABASE SETUP")
    print("=" * 70)
    print("\nThis script prepares a restored central database for ship operations.")
    print("It will add sync tracking and let you choose which cruises to keep.\n")
    
    confirm = input("Have you already restored the central database dump? (yes/no): ").strip().lower()
    if confirm != 'yes':
        print("\nPlease restore the database first:")
        print("  1. psql -U postgres -d postgres -c \"CREATE DATABASE sediment_cores\"")
        print("  2. psql -U postgres -d sediment_cores -f central_backup.sql")
        print("\nThen run this script again.")
        return
    
    add_sync_tracking()
    create_sensor_analysis_table()
    create_recoil_analysis_results_table()
    select_cruises_to_keep()
    
    print("\n" + "=" * 70)
    print("SHIP DATABASE READY!")
    print("=" * 70)
    print("\nDatabase is configured for at-sea operations.")
    print("New cores created on ship will be automatically flagged for sync to central.")
    print("\n")

if __name__ == "__main__":
    main()