@echo off
title Shipside Database - File Data Entry
echo ========================================
echo  Starting File Data Entry (port 8503)
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
echo Starting File Data Entry...
echo Browser tab will open automatically...
echo.
python launcher.py 8503
echo.
echo Application closed.
pause
