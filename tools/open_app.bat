@echo off
setlocal
title GOSHORE APP Launcher

rem silent mode: no pause/timeout, ASCII status markers for FastAPI /api/open_app
set "SILENT=0"
if /i "%~1"=="silent" set "SILENT=1"

rem avoid adb.log permission issue in system Temp
set "TEMP=D:\GOSHORE\.tmp"
set "TMP=D:\GOSHORE\.tmp"
if not exist "%TEMP%" mkdir "%TEMP%" >nul 2>&1

rem ===== 1. locate adb =====
set "ADB=D:\GOSHORE\.android-sdk\platform-tools\adb.exe"
if not exist "%ADB%" set "ADB=D:\platform-tools-latest-windows\platform-tools\adb.exe"
if not exist "%ADB%" (
    for /f "delims=" %%i in ('where adb 2^>nul') do set "ADB=%%i"
)
if not exist "%ADB%" (
    echo [ERR] NO_ADB
    if "%SILENT%"=="1" exit /b 1
    echo adb.exe not found. Install Android platform-tools first.
    pause
    exit /b 1
)

"%ADB%" start-server >nul 2>&1

rem ===== 2. find connected device =====
set "SERIAL="
for /f "skip=1 tokens=1,2" %%a in ('"%ADB%" devices 2^>nul') do (
    if "%%b"=="device" if not defined SERIAL set "SERIAL=%%a"
)

rem ===== 3. try common emulator adb ports =====
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

rem ===== 3b. launch MuMu player when no device yet =====
if not defined SERIAL (
    set "MUMU=%ProgramFiles%\Netease\MuMu\nx_main\mumu-cli.exe"
    if not exist "%MUMU%" set "MUMU=%ProgramFiles(x86)%\Netease\MuMu\nx_main\mumu-cli.exe"
    if not exist "%MUMU%" set "MUMU=D:\Program Files\Netease\MuMu\nx_main\mumu-cli.exe"
    if not exist "%MUMU%" set "MUMU=%LOCALAPPDATA%\Programs\MuMu\nx_main\mumu-cli.exe"
    if exist "%MUMU%" (
        echo [INFO] STARTING_MUMU
        "%MUMU%" control --vmindex 0 launch >nul 2>&1
        for /l %%n in (1,1,30) do (
            if not defined SERIAL (
                "%ADB%" connect 127.0.0.1:16384 >nul 2>&1
                "%ADB%" connect 127.0.0.1:7555 >nul 2>&1
                for /f "skip=1 tokens=1,2" %%a in ('"%ADB%" devices 2^>nul') do (
                    if "%%b"=="device" if not defined SERIAL set "SERIAL=%%a"
                )
                if not defined SERIAL timeout /t 4 >nul
            )
        )
    )
)

if not defined SERIAL (
    echo [ERR] NO_DEVICE
    if "%SILENT%"=="1" exit /b 1
    echo No emulator or device found.
    echo Install MuMu player, or plug in a phone with USB debugging on.
    pause
    exit /b 1
)

echo [OK] DEVICE=%SERIAL%

rem ===== 4. install APK if missing =====
set "ROOT=%~dp0.."
set "APK=%ROOT%\dist\goshor-20261009.apk"
if not exist "%APK%" set "APK=%ROOT%\android\app\build\outputs\apk\debug\app-debug.apk"
"%ADB%" -s %SERIAL% shell pm list packages com.goshor.app 2>nul | findstr /i "goshor" >nul
if errorlevel 1 (
    echo [INFO] INSTALLING_APK
    if not exist "%APK%" (
        echo [ERR] NO_APK
        if "%SILENT%"=="1" exit /b 1
        pause
        exit /b 1
    )
    "%ADB%" -s %SERIAL% install -r -d "%APK%"
)

rem ===== 5. launch app =====
"%ADB%" -s %SERIAL% shell am start -n com.goshor.app/.MainActivity >nul 2>&1
if errorlevel 1 (
    echo [ERR] START_FAILED
    if "%SILENT%"=="1" exit /b 1
    echo Launch failed. Check if the APK is installed correctly.
    pause
    exit /b 1
)
echo [OK] APP_STARTED
if "%SILENT%"=="1" exit /b 0
echo Done.
timeout /t 2 >nul
