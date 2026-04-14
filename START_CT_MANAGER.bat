@echo off
title Shipside Database - CT Manager
echo ========================================
echo  Starting CT Manager (port 8507)
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
echo Starting CT Manager...
echo Browser tab will open automatically...
echo.
python launcher.py 8507
echo.
echo Application closed.
