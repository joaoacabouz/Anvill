@echo off
setlocal
cd /d "%~dp0"

:: 1. Prefer local virtual environment pythonw (pure GUI, no console window)
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "src\app_gui.py" %*
    exit /b 0
)

:: 2. Fallback to venv python.exe in background
if exist ".venv\Scripts\python.exe" (
    start "" /b ".venv\Scripts\python.exe" "src\app_gui.py" %*
    exit /b 0
)

:: 3. Fallback to system pythonw
where pythonw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw "src\app_gui.py" %*
    exit /b 0
)

:: 4. Fallback to system python
where python >nul 2>&1
if %errorlevel% equ 0 (
    start "" /b python "src\app_gui.py" %*
    exit /b 0
)

echo [ERROR] Python not found. Please install Python 3.10+ and requirements.
pause
exit /b 1

