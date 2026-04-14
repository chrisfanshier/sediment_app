@echo off
title CorElator
echo ========================================
echo  Starting CorElator
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
echo Starting CorElator...
echo.
python ct_correlator.py
echo.
echo Application closed.
