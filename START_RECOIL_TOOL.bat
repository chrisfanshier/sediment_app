@echo off
title Shipside Database - Recoil Fitting Tool
echo ========================================
echo  Starting Recoil Fitting Tool
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
echo Starting Recoil Fitting Tool...
echo.
python -m recoil_tool
echo.
echo Application closed.
pause
