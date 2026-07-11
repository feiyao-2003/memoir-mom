@echo off
echo ============================================
echo   人生回忆录 - 公网模式
echo ============================================
echo.
echo 正在启动服务...

REM 启动 FastAPI 后端
start "人生回忆录-后端" cmd /c "cd /d %~dp0backend && python main.py"

REM 等待后端启动
timeout /t 3 /nobreak >nul

echo 后端已启动，正在生成公网链接...
echo.
echo 请稍候，链接生成后会显示在下方...
echo 按 Ctrl+C 可以停止所有服务
echo ============================================

REM 使用 localtunnel 生成公网链接
npx -y localtunnel --port 8000 --subdomain renshenghuiyilu

pause
