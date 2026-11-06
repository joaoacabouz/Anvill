@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

set PY=python
if exist "%~dp0.venv\Scripts\python.exe" set PY="%~dp0.venv\Scripts\python.exe"

REM Pure-Python entrypoint (logic is 100% in Python)
%PY% setup_sdk.py -y %*

if errorlevel 1 (
    echo.
    echo Setup failed. Press any key to exit...
    pause >nul
) else (
    echo.
    echo Setup completed successfully!
    pause >nul
)
