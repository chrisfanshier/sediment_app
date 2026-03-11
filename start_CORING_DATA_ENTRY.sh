#!/bin/bash
echo "========================================"
echo " Starting Coring Data Entry (port 8502)"
echo "========================================"
echo ""
echo "Make sure database is running!"
echo "(If not, run ./startdatabase.sh first)"
echo ""
cd ~/ShipsideDB/app/scripts
source venv/bin/activate
python launcher.py 8502
echo "Application closed."
