@echo off
setlocal
title Sensorius
set "HERE=%~dp0"
set "VENVPY=%HERE%venv\Scripts\python.exe"
set "VENVPYW=%HERE%venv\Scripts\pythonw.exe"

if exist "%VENVPY%" goto :havevenv

echo ========================================
echo  First run: setting up Python environment
echo ========================================
where python >nul 2>nul
if errorlevel 1 goto :trypy
python -m venv "%HERE%venv"
if errorlevel 1 goto :setupfail
goto :havevenv

:trypy
where py >nul 2>nul
if errorlevel 1 goto :nopython
py -3 -m venv "%HERE%venv"
if errorlevel 1 goto :setupfail

:havevenv
"%VENVPY%" -c "import PySide6, pyqtgraph, pandas, numpy, scipy" >nul 2>nul
if not errorlevel 1 goto :launch
echo Installing requirements (one-time, may take a few minutes)...
"%VENVPY%" -m pip install --upgrade pip
"%VENVPY%" -m pip install -r "%HERE%requirements.txt"
if errorlevel 1 goto :setupfail

:launch
cd /d "%HERE%.."
"%VENVPY%" -c "import sensor_standalone.gui.main_window"
if errorlevel 1 goto :appfail

start "" "%VENVPYW%" -m sensor_standalone
exit /b 0

:nopython
echo Python was not found. Install Python 3.10+ from https://www.python.org/downloads/
pause
exit /b 1

:setupfail
echo Environment setup failed.
pause
exit /b 1

:appfail
echo The app failed to start - see error above.
pause
exit /b 1
