@echo off
chcp 65001 >nul
cd /d %~dp0

echo ================================================
echo   GOSHORE 上岸工作台 启动中...
echo ================================================

rem Port comes from data/settings.json (run.py reads it). Hard-coding 8765 would
rem make this script check 8765 and open a blank page after the user changes it.
set PORT=8765
for /f "usebackq delims=" %%p in (`python -c "from app.config import load_settings; print(int(load_settings()['port']))" 2^>nul`) do set PORT=%%p

rem Check whether the port is already in use. Never kill anything by default:
rem only warn, and let the user decide. Match ":PORT" at end of line exactly,
rem so that :18765 / :28765 are not mistaken for the same port.
set OCCUPIED=
for /f "tokens=5" %%a in ('netstat -ano -p tcp ^| findstr "LISTENING" ^| findstr /R /C:":%PORT% $"') do (
    set OCCUPIED=%%a
    goto :found
)
rem Fallback when the exact match fails (some netstat output has no trailing space)
for /f "tokens=5" %%a in ('netstat -ano -p tcp ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    set OCCUPIED=%%a
    goto :found
)
goto :launch

:found
set PNAME=未知进程
for /f "tokens=1 delims=," %%n in ('tasklist /FI "PID eq %OCCUPIED%" /NH /FO CSV 2^>nul') do set PNAME=%%~n
echo.
echo [提示] 端口 %PORT% 已被占用：PID %OCCUPIED%（%PNAME%）
echo.
echo   1 = 结束该进程并继续启动（请先确认它不是别的重要程序）
echo   2 = 直接打开已运行的服务（若是本应用的上一个实例）
echo   3 = 取消启动，我自己处理
echo.
choice /C 123 /N /M "请选择 [1/2/3]: "
if errorlevel 3 goto :cancel
if errorlevel 2 goto :openonly
if errorlevel 1 goto :kill

:kill
echo 正在结束 PID %OCCUPIED% ...
taskkill /F /PID %OCCUPIED%
if errorlevel 1 (
    echo 结束失败：可能权限不足。请以管理员身份重试，或手动处理该端口。
    pause
    exit /b 1
)
timeout /t 1 /nobreak >nul
goto :launch

:openonly
start "" "http://127.0.0.1:%PORT%"
echo 已打开 http://127.0.0.1:%PORT% ；若页面打不开，说明占用者不是本应用。
pause
exit /b 0

:cancel
echo 已取消启动。请先处理占用 %PORT% 的进程，再运行本脚本。
pause
exit /b 0

:launch
rem Wait in the background until the port is connectable (service really ready),
rem then open the browser, instead of a fixed delay that may land on a blank page.
start "" powershell -WindowStyle Hidden -NoProfile -Command "for($i=0;$i -lt 120;$i++){try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',%PORT%);$c.Close();Start-Sleep -Milliseconds 300;Start-Process 'http://127.0.0.1:%PORT%';exit}catch{Start-Sleep -Milliseconds 500}}"

rem Start the service in the foreground; closing this window stops it.
python run.py

pause
