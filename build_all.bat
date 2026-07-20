@echo off
REM ============================================================
REM  build_all.bat
REM  Build both x64 and x86 EXEs in one go.
REM
REM  Usage:
REM      build_all.bat                x64 + x86 full
REM      build_all.bat no-cython      both skip Cython
REM      build_all.bat x64-only       x64 only
REM      build_all.bat x86-only       x86 only
REM ============================================================

setlocal enabledelayedexpansion

set "MODE=both"
if /i "%~1"=="x64-only" set "MODE=x64"
if /i "%~1"=="x86-only" set "MODE=x86"
if /i "%~1"=="no-cython" set "MODE=both-nocython"

echo.
echo ############################################################
echo #   build_all.bat
echo #   Mode: %MODE%
echo ############################################################
echo.

set "FAILED=0"

REM ---------- 1. x64 ----------
if /i "%MODE%"=="x86" goto SKIP_X64

echo.
echo ############################################################
echo #  [1/2] x64 build
echo ############################################################
echo.
call "%~dp0build_x64.bat" %1
if errorlevel 1 (
    echo [build_all] FATAL: x64 build failed
    set "FAILED=1"
    goto END
)
echo [build_all] x64 build OK
goto AFTER_X64

:SKIP_X64
echo [build_all] Skip x64 -- mode %MODE%

:AFTER_X64

REM ---------- 2. x86 ----------
if /i "%MODE%"=="x64" goto END

echo.
echo ############################################################
echo #  [2/2] x86 build
echo ############################################################
echo.
call "%~dp0build_x86.bat" %1
if errorlevel 1 (
    echo [build_all] FATAL: x86 build failed
    set "FAILED=1"
    goto END
)
echo [build_all] x86 build OK

:END
echo.
if "%FAILED%"=="1" (
    echo ############################################################
    echo #   build_all.bat FAILED
    echo ############################################################
    endlocal & exit /b 1
)

echo ############################################################
echo #   build_all.bat DONE
echo ############################################################
echo.
if exist "%~dp0dist\win7-x64" echo     - dist\win7-x64\
if exist "%~dp0dist\win7-x86" echo     - dist\win7-x86\
echo.
endlocal & exit /b 0
