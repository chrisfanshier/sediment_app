@echo off
title Shipside Database - Sensorius
echo ========================================
echo  Starting Sensorius
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
echo Starting Sensorius...
echo.
python -m sensor_tool
echo.
echo Application closed.
pause
