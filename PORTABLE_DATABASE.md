# Portable Database System for Field Operations

This documentation describes how to use the portable SQLite database system for offline sediment coring data collection at sea.

## Overview

The sediment coring application now supports two database modes:

1. **Connected Mode (PostgreSQL)**: The default mode when connected to the network. Uses the central PostgreSQL database.

2. **Portable Mode (SQLite)**: For offline field operations at sea. Uses a lightweight SQLite database that can be synced later.

## Quick Start

### Creating a Portable Database (Before Going to Sea)

1. Run the Streamlit app connected to the PostgreSQL server
2. Navigate to the "Portable Database Manager" page
3. Select the cruises you want to take to the field
4. Click "Create Portable Database"
5. Download the generated `.db` file
6. Copy to your field laptop

### Working Offline at Sea

Set environment variables before running the app:

```bash
# Linux/Mac
export SEDIMENT_DB_MODE=sqlite
export SQLITE_DATABASE_PATH=/path/to/your/portable_sediment.db

# Windows
set SEDIMENT_DB_MODE=sqlite
set SQLITE_DATABASE_PATH=C:\path\to\your\portable_sediment.db
```

Then run the Streamlit apps as normal. All data will be saved to the SQLite database.

### Syncing Back to Server (After Returning)

1. Connect to the network with PostgreSQL access
2. Run the Streamlit app (will automatically use PostgreSQL)
3. Navigate to "Portable Database Manager" > "Sync to Server"
4. Upload or select your portable database file
5. Choose conflict resolution strategy
6. Click "Sync to Server"

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SEDIMENT_DB_MODE` | Force database mode: `postgres`, `sqlite`, or `auto` | `auto` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://postgres:***@localhost/sediment_cores` |
| `SQLITE_DATABASE_PATH` | Path to SQLite database file | `portable_sediment.db` |

## Command Line Usage

### Create a portable database programmatically:

```python
from sync_manager import create_portable_database

# Export all cruises
results = create_portable_database(output_path="field_db.db")

# Export specific cruises
results = create_portable_database(
    cruise_ids=[1, 2, 3], 
    output_path="field_db.db"
)
print(f"Exported {results['exported_counts']}")
```

### Sync data back to server:

```python
from sync_manager import sync_portable_database, ConflictResolution

results = sync_portable_database(
    sqlite_path="field_db.db",
    conflict_resolution=ConflictResolution.LOCAL_WINS
)
print(f"Imported {results['imported_counts']}")
```

### Check sync status:

```python
from sync_manager import get_portable_status

status = get_portable_status("field_db.db")
print(f"Pending records: {status['total_pending']}")
```

## Database Schema

The SQLite database mirrors the PostgreSQL schema with additional sync tracking:

- All tables include a `sync_status` column (`pending`, `synced`, `conflict`)
- A `sync_log` table tracks sync operations
- Reference tables (vessels, core_types, wire) are read-only in portable mode

## Tables Included

**Reference Data (exported from server, read-only in field):**
- vessels
- core_types
- wire

**Operational Data (can be created/modified in field):**
- cruises
- cores
- sections
- mscl_files
- sensor_files
- winch_data

## Conflict Resolution

When syncing back to the server, conflicts can occur if the same record exists in both databases. Available strategies:

- **Local Wins**: Field data takes priority (recommended for new data)
- **Server Wins**: Server data takes priority (safe option)
- **Manual Review**: Flags conflicts for manual resolution

## Best Practices

1. **Before departure**: Create portable database with only the cruises you'll be working on
2. **Naming convention**: Use unique, descriptive core names to avoid conflicts
3. **Regular backups**: Keep multiple copies of the portable database file
4. **Sync promptly**: Sync data to the server as soon as you have connectivity
5. **Verify sync**: Check the sync results to ensure all data was transferred

## Troubleshooting

### "No cruises found in database"
- Make sure you're connected to PostgreSQL (not in portable mode)
- Check your DATABASE_URL environment variable

### "Failed to connect to PostgreSQL"
- Verify network connectivity
- Check that the PostgreSQL server is running
- Verify credentials in DATABASE_URL

### "Sync conflicts detected"
- Review the conflicts in the sync results
- Choose appropriate conflict resolution strategy
- Re-run sync if needed

## Architecture

```
┌─────────────────────┐     ┌─────────────────────┐
│   PostgreSQL        │     │    SQLite           │
│   (Central Server)  │     │    (Field Device)   │
│                     │     │                     │
│  - All data         │     │  - Selected cruises │
│  - Multi-user       │◄───►│  - Single user      │
│  - Full access      │     │  - Offline capable  │
│                     │     │  - Sync tracking    │
└─────────────────────┘     └─────────────────────┘
         ▲                           ▲
         │                           │
         └─────────┬─────────────────┘
                   │
           ┌───────┴───────┐
           │ Sync Manager  │
           │               │
           │ - Export      │
           │ - Import      │
           │ - Conflict    │
           │   Resolution  │
           └───────────────┘
```
