@echo off
chcp 65001 >nul
cd /d %~dp0

set PORT=8765

echo ================================================
echo   GOSHORE 上岸工作台 . 桌面模式
echo ================================================
echo   用原生窗口显示，不打开浏览器
echo   服务仍监听 0.0.0.0，手机端 /m/ 照旧可用
echo.

rem 端口占用只提示、不结束任何进程（与 start.bat 的安全策略一致）
netstat -ano | findstr ":%PORT%" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 echo [提示] 端口 %PORT% 已被占用：若是本应用的另一个窗口会自动复用；若是其它程序请先处理，或用 --port 换端口。

python desktop.py %*
if errorlevel 1 echo [x] 启动失败。若提示缺少 pywebview，先执行：pip install -r requirements-desktop.txt
if errorlevel 1 pause
