"""
Copy data files from network server to local machine via SSH/SFTP
Run this ON THE SHIP after restoring database and running prepare_db.py

This script will:
1. Query the database for all file paths that belong to kept cruises
2. Copy files from Linux server to local Windows machine via SSH/SFTP
3. Maintain identical directory structure
"""

import os
import stat
from pathlib import Path
from db_util import get_connection
from sqlalchemy import text
from config import ROOT_DIRECTORY
import paramiko

# SSH Connection settings
SSH_HOST = os.getenv("SSH_HOST", "marssam-data.ceoas.oregonstate.edu")
SSH_PORT = int(os.getenv("SSH_PORT", "22"))
SSH_USER = os.getenv("SSH_USER", "fanshiec")
SSH_KEY_PATH = os.getenv("SSH_KEY_PATH", None)  # Optional: path to SSH private key

# Network server root path (on Linux server)
NETWORK_ROOT = "/home/server/project/marssam/marssam_data_files"

# Local machine root from config
LOCAL_ROOT = ROOT_DIRECTORY

def get_files_to_copy():
    """Query database for all file paths that need to be copied"""
    
    files_to_copy = []
    
    with get_connection() as conn:
        # Get MSCL files
        result = conn.execute(text("""
            SELECT DISTINCT m.file_path, m.file_name
            FROM mscl_files m
            JOIN cores c ON m.core_id = c.core_id
            WHERE m.file_path IS NOT NULL
            ORDER BY m.file_path
        """))
        for row in result:
            files_to_copy.append({
                'type': 'MSCL',
                'relative_path': os.path.join(row.file_path, row.file_name) if row.file_path else row.file_name,
                'filename': row.file_name
            })
        
        # Get sensor files
        result = conn.execute(text("""
            SELECT DISTINCT s.file_path, s.file_name
            FROM sensor_files s
            JOIN cores c ON s.core_id = c.core_id
            WHERE s.file_path IS NOT NULL
            ORDER BY s.file_path
        """))
        for row in result:
            files_to_copy.append({
                'type': 'Sensor',
                'relative_path': os.path.join(row.file_path, row.file_name) if row.file_path else row.file_name,
                'filename': row.file_name
            })
        
        # Get winch data files
        result = conn.execute(text("""
            SELECT DISTINCT w.file_path, w.file_name
            FROM winch_data w
            JOIN cruises cr ON w.cruise_id = cr.cruise_id
            WHERE w.file_path IS NOT NULL
            ORDER BY w.file_path
        """))
        for row in result:
            files_to_copy.append({
                'type': 'Winch',
                'relative_path': os.path.join(row.file_path, row.file_name) if row.file_path else row.file_name,
                'filename': row.file_name
            })
    
    return files_to_copy


def copy_files_sftp(sftp, files_to_copy, dry_run=False):
    """Copy files from server via SFTP to local storage"""
    
    stats = {
        'total': len(files_to_copy),
        'copied': 0,
        'skipped': 0,
        'missing': 0,
        'errors': 0
    }
    
    for file_info in files_to_copy:
        relative_path = file_info['relative_path']
        filename = file_info['filename']
        file_type = file_info['type']
        
        # Construct full paths
        # Use forward slashes for Linux server path
        source_path = f"{NETWORK_ROOT}/{relative_path}".replace('\\', '/')
        # Use OS-specific separators for local Windows path
        dest_path = os.path.join(LOCAL_ROOT, relative_path)
        
        # Check if source exists on server
        try:
            sftp.stat(source_path)
        except FileNotFoundError:
            print(f"  ⚠ Missing on server: {relative_path}")
            stats['missing'] += 1
            continue
        except Exception as e:
            print(f"  ⚠ Error checking {relative_path}: {e}")
            stats['errors'] += 1
            continue
        
        # Check if destination already exists locally
        if os.path.exists(dest_path):
            if dry_run and stats['skipped'] < 5:  # Show first 5 examples
                print(f"  Already exists: {dest_path}")
            stats['skipped'] += 1
            continue
        
        if dry_run:
            print(f"  Would copy: {relative_path}")
            stats['copied'] += 1
            continue
        
        try:
            # Create destination directory if it doesn't exist
            dest_dir = os.path.dirname(dest_path)
            os.makedirs(dest_dir, exist_ok=True)
            
            # Copy the file via SFTP
            sftp.get(source_path, dest_path)
            stats['copied'] += 1
            
            if stats['copied'] % 10 == 0:
                print(f"  Copied {stats['copied']}/{stats['total']} files...")
                
        except Exception as e:
            print(f"  ✗ Error copying {relative_path}: {e}")
            stats['errors'] += 1
            if not dry_run:
                # Log detailed error info
                import traceback
                print(f"     Details: {traceback.format_exc()}")
    
    return stats


