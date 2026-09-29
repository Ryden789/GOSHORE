@echo off
chcp 65001 >nul
title GOSHORE Protocol Register

rem 注册 goshor:// 自定义协议（仅当前用户，无需管理员）
rem 作用：PPT / 浏览器中的 goshor://open 链接将调用 open_app.bat 拉起模拟器中的 APP

reg add "HKCU\Software\Classes\goshor" /ve /d "URL:GOSHORE App Launcher" /f >nul
reg add "HKCU\Software\Classes\goshor" /v "URL Protocol" /d "" /f >nul
reg add "HKCU\Software\Classes\goshor\shell\open\command" /ve /d "\"%~dp0open_app.bat\"" /f >nul

echo [OK] goshor:// 协议已注册（当前用户级）
echo      关联程序: %~dp0open_app.bat
echo.
echo 如需取消注册，运行:
echo   reg delete "HKCU\Software\Classes\goshor" /f
pause
