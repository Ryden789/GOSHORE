@echo off
chcp 65001 >nul
cd /d %~dp0

echo ================================================
echo   GOSHORE 上岸工作台 启动中...
echo ================================================

:: 释放被占用的 8765 端口
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

:: 延迟 2 秒自动打开浏览器
start "" powershell -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8765'"

:: 启动服务（前台运行，关闭本窗口即停止）
python run.py

pause
