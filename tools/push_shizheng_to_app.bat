@echo off
chcp 65001 >nul
setlocal
set "TEMP=D:\GOSHORE\.tmp"
set "TMP=D:\GOSHORE\.tmp"

set "ADB=D:\Program Files\Netease\MuMu\nx_main\adb.exe"
if not exist "%ADB%" set "ADB=D:\GOSHORE\.android-sdk\platform-tools\adb.exe"

echo [1/4] 查找已连接设备...
set "SERIAL="
for /f "skip=1 tokens=1,2" %%a in ('"%ADB%" devices 2^>nul') do (
    if "%%b"=="device" if not defined SERIAL set "SERIAL=%%a"
)
if not defined SERIAL (
    echo [ERR] 未检测到设备，请先启动MuMu模拟器
    pause
    exit /b 1
)
echo [OK] DEVICE=%SERIAL%

echo [2/4] 检查APP是否安装...
"%ADB%" -s %SERIAL% shell pm list packages com.goshor.app 2>nul | findstr /i "goshor" >nul
if errorlevel 1 (
    echo [ERR] APP未安装，请先安装上岸题库APP
    pause
    exit /b 1
)
echo [OK] APP已安装

echo [3/4] 推送题库到APP...
"%ADB%" -s %SERIAL% push "D:\GOSHORE\data\goshor.db" /data/data/com.goshor.app/files/goshor.db
if errorlevel 1 (
    echo [ERR] 推送失败，尝试备用路径...
    "%ADB%" -s %SERIAL% push "D:\GOSHORE\data\goshor.db" /sdcard/Android/data/com.goshor.app/files/goshor.db
    if errorlevel 1 (
        echo [ERR] 推送失败，请检查ADB权限
        pause
        exit /b 1
    )
)
echo [OK] 题库已推送

echo [4/4] 重启APP...
"%ADB%" -s %SERIAL% shell am force-stop com.goshor.app
"%ADB%" -s %SERIAL% shell am start -n com.goshor.app/.MainActivity
echo [OK] APP已重启，时政内容已更新

pause
