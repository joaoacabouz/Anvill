@echo off
setlocal
cd /d "%~dp0"

echo ======================================================================
echo   ANVILL - Build Standalone Executable (Nuitka + Clang)
echo ======================================================================

set PYTHON_CMD=python
if exist ".venv\Scripts\python.exe" (
    set PYTHON_CMD=".venv\Scripts\python.exe"
)

%PYTHON_CMD% build_exe.py %*
if %errorlevel% neq 0 (
    echo.
    echo Build failed with error code %errorlevel%.
    pause
    exit /b %errorlevel%
)

echo.
echo Build complete.
pause

