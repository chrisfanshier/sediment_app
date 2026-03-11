@echo off
title Shipside Database - Winch Plotter
echo ========================================
echo  Starting Winch Plotter (port 8505)
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
echo Starting Winch Plotter...
echo Browser tab will open automatically...
echo.
python launcher.py 8505
echo.
echo Application closed.
pause
