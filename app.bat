@echo off
setlocal
cd /d "%~dp0"

:: 1. Prefer local virtual environment if present
if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" "src\app_gui.py" %*
    exit /b 0
)

:: 2. Fallback to system python
where python >nul 2>&1
if %errorlevel% equ 0 (
    start "" python "src\app_gui.py" %*
    exit /b 0
)

echo [ERROR] Python not found. Please install Python 3.10+ and requirements.
pause
exit /b 1

