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

:: 等待端口真正释放（最多约 10 秒）；若仍被占用则补杀一次，避免 python 启动时 bind 10048
powershell -NoProfile -Command "for($i=0;$i -lt 20;$i++){$c=@(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue);if($c.Count -eq 0){exit};foreach($p in $c){Stop-Process -Id $p.OwningProcess -Force -ErrorAction SilentlyContinue};Start-Sleep -Milliseconds 500}"

:: 后台等待：端口可连接（服务真正就绪）后再打开浏览器，避免固定延时导致的“无连接”页
start "" powershell -WindowStyle Hidden -NoProfile -Command "for($i=0;$i -lt 120;$i++){try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',8765);$c.Close();Start-Sleep -Milliseconds 300;Start-Process 'http://127.0.0.1:8765';exit}catch{Start-Sleep -Milliseconds 500}}"

:: 启动服务（前台运行，关闭本窗口即停止）
python run.py

pause
