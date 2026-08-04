@echo off
setlocal
set "ROOT_DIR=%~dp0"

if exist "%ROOT_DIR%.venv\Scripts\python.exe" (
    "%ROOT_DIR%.venv\Scripts\python.exe" "%ROOT_DIR%crear_playlist.py" %*
    exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    python "%ROOT_DIR%crear_playlist.py" %*
    exit /b %ERRORLEVEL%
)

echo Error: no se encontro Python. Ejecute primero install.ps1. 1>&2
exit /b 1
