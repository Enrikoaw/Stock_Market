@echo off
title SmartFlow IDX - 24/7 Watchdog Server
cd /d "%~dp0"
echo ============================================================
echo   SMARTFLOW IDX - 24/7 NON-STOP SERVER (AUTO-RESTART)
echo   Akses Lokal : http://127.0.0.1:8000
echo   Akses LAN/HP: http://%COMPUTERNAME%:8000
echo ============================================================

:loop
echo [%date% %time%] Menjalankan SmartFlow IDX Backend Server...
python backend/main.py
echo [%date% %time%] Server berhenti. Melakukan restart otomatis dalam 5 detik...
timeout /t 5 /nobreak >nul
goto loop
