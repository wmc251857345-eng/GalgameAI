@echo off

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [GALA] venv not found.
    pause
    exit /b 1
)

if not exist "frontend\dist\index.html" (
    echo [GALA] frontend not built.
    echo Run:
    echo cd frontend
    echo npm run build
    pause
    exit /b 1
)

venv\Scripts\python.exe -m backend.app