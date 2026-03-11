@echo off
title Shipside Database - File Sync
echo ========================================
echo  Starting File Sync (port 8506)
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
echo Starting File Sync...
echo Browser tab will open automatically...
echo.
python launcher.py 8506
echo.
echo Application closed.
pause
