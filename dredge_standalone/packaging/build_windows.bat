@echo off
setlocal
title Build Dragognosificator
rem Builds a single-file Dragognosificator.exe in dist\
rem Run this from any directory; it finds the repo root from its own location.

set "HERE=%~dp0"
set "ROOT=%HERE%..\.."
cd /d "%ROOT%"

echo ========================================
echo  Building Dragognosificator.exe
echo ========================================
echo.
echo Repo root: %ROOT%
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found on PATH. Install Python 3.10+ from python.org
    pause
    exit /b 1
)

python -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 goto :fail
)

echo Installing app requirements into current Python...
python -m pip install -r dredge_standalone\requirements.txt
if errorlevel 1 goto :fail

echo.
echo Running PyInstaller (this may take a few minutes)...
python -m PyInstaller --clean --noconfirm dredge_standalone\packaging\dragognosificator.spec
if errorlevel 1 goto :fail

echo.
echo ========================================
echo  Build complete!
echo ========================================
echo.
echo   %ROOT%\dist\Dragognosificator.exe
echo.
echo Copy that file anywhere and double-click to run.
echo No Python installation needed on the target machine.
echo.
pause
exit /b 0

:fail
echo.
echo Build failed - see messages above.
pause
exit /b 1
