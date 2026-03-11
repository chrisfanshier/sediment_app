#!/bin/bash
echo "========================================"
echo " Starting Winch Plotter (port 8505)"
echo "========================================"
echo ""
echo "Make sure database is running!"
echo "(If not, run ./startdatabase.sh first)"
echo ""
cd ~/ShipsideDB/app/scripts
source venv/bin/activate
python launcher.py 8505
echo "Application closed."
