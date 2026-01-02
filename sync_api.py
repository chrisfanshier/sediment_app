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
import os
import json

app = Flask(__name__)

# --- Database config ---
PG_DB = {
    "dbname": "sediment_cores",
    "user": "postgres",
    "password": "madmaxfuryroad",
    "host": "localhost",
    "port": 5432
}

# --- File storage config ---
CENTRAL_FILE_ROOT = "/home/server/project/marrsam/marssam_data_files"

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
    Metadata-only sync endpoint.
    Accepts JSON body:
      { "ship_name": "...", "timestamp": "...", "data": { table_name: [ {ship_id, central_id, data}, ... ] } }
    Processes INSERT for records without central_id, UPDATE for records with central_id.
    Returns id_mappings for newly inserted records.
    """
    try:
        payload = request.get_json()
        if not payload:
            return jsonify({"status": "error", "error": "No JSON payload provided"}), 400

        ship_name = payload.get('ship_name', 'unknown')
        sync_timestamp = payload.get('timestamp')
        data = payload.get('data', {})

        print(f"\n{'='*70}")
        print(f"📥 Received metadata sync from: {ship_name}")
        print(f"   Timestamp: {sync_timestamp}")
        print(f"   Tables: {list(data.keys())}")
        print(f"{'='*70}\n")

        conn = get_pg_conn()
        cur = conn.cursor()

        synced_count = 0
        error_count = 0
        errors = []
        id_mappings = {}
        table_counts = {}

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
                        # INSERT
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

                        id_mappings[table_name][ship_id] = new_central_id
                        table_synced += 1
                        synced_count += 1

                        print(f"  ✓ Inserted {table_name} ship_id={ship_id} → central_id={new_central_id}")

                    else:
                        # UPDATE
                        columns = list(record_data.keys())
                        values = [record_data[col] for col in columns]
                        values.append(central_id)
                        set_clause = ','.join([f"{col} = %s" for col in columns])

                        update_query = f"""
                            UPDATE {table_name}
                            SET {set_clause}
                            WHERE {id_column} = %s
                        """
                        cur.execute(update_query, values)
                        conn.commit()

                        id_mappings[table_name][ship_id] = central_id
                        table_synced += 1
                        synced_count += 1

                        print(f"  ✓ Updated {table_name} central_id={central_id}")

                except Exception as e:
                    error_count += 1
                    error_msg = f"{table_name} ship_id={record.get('ship_id')}: {str(e)}"
                    errors.append(error_msg)
                    print(f"  ✗ {error_msg}")
                    conn.rollback()

            table_counts[table_name] = table_synced

        # Log metadata sync
        try:
            cur.execute("""
                INSERT INTO sync_log
                (sync_timestamp, sync_direction, table_name, records_synced, conflicts_detected, status, error_message)
                VALUES (CURRENT_TIMESTAMP, 'ship_metadata', %s, %s, %s, %s, %s)
            """, (
                ship_name,
                synced_count,
                error_count,
                'success' if error_count == 0 else 'partial',
                '; '.join(errors[:5]) if errors else None
            ))
            conn.commit()
        except Exception as e:
            print(f"⚠️ Could not log metadata sync: {e}")
            conn.rollback()

        conn.close()

        print(f"\n{'='*70}")
        print(f"✅ Metadata sync complete: {synced_count} records, {error_count} errors")
        print(f"{'='*70}\n")

        return jsonify({
            'status': 'success' if error_count == 0 else 'partial',
            'synced_count': synced_count,
            'error_count': error_count,
            'errors': errors,
            'id_mappings': id_mappings,
            'table_counts': table_counts,
            'timestamp': datetime.now().isoformat()
        }), 200

    except Exception as e:
        print(f"\n✗ Metadata sync failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'error': str(e)}), 500


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


@app.route("/upload_file", methods=["POST"])
def upload_file():
    """
    File upload endpoint for syncing actual data files.
    Expects:
      - file: The file data (multipart/form-data)
      - relative_path: The relative path from ROOT_DIRECTORY (e.g., "MSCL_Data/cruise123/file.csv")
    Saves file to central location preserving directory structure.
    """
    try:
        if 'file' not in request.files:
            return jsonify({'status': 'error', 'error': 'No file provided'}), 400
        
        if 'relative_path' not in request.form:
            return jsonify({'status': 'error', 'error': 'No relative_path provided'}), 400
        
        file = request.files['file']
        relative_path = request.form['relative_path']
        
        # ADD THIS: Normalize path separators for Linux
        relative_path = relative_path.replace('\\', '/')
        
        # ADD THIS: Strip any leading/trailing whitespace
        relative_path = relative_path.strip()
        
        print(f"📥 Upload request: {relative_path}")
        
        if file.filename == '':
            return jsonify({'status': 'error', 'error': 'Empty filename'}), 400
        
        # Construct full central path - use normpath to clean it up
        full_path = os.path.normpath(os.path.join(CENTRAL_FILE_ROOT, relative_path))
        
        print(f"   Full path: {full_path}")
        
        # Security: prevent path traversal attacks
        if not os.path.abspath(full_path).startswith(os.path.abspath(CENTRAL_FILE_ROOT)):
            return jsonify({'status': 'error', 'error': 'Invalid path'}), 400
        
        # Create directory structure if it doesn't exist
        dir_path = os.path.dirname(full_path)
        os.makedirs(dir_path, exist_ok=True)
        print(f"   Directory: {dir_path}")
        
        # Save the file - explicitly specify the path
        file.save(full_path)
        
        # Verify it was saved
        if not os.path.exists(full_path):
            raise Exception(f"File not found after save: {full_path}")
        
        file_size = os.path.getsize(full_path)
        print(f"   ✓ Saved: {file_size} bytes")
        
        # Log file sync to database
        try:
            conn = get_pg_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO sync_log
                (sync_timestamp, sync_direction, table_name, records_synced, status, error_message)
                VALUES (CURRENT_TIMESTAMP, 'ship_file', %s, 1, 'success', %s)
            """, (
                relative_path,
                f"Size: {file_size} bytes"
            ))
            conn.commit()
            conn.close()
        except Exception as log_error:
            print(f"⚠️ Could not log file upload: {log_error}")
        
        return jsonify({
            'status': 'success',
            'path': full_path,
            'relative_path': relative_path,
            'size_bytes': file_size,
            'timestamp': datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        print(f"✗ File upload failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route("/check_file", methods=["POST"])
def check_file():
    """
    Check if a file already exists on central.
    Expects JSON: {"relative_path": "..."}
    Returns: {"exists": true/false, "size": bytes or null}
    """
    try:
        data = request.get_json()
        if not data or 'relative_path' not in data:
            return jsonify({'error': 'No relative_path provided'}), 400
        
        relative_path = data['relative_path']
        full_path = os.path.join(CENTRAL_FILE_ROOT, relative_path)
        
        # Security check
        if not os.path.abspath(full_path).startswith(os.path.abspath(CENTRAL_FILE_ROOT)):
            return jsonify({'error': 'Invalid path'}), 400
        
        exists = os.path.exists(full_path)
        size = os.path.getsize(full_path) if exists else None
        
        return jsonify({
            'exists': exists,
            'size_bytes': size,
            'relative_path': relative_path
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    print("\n" + "="*70)
    print("🚢 CENTRAL SYNC RECEIVER STARTING")
    print("="*70)
    print(f"Listening on: http://0.0.0.0:5910")
    print(f"Health check: http://10.129.222.192:5910/health")
    print(f"Metadata sync: http://10.129.222.192:5910/sync")
    print(f"File upload: http://10.129.222.192:5910/upload_file")
    print(f"File check: http://10.129.222.192:5910/check_file")
    print(f"File root: {CENTRAL_FILE_ROOT}")
    print("="*70 + "\n")

    app.run(host="0.0.0.0", port=5910, debug=True)
