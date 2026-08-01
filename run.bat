@echo off
rem GALA 运行（加载已构建的前端 dist；构建: cd frontend && npm run build）
cd /d %~dp0

if not exist venv\Scripts\python.exe (
  echo [GALA] 未找到 venv
  pause & exit /b 1
)
if not exist frontend\dist\index.html (
  echo [GALA] 未找到前端构建产物，请先执行: cd frontend ^&^& npm run build
  pause & exit /b 1
)

venv\Scripts\python -m backend.app
