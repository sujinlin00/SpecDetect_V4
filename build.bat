@echo off
REM ============================================================
REM  build.bat
REM  Backward-compatible entry (thin wrapper).
REM
REM  Behavior:
REM    1. Calls build_x64.bat to build dist\win7-x64\
REM    2. Syncs the 5 EXEs back to dist\ root for legacy deploy
REM
REM  Usage:
REM      build.bat                Default 64-bit + sync to dist\
REM      build.bat no-sync        Build only, no legacy sync
REM ============================================================

setlocal enabledelayedexpansion

set "DO_SYNC=1"
if /i "%~1"=="no-sync" set "DO_SYNC=0"

call "%~dp0build_x64.bat" %1
if errorlevel 1 (
    echo [build.bat] build_x64.bat failed
    exit /b 1
)

if "%DO_SYNC%"=="0" goto END

call "%~dp0build_config.bat" x64 >nul
if errorlevel 1 (
    echo [build.bat] WARN: build_config.bat failed during sync, skip
    goto END
)

echo.
echo [build.bat] Syncing artifacts back to dist\ root for legacy compat...

set "OLD_DIST=%ROOT_DIR%\dist"
set "NEW_DIST=%ROOT_DIR%\dist\win7-x64"

if not exist "%OLD_DIST%" mkdir "%OLD_DIST%"

copy /y "%NEW_DIST%\SGAtom_v%ATOM_VERSION%.exe"          "%OLD_DIST%\SGAtom_v%ATOM_VERSION%.exe"          >nul
copy /y "%NEW_DIST%\SOAPProxy_v%PROXY_VERSION%.exe"      "%OLD_DIST%\SOAPProxy_v%PROXY_VERSION%.exe"      >nul
copy /y "%NEW_DIST%\rmcp_proxy_v%RMCP_PROXY_VERSION%.exe" "%OLD_DIST%\rmcp_proxy_v%RMCP_PROXY_VERSION%.exe" >nul
copy /y "%NEW_DIST%\gen_license_v%ATOM_VERSION%.exe"     "%OLD_DIST%\gen_license.exe"                       >nul
copy /y "%NEW_DIST%\gen_auth_code_v%ATOM_VERSION%.exe"   "%OLD_DIST%\gen_auth_code_v%ATOM_VERSION%.exe"    >nul

if exist "%NEW_DIST%\config" xcopy /e /y /q "%NEW_DIST%\config" "%OLD_DIST%\config\"
if exist "%NEW_DIST%\keys"   xcopy /e /y /q "%NEW_DIST%\keys"   "%OLD_DIST%\keys\"

if exist "%NEW_DIST%\SGAtom_v%ATOM_VERSION%.exe" (
    powershell -Command "Compress-Archive -Path '%NEW_DIST%\SGAtom_v%ATOM_VERSION%.exe' -DestinationPath '%OLD_DIST%\SGAtom_v%ATOM_VERSION%.zip' -Force" >nul 2>&1
)

echo [build.bat] Legacy path synced: dist\SGAtom_v%ATOM_VERSION%.exe
echo.

:END
echo ========================================
echo   build.bat DONE
echo ========================================
echo   New layout:    dist\win7-x64\SGAtom_v%ATOM_VERSION%.exe
echo   Legacy path:   dist\SGAtom_v%ATOM_VERSION%.exe   (kept for compat)
echo ========================================
echo.
endlocal & exit /b 0
