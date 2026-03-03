@echo off
:: RC-to-Controller ADB Setup
:: Sets up forward tunnel: PC's localhost:8080 -> RC's 8080
:: This lets the Python server connect to the RC's WebSocket server via USB.
:: Run this once before launching the Python server.

echo === RC to Controller - ADB Setup ===
echo.

:: Check ADB is available
where adb >nul 2>&1
if errorlevel 1 (
    echo ERROR: adb not found in PATH. Install Android Platform Tools.
    pause
    exit /b 1
)

:: List devices
echo Connected devices:
adb devices
echo.

:: Set up forward tunnel (PC localhost:8080 -> RC's port 8080)
echo Setting up forward tunnel...
adb forward tcp:8080 tcp:8080

echo.
echo === Done! ===
echo PC localhost:8080 now tunnels to the RC's WebSocket server.
echo Start the Python server if not already running:
echo   cd python\server ^&^& python main.py
echo.
pause
