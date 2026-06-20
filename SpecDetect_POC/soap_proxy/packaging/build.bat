@echo off
REM Build script for SOAPProxy (single exe)
REM Usage: build.bat (run from soap_proxy root, NOT from packaging/)

setlocal enabledelayedexpansion

set "PYINSTALLER=C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37\Scripts\pyinstaller.exe"

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."

REM 从唯一版本源读取 PROXY_VERSION
python "%~dp0..\..\..\get_version.py" "%~dp0..\..\..\."
if errorlevel 1 (
    echo [ERROR] Failed to parse version
    exit /b 1
)
for /f "usebackq tokens=1,2 delims==" %%A in ("%SCRIPT_DIR%..\..\..\_version.env") do (
    if "%%A"=="PROXY_VERSION" set "VERSION=%%B"
)

echo ========================================
echo   SOAPProxy Build v%VERSION% (single exe)
echo ========================================
echo.

if not exist "%PYINSTALLER%" (
    echo [ERROR] PyInstaller not found
    exit /b 1
)

echo [1/4] Cleaning...
if exist "%PROJECT_DIR%\build" rmdir /s /q "%PROJECT_DIR%\build"
if exist "%PROJECT_DIR%\dist\SOAPProxy*.exe" del /q "%PROJECT_DIR%\dist\SOAPProxy*.exe"

echo [2/4] Building...
"%PYINSTALLER%" --onefile "%SCRIPT_DIR%SOAPProxy.spec" --distpath "%PROJECT_DIR%\dist"
if errorlevel 1 (
    echo [ERROR] Build failed
    exit /b 1
)

echo [3/4] Verifying output...
if exist "%PROJECT_DIR%\dist\SOAPProxy_v%VERSION%.exe" (
    echo [OK] Output: %PROJECT_DIR%\dist\SOAPProxy_v%VERSION%.exe
) else (
    echo [WARNING] Expected output not found
    dir "%PROJECT_DIR%\dist\"
)

REM Copy to central dist
echo [4/4] Copying to central dist...
if not exist "D:\arvin\claude_workspace\SpecDetect_V4\dist" mkdir "D:\arvin\claude_workspace\SpecDetect_V4\dist"
copy /y "%PROJECT_DIR%\dist\SOAPProxy_v%VERSION%.exe" "D:\arvin\claude_workspace\SpecDetect_V4\dist\"

echo [5/5] Done.
echo.
pause
