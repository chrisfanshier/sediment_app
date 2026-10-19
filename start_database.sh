#!/bin/bash

# Title equivalent for terminal
echo -e "\033]0;Shipside PostgreSQL Server\007"
echo "========================================"
echo " Starting Shipside Database"
echo "========================================"
echo

# Update this path to where your PG binaries are located on the Mac
# For example: /usr/local/opt/postgresql@15/bin
PG_BIN_DIR="/usr/local/bin"
PG_DATA_DIR="/Users/Shared/ShipsideDB/data"
PG_LOG_DIR="/Users/Shared/ShipsideDB/logs"

cd "$PG_BIN_DIR" || { echo "Error: Could not find PG bin directory"; exit 1; }

# Create logs directory if needed
if [ ! -d "$PG_LOG_DIR" ]; then
    mkdir -p "$PG_LOG_DIR"
fi

# Start PostgreSQL
echo "Starting PostgreSQL on port 5432..."
./pg_ctl -D "$PG_DATA_DIR" -l "$PG_LOG_DIR/postgres.log" start

if [ $? -eq 0 ]; then
    echo
    echo "======================================"
    echo " Database started successfully!"
    echo "======================================"
    echo
    echo "Logs: $PG_LOG_DIR/postgres.log"
    echo
    echo "Keep this window open or use stop_database.sh to close."
else
    echo
    echo "ERROR: Database failed to start!"
    echo "Check logs: $PG_LOG_DIR/postgres.log"
fi

echo
read -p "Press [Enter] to continue..."
