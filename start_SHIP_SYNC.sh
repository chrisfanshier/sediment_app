#!/bin/bash
echo "========================================"
echo " Starting Ship Sync (port 8504)"
echo "========================================"
echo ""
echo "Make sure database is running!"
echo "(If not, run ./startdatabase.sh first)"
echo ""
cd ~/ShipsideDB/app/scripts
source venv/bin/activate
python launcher.py 8504
echo "Application closed."
