@echo off
title Shipside Database - Main App
echo ========================================
echo  Starting Main App (port 8501)
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
echo Starting Main App...
echo Browser tab will open automatically...
echo.
python launcher.py 8501
echo.
echo Application closed.
pause
