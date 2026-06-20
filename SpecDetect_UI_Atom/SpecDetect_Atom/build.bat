@echo off
REM Build script for SGAtom
REM Usage: build.bat

setlocal enabledelayedexpansion

REM Get version from service.py
for /f "delims=" %%a in ('powershell -ExecutionPolicy Bypass -File "%~dp0get_version.ps1"') do set "VERSION=%%a"
if not defined VERSION set "VERSION=1.1.4"

echo Detected version: %VERSION%

echo ========================================
echo   SGAtom Build v%VERSION%
echo ========================================
echo.

REM Paths
set PROJECT_DIR=%~dp0
set OUTPUT_DIR=%PROJECT_DIR%dist\SGAtom_v%VERSION%
set PYINSTALLER=C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37\Scripts\pyinstaller.exe

REM Check PyInstaller
if not exist "%PYINSTALLER%" (
    echo [ERROR] PyInstaller not found
    exit /b 1
)

REM Update version_info.txt
echo [0/5] Updating version to v%VERSION%...
powershell -ExecutionPolicy Bypass -File update_version.ps1 -Version "%VERSION%"

REM Clean
echo [1/5] Cleaning...
cd /d "%PROJECT_DIR%"
if exist build rmdir /s /q build
if exist %OUTPUT_DIR% rmdir /s /q %OUTPUT_DIR%
mkdir dist

REM Build
echo [2/5] Building...
"%PYINSTALLER%" --onefile packaging\SpecDetect_Atom.spec --distpath "%OUTPUT_DIR%"
if errorlevel 1 (
    echo [ERROR] Build failed
    exit /b 1
)

REM Copy DLLs
echo [3/5] Copying DLLs...
if exist runtime\*.dll xcopy /y /q runtime\*.dll "%OUTPUT_DIR%\"
if exist "..\..\dist\SGAtom_v1.0.6\python37.dll" copy /y "..\..\dist\SGAtom_v1.0.6\python37.dll" "%OUTPUT_DIR%\"
if exist "..\..\dist\SGAtom_v1.0.6\vcruntime140.dll" copy /y "..\..\dist\SGAtom_v1.0.6\vcruntime140.dll" "%OUTPUT_DIR%\"
if exist "..\..\dist\SGAtom_v1.0.6\ucrtbase.dll" copy /y "..\..\dist\SGAtom_v1.0.6\ucrtbase.dll" "%OUTPUT_DIR%\"

REM Compress
echo [4/5] Compressing...
powershell -Command "Compress-Archive -Path '%OUTPUT_DIR%\SGAtom_v%VERSION%.exe' -DestinationPath 'dist\SGAtom_v%VERSION%.zip' -Force"
if errorlevel 1 (
    echo [ERROR] Compress failed
    exit /b 1
)

REM Copy to central dist
echo [5/5] Copying to central dist...
if not exist "D:\arvin\claude_workspace\SpecDetect_V4\dist" mkdir "D:\arvin\claude_workspace\SpecDetect_V4\dist"
copy /y "%OUTPUT_DIR%\SGAtom_v%VERSION%.exe" "D:\arvin\claude_workspace\SpecDetect_V4\dist\"
copy /y "dist\SGAtom_v%VERSION%.zip" "D:\arvin\claude_workspace\SpecDetect_V4\dist\"

REM Done
echo [6/6] Done!
echo.
echo Output:
echo   - %OUTPUT_DIR%\SGAtom_v%VERSION%.exe
echo   - dist\SGAtom_v%VERSION%.zip
echo.
pause
