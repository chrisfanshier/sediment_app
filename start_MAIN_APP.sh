#!/bin/bash
echo "========================================"
echo " Starting Main App (port 8501)"
echo "========================================"
echo ""
echo "Make sure database is running!"
echo "(If not, run ./startdatabase.sh first)"
echo ""
cd ~/ShipsideDB/app/scripts
source venv/bin/activate
python launcher.py 8501
echo "Application closed."
