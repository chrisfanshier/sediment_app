@echo off
title Shipside Database - Dredge App
echo ========================================
echo  Starting Dredge App
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
echo Starting Dredge App...
echo.
python -m dredge_app
echo.
echo Application closed.
pause
