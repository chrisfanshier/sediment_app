@echo off
title Dredge App
rem Double-clickable launcher. Lives inside the dredge_standalone folder;
rem runs from the parent folder so "python -m dredge_standalone" resolves.
cd /d "%~dp0.."

if not exist "venv\Scripts\pythonw.exe" (
    echo ========================================
    echo  First run: setting up Python environment
    echo ========================================
    python -m venv venv
    if errorlevel 1 goto :error
    call venv\Scripts\activate.bat
    echo Installing requirements (one-time, may take a few minutes)...
    pip install -r dredge_standalone\requirements.txt
    if errorlevel 1 goto :error
)

start "" "venv\Scripts\pythonw.exe" -m dredge_standalone
exit /b 0

:error
echo.
echo Setup failed. Make sure Python 3.10+ is installed and on PATH
echo (https://www.python.org/downloads/ - check "Add python.exe to PATH").
pause
