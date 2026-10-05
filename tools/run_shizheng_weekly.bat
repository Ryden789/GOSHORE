@echo off
REM ============================================================
REM GOSHORE 时政流水线 · 每周自动更新
REM 双击即可手动跑一次；也可注册为 Windows 计划任务（每周一 08:00）：
REM   schtasks /Create /TN "GOSHORE-Shizheng-Weekly" ^
REM            /TR "D:\GOSHORE\tools\run_shizheng_weekly.bat" ^
REM            /SC WEEKLY /D MON /ST 08:00 /F
REM 删除计划任务：
REM   schtasks /Delete /TN "GOSHORE-Shizheng-Weekly" /F
REM ============================================================
setlocal
cd /d "%~dp0.."

set PY=python
if exist "%USERPROFILE%\.workbuddy-ai\binaries\python\envs\default\Scripts\python.exe" (
  set PY=%USERPROFILE%\.workbuddy-ai\binaries\python\envs\default\Scripts\python.exe
)

echo [%date% %time%] 开始更新时政...
"%PY%" scripts\update_shizheng.py --pages 12 --periods 6
set CODE=%ERRORLEVEL%
echo [%date% %time%] 结束，退出码=%CODE%

if "%CODE%"=="2" echo 网络不可用，本次跳过（未做任何修改）。
if "%CODE%"=="3" echo 未配置 DeepSeek Key，已跳过 AI 出题。

REM 计划任务场景下不需要暂停；手动双击时可取消下一行注释以查看输出
REM pause
endlocal
