@echo off
title Shipside Database - Applications
echo ========================================
echo  Starting Shipside Database Apps
echo ========================================
echo.
echo Make sure database is running!
echo (If not, run START_DATABASE.bat first)
echo.
pause
cd /d C:\ShipsideDB\app\scripts
echo Activating Python environment...
call venv\Scripts\activate.bat
echo.
echo Starting all applications...
echo.
echo Browser tabs will open automatically...
echo.
python launcher.py
echo.
echo Applications closed.
pause
