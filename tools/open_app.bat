@echo off
setlocal
chcp 65001 >nul
title GOSHORE APP Launcher

rem 规避系统 Temp 目录 adb.log 权限问题
set "TEMP=D:\GOSHORE\.tmp"
set "TMP=D:\GOSHORE\.tmp"
if not exist "%TEMP%" mkdir "%TEMP%" >nul 2>&1

rem ===== 1. 定位 adb =====
set "ADB=D:\GOSHORE\.android-sdk\platform-tools\adb.exe"
if not exist "%ADB%" set "ADB=D:\platform-tools-latest-windows\platform-tools\adb.exe"
if not exist "%ADB%" (
    for /f "delims=" %%i in ('where adb 2^>nul') do set "ADB=%%i"
)
if not exist "%ADB%" (
    echo [X] 未找到 adb.exe，请安装 Android platform-tools 后重试
    pause
    exit /b 1
)

"%ADB%" start-server >nul 2>&1

rem ===== 2. 查找已连接设备 =====
set "SERIAL="
for /f "skip=1 tokens=1,2" %%a in ('"%ADB%" devices 2^>nul') do (
    if "%%b"=="device" if not defined SERIAL set "SERIAL=%%a"
)

rem ===== 3. 未发现设备则尝试常见模拟器端口 =====
if not defined SERIAL (
    for %%p in (5555 7555 16384 62001 21503) do (
        if not defined SERIAL (
            "%ADB%" connect 127.0.0.1:%%p >nul 2>&1
            for /f "skip=1 tokens=1,2" %%a in ('"%ADB%" devices 2^>nul') do (
                if "%%b"=="device" if not defined SERIAL set "SERIAL=%%a"
            )
        )
    )
)

if not defined SERIAL (
    echo [X] 未检测到模拟器或设备，请先启动安卓模拟器
    pause
    exit /b 1
)

echo [OK] 已连接设备: %SERIAL%

rem ===== 4. 检查 APP 是否已安装，未安装则自动安装 APK =====
"%ADB%" -s %SERIAL% shell pm list packages com.goshor.app 2>nul | findstr /i "goshor" >nul
if errorlevel 1 (
    echo [..] 检测到 APP 未安装，正在安装 APK（约 271MB，请耐心等待）...
    "%ADB%" -s %SERIAL% install -r -d "D:\GOSHORE\android\app\build\outputs\apk\debug\app-debug.apk"
)

rem ===== 5. 拉起 APP =====
"%ADB%" -s %SERIAL% shell am start -n com.goshor.app/.MainActivity >nul 2>&1
if errorlevel 1 (
    echo [X] 启动失败，请确认 APK 已正确安装
    pause
    exit /b 1
)
echo [OK] 上岸题库 APP 已启动
timeout /t 2 >nul
