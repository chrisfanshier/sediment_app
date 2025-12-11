"""
Central VM Sync Receiver - Flask API
Receives pending data from ships and writes to central database
Run: python sync_api.py
Listens on: http://10.129.222.192:5910
"""

from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

app = Flask(__name__)

# --- Database config ---
PG_DB = {
    "dbname": "sediment_cores",
    "user": "postgres",
    "password": "madmaxfuryroad",
    "host": "localhost",
    "port": 5432
}

# Tables that can be synced (in dependency order)
SYNC_TABLES = {
    'vessels': 'vessel_id',
    'cruises': 'cruise_id',
    'cores': 'core_id',
    'sections': 'section_id',
    'mscl_files': 'file_id',
    'sensor_files': 'file_id',
    'winch_data': 'winch_file_id',
}

def get_pg_conn():
    return psycopg2.connect(**PG_DB)

@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat()
    })

@app.route("/sync", methods=["POST"])
def receive_sync():
    """
    Main sync endpoint - receives batch data from ship
    Expects JSON payload:
    {
        "ship_name": "RV_ATLANTIS",
        "timestamp": "2024-12-11T10:30:00",
        "data": {
            "vessels": [
                {"ship_id": 1, "central_id": null, "data": {...}},
                ...
            ],
            "cores": [...]
        }
    }
    """
    
    try:
        payload = request.get_json()
        
        ship_name = payload.get('ship_name', 'unknown')
        sync_timestamp = payload.get('timestamp')
        data = payload.get('data', {})
        
        print(f"\n{'='*70}")
        print(f"📥 Received sync from: {ship_name}")
        print(f"   Timestamp: {sync_timestamp}")
        print(f"{'='*70}\n")
        
        conn = get_pg_conn()
        cur = conn.cursor()
        
        synced_count = 0
        error_count = 0
        errors = []
        id_mappings = {}  # For returning new IDs to ship
        table_counts = {}
        
        # Process each table in dependency order
        for table_name in SYNC_TABLES.keys():
            if table_name not in data:
                continue
                
            records = data[table_name]
            id_column = SYNC_TABLES[table_name]
            table_synced = 0
            id_mappings[table_name] = {}
            
            print(f"📋 Processing {table_name}: {len(records)} records")
            
            for record in records:
                try:
                    ship_id = record.get('ship_id')
                    central_id = record.get('central_id')
                    record_data = record.get('data', {})
                    
                    if not central_id:
                        # NEW RECORD - INSERT
                        columns = list(record_data.keys())
                        values = [record_data[col] for col in columns]
                        placeholders = ','.join(['%s'] * len(columns))
                        colnames = ','.join(columns)
                        
                        insert_query = f"""
                            INSERT INTO {table_name} ({colnames})
                            VALUES ({placeholders})
                            RETURNING {id_column}
                        """
                        
                        cur.execute(insert_query, values)
                        new_central_id = cur.fetchone()[0]
                        conn.commit()
                        
                        # Store mapping so ship can update its central_id
                        id_mappings[table_name][ship_id] = new_central_id
                        table_synced += 1
                        synced_count += 1
                        
                        print(f"  ✓ Inserted {table_name} ship_id={ship_id} → central_id={new_central_id}")
                        
                    else:
                        # EXISTING RECORD - UPDATE
                        columns = list(record_data.keys())
                        values = [record_data[col] for col in columns]
                        values.append(central_id)  # For WHERE clause
                        
                        set_clause = ','.join([f"{col} = %s" for col in columns])
                        
                        update_query = f"""
                            UPDATE {table_name}
                            SET {set_clause}
                            WHERE {id_column} = %s
                        """
                        
                        cur.execute(update_query, values)
                        conn.commit()
                        
                        # Keep existing mapping
                        id_mappings[table_name][ship_id] = central_id
                        table_synced += 1
                        synced_count += 1
                        
                        print(f"  ✓ Updated {table_name} central_id={central_id}")
                
                except Exception as e:
                    error_count += 1
                    error_msg = f"{table_name} ship_id={ship_id}: {str(e)}"
                    errors.append(error_msg)
                    print(f"  ✗ {error_msg}")
                    conn.rollback()
            
            table_counts[table_name] = table_synced
        
        # Log sync to database
        try:
            log_query = """
                INSERT INTO sync_log 
                (sync_timestamp, sync_direction, table_name, records_synced, 
                 conflicts_detected, status, error_message)
                VALUES (CURRENT_TIMESTAMP, 'ship_to_central', %s, %s, %s, %s, %s)
            """
            cur.execute(log_query, (
                ship_name,
                synced_count,
                error_count,
                'success' if error_count == 0 else 'partial',
                '; '.join(errors[:5]) if errors else None  # First 5 errors
            ))
            conn.commit()
        except Exception as e:
            print(f"⚠️  Could not log sync: {e}")
        
        conn.close()
        
        print(f"\n{'='*70}")
        print(f"✅ Sync complete: {synced_count} synced, {error_count} errors")
        print(f"{'='*70}\n")
        
        # Return response for ship to update its local DB
        return jsonify({
            'status': 'success' if error_count == 0 else 'partial',
            'synced_count': synced_count,
            'error_count': error_count,
            'errors': errors,
            'id_mappings': id_mappings,  # Ship uses this to update central_id
            'table_counts': table_counts,
            'timestamp': datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        print(f"\n✗ Sync failed: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


# Keep your original upload endpoint for backwards compatibility
@app.route("/api/upload/<table_name>", methods=["POST"])
def upload_record(table_name):
    """Original single-record upload endpoint"""
    if table_name not in SYNC_TABLES:
        return jsonify({"error": "Table not allowed"}), 403

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    columns = list(data.keys())
    values = [data[col] for col in columns]
    placeholders = ','.join(['%s'] * len(columns))
    colnames = ','.join(columns)

    conn = get_pg_conn()
    cur = conn.cursor()

    try:
        cur.execute(f"INSERT INTO {table_name} ({colnames}) VALUES ({placeholders})", values)
        conn.commit()
        conn.close()
        return jsonify({"status": "inserted", "table": table_name}), 201
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    print("\n" + "="*70)
    print("🚢 CENTRAL SYNC RECEIVER STARTING")
    print("="*70)
    print(f"Listening on: http://0.0.0.0:5910")
    print(f"Health check: http://10.129.222.192:5910/health")
    print(f"Sync endpoint: http://10.129.222.192:5910/sync")
    print(f"Legacy upload: http://10.129.222.192:5910/api/upload/<table>")
    print("="*70 + "\n")
    
    app.run(host="0.0.0.0", port=5910, debug=True)