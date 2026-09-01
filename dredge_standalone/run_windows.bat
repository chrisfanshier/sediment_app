@echo off
setlocal
title Dragognosificator
rem Double-clickable launcher. Creates a dedicated Python environment inside
rem this folder (dredge_standalone\venv) on first run — it deliberately does
rem NOT reuse any venv that may exist elsewhere, so it can't be broken by
rem other apps' environments.

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
rem Install requirements if any are missing (first run, or after updates).
"%VENVPY%" -c "import PySide6, pyqtgraph, pandas, numpy, pyproj" >nul 2>nul
if not errorlevel 1 goto :launch
echo Installing requirements (one-time, may take a few minutes)...
"%VENVPY%" -m pip install --upgrade pip
"%VENVPY%" -m pip install -r "%HERE%requirements.txt"
if errorlevel 1 goto :setupfail

:launch
rem Run from the parent folder so "python -m dredge_standalone" resolves.
cd /d "%HERE%.."
rem Verify the app imports cleanly; if not, show the real error and stop.
"%VENVPY%" -c "import dredge_standalone.gui.main_window"
if errorlevel 1 goto :appfail

start "" "%VENVPYW%" -m dredge_standalone
exit /b 0

:nopython
echo.
echo Python was not found on this computer.
echo Install Python 3.10 or newer from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during installation, then run this again.
pause
exit /b 1

:setupfail
echo.
echo Environment setup failed - see the messages above.
pause
exit /b 1

:appfail
echo.
echo The app failed to start - the error is shown above.
echo If it mentions a missing module, delete the "venv" folder inside
echo dredge_standalone and run this launcher again to reinstall.
pause
exit /b 1
