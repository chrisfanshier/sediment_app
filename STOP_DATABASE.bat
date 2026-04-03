@echo off
title Stop Shipside Database
echo ========================================
echo  Stopping Shipside Database
echo ========================================
echo.

cd /d C:\ShipsideDB\postgresql\bin

pg_ctl.exe -D ..\data stop

echo.
echo Database stopped safely.
echo.
pause