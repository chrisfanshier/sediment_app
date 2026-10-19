#!/bin/bash

echo -e "\033]0;Stop Shipside Database\007"
echo "========================================"
echo " Stopping Shipside Database"
echo "========================================"
echo

# Update these paths to match your Mac setup
PG_BIN_DIR="/usr/local/bin"
PG_DATA_DIR="/Users/Shared/ShipsideDB/data"

cd "$PG_BIN_DIR" || { echo "Error: Bin directory not found"; exit 1; }

# Stop the database
./pg_ctl -D "$PG_DATA_DIR" stop

echo
echo "Database stopped safely."
echo
read -p "Press [Enter] to continue..."