def connect_ssh():
    """Establish SSH connection to server"""
    
    print(f"\nConnecting to {SSH_USER}@{SSH_HOST}:{SSH_PORT}...")
    
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        if SSH_KEY_PATH and os.path.exists(SSH_KEY_PATH):
            # Use SSH key authentication
            print(f"  Using SSH key: {SSH_KEY_PATH}")
            ssh.connect(
                hostname=SSH_HOST,
                port=SSH_PORT,
                username=SSH_USER,
                key_filename=SSH_KEY_PATH
            )
        else:
            # Use password authentication
            import getpass
            password = getpass.getpass(f"  Password for {SSH_USER}@{SSH_HOST}: ")
            ssh.connect(
                hostname=SSH_HOST,
                port=SSH_PORT,
                username=SSH_USER,
                password=password
            )
        
        print("  ✓ Connected")
        return ssh
        
    except Exception as e:
        print(f"  ✗ Connection failed: {e}")
        return None


def main():
    print("\n" + "=" * 70)
    print("COPY DATA FILES VIA SSH/SFTP")
    print("=" * 70)
    
    print(f"\nServer:      {SSH_USER}@{SSH_HOST}")
    print(f"Remote root: {NETWORK_ROOT}")
    print(f"Local root:  {LOCAL_ROOT}")
    
    # Verify/create local path
    os.makedirs(LOCAL_ROOT, exist_ok=True)
    
    print("\n1. Querying database for files to copy...")
    files_to_copy = get_files_to_copy()
    
    if not files_to_copy:
        print("  No files found in database.")
        return
    
    print(f"  Found {len(files_to_copy)} files to copy")
    
    # Count by type
    type_counts = {}
    for f in files_to_copy:
        type_counts[f['type']] = type_counts.get(f['type'], 0) + 1
    
    for file_type, count in type_counts.items():
        print(f"    - {file_type}: {count} files")
    
    # Connect to server
    print("\n2. Connecting to server...")
    ssh = connect_ssh()
    if not ssh:
        return
    
    try:
        sftp = ssh.open_sftp()
        
        print("\n3. Dry run to check what will be copied...")
        stats = copy_files_sftp(sftp, files_to_copy, dry_run=True)
        
        print(f"\n  Summary:")
        print(f"    Total files:       {stats['total']}")
        print(f"    Would copy:        {stats['copied']}")
        print(f"    Already exist:     {stats['skipped']}")
        print(f"    Missing on server: {stats['missing']}")
        
        if stats['missing'] > 0:
            print(f"\n  ⚠ Warning: {stats['missing']} files are in the database but not found on server")
        
        print("\nProceed with copying files? (yes/no): ", end="")
        confirm = input().strip().lower()
        
        if confirm != 'yes':
            print("\nCopy cancelled.")
            return
        
        print("\n4. Copying files via SFTP...")
        stats = copy_files_sftp(sftp, files_to_copy, dry_run=False)
        
        print("\n" + "=" * 70)
        print("COPY COMPLETE")
        print("=" * 70)
        print(f"\n  Files copied:      {stats['copied']}")
        print(f"  Already existed:   {stats['skipped']}")
        print(f"  Missing:           {stats['missing']}")
        print(f"  Errors:            {stats['errors']}")
        
        if stats['errors'] > 0:
            print(f"\n  ⚠ {stats['errors']} files had errors during copy")
        
        print("\n")
        
    finally:
        sftp.close()
        ssh.close()
        print("Connection closed.")


if __name__ == "__main__":
    main()
