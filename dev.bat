@echo off
rem GALA 开发模式：vite dev server + pywebview（需先安装依赖）
cd /d %~dp0

if not exist venv\Scripts\python.exe (
  echo [GALA] 未找到 venv，请先执行:
  echo   python -m venv venv
  echo   venv\Scripts\pip install -r requirements.txt
  pause & exit /b 1
)
if not exist frontend\node_modules (
  echo [GALA] 未安装前端依赖，请先执行:
  echo   cd frontend ^&^& npm install
  pause & exit /b 1
)

start "GALA vite" cmd /k "cd /d %~dp0frontend && npm run dev"
timeout /t 2 >nul
venv\Scripts\python -m backend.app --dev
