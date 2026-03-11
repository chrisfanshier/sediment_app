#!/bin/bash
echo "========================================"
echo " Starting All Shipside Database Apps"
echo "========================================"
echo ""
echo "Make sure database is running!"
echo "(If not, run ./startdatabase.sh first)"
echo ""
cd ~/ShipsideDB/app/scripts
source venv/bin/activate
python launcher.py
echo "Applications closed."
