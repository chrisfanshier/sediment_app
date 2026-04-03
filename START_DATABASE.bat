@echo off
title Shipside PostgreSQL Server
echo ========================================
echo  Starting Shipside Database
echo ========================================
echo.

cd /d C:\ShipsideDB\postgresql\bin

REM Create logs directory if needed
if not exist "..\logs" mkdir ..\logs

REM Start PostgreSQL
echo Starting PostgreSQL on port 5432...
pg_ctl.exe -D ..\data -l ..\logs\postgres.log start

if %errorlevel% equ 0 (
    echo.
    echo ======================================
    echo  Database started successfully!
    echo ======================================
    echo.
    echo Logs: C:\ShipsideDB\postgresql\logs\
    echo.
    echo Keep this window open while using the database.
) else (
    echo.
    echo ERROR: Database failed to start!
    echo Check logs: C:\ShipsideDB\postgresql\logs\postgres.log
)

echo.
pause