@echo off
chcp 65001 >nul
title Xuexit Login Helper
cd /d "%~dp0"
echo ============================================
echo   Xuexit Login Helper
echo   Close this window to stop the tunnel.
echo ============================================
echo.
set "PYEXE="
if exist "%~dp0python\python.exe" set "PYEXE=%~dp0python\python.exe"
where python >nul 2>nul && set "PYEXE=python"
if not defined PYEXE (
  echo [ERROR] Python not found. Install 3.8+ from python.org
  pause
  exit /b 1
)
"%PYEXE%" "%~dp0login_proxy.py" --config "%~dp0helper.json"
echo.
echo Helper stopped. Tunnel closed.
pause
