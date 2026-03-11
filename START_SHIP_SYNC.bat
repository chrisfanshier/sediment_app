@echo off
title Shipside Database - Ship Sync
echo ========================================
echo  Starting Ship Sync (port 8504)
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
echo Starting Ship Sync...
echo Browser tab will open automatically...
echo.
python launcher.py 8504
echo.
echo Application closed.
pause
