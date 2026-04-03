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
echo Starting applications...
echo - View App (port 8501)
echo - Coring Data Entry (port 8502)
echo - File Data Entry (port 8503)
echo - Ship Sync (port 8504)
echo - Winch Plotter (port 8505)
echo - File Sync (port 8506)
echo.
echo Browser tabs will open automatically...
echo.

python launcher.py

echo.
echo Applications closed.
pause