@echo off
REM ============================================================
REM  build_x64.bat
REM  Build all 5 EXEs for x64.
REM
REM  - 100% preserves existing 64-bit build behavior
REM  - 64-bit Python: ...\Python37\python.exe (existing)
REM  - 64-bit runtime: SpecDetect_UI_Atom\SpecDetect_Atom\runtime\win_amd64\
REM  - 64-bit output:  dist\win7-x64\
REM  - Cython output:  cp37-win_amd64.pyd
REM
REM  Usage:
REM      build_x64.bat                Full build
REM      build_x64.bat no-cython      Skip Cython (PyInstaller only)
REM ============================================================

setlocal enabledelayedexpansion

call "%~dp0build_config.bat" x64
if errorlevel 1 (
    echo [build_x64] FATAL: build_config.bat failed
    exit /b 1
)

echo.
echo ========================================
echo   build_x64.bat
echo ========================================
echo   BUILD_ARCH    = %BUILD_ARCH%
echo   Python        = %PYTHON_EXE%
echo   PyInstaller   = %PYINSTALLER%
echo   Runtime DLLs  = %RUNTIME_DIR%
echo   Output dir    = %OUTPUT_DIR%
echo   Cython suffix = %PYD_SUFFIX%
echo   Atom v        = %ATOM_VERSION%
echo   Proxy v       = %PROXY_VERSION%
echo   RMCP v        = %RMCP_PROXY_VERSION%
echo ========================================
echo.

REM ---------- 1. Project subdirs ----------
set "ATOM_PROJECT_DIR=%ROOT_DIR%\SpecDetect_UI_Atom\SpecDetect_Atom"
set "PROXY_PROJECT_DIR=%ROOT_DIR%\SpecDetect_POC\soap_proxy"
set "RMCP_PROXY_PROJECT_DIR=%ATOM_PROJECT_DIR%"

set "ATOM_BUILD_DIR=%ATOM_PROJECT_DIR%\build_onedir"
set "PROXY_BUILD_DIR=%PROXY_PROJECT_DIR%\build_onedir"
set "RMCP_BUILD_DIR=%ATOM_PROJECT_DIR%\build_proxy"
set "GEN_LICENSE_BUILD_DIR=%ATOM_PROJECT_DIR%\build_gen_license"
set "GEN_AUTH_CODE_BUILD_DIR=%ATOM_PROJECT_DIR%\build_gen_auth_code"

REM ---------- 2. Pass BUILD_ARCH to PyInstaller & children ----------
REM    No "set BUILD_ARCH=" here, it is already set by build_config.bat
REM    and we use the same value.

REM ---------- 3. Clean previous build ----------
echo [1/8] Cleaning previous build artifacts...
if exist "%ATOM_BUILD_DIR%"          rmdir /s /q "%ATOM_BUILD_DIR%"
if exist "%PROXY_BUILD_DIR%"         rmdir /s /q "%PROXY_BUILD_DIR%"
if exist "%RMCP_BUILD_DIR%"          rmdir /s /q "%RMCP_BUILD_DIR%"
if exist "%GEN_LICENSE_BUILD_DIR%"   rmdir /s /q "%GEN_LICENSE_BUILD_DIR%"
if exist "%GEN_AUTH_CODE_BUILD_DIR%" rmdir /s /q "%GEN_AUTH_CODE_BUILD_DIR%"

if exist "%OUTPUT_DIR%\SGAtom_v*.exe"            del /q "%OUTPUT_DIR%\SGAtom_v*.exe"
if exist "%OUTPUT_DIR%\SOAPProxy_v*.exe"         del /q "%OUTPUT_DIR%\SOAPProxy_v*.exe"
if exist "%OUTPUT_DIR%\rmcp_proxy_v*.exe"        del /q "%OUTPUT_DIR%\rmcp_proxy_v*.exe"
if exist "%OUTPUT_DIR%\gen_license*.exe"         del /q "%OUTPUT_DIR%\gen_license*.exe"
if exist "%OUTPUT_DIR%\gen_auth_code_v*.exe"     del /q "%OUTPUT_DIR%\gen_auth_code_v*.exe"

REM ---------- 4. Cython compile ----------
echo [2/8] Cython compiling license module to .pyd ...
if /i not "%~1"=="no-cython" (
    pushd "%ATOM_PROJECT_DIR%"
        "%PYTHON_EXE%" setup_cython.py build_ext --inplace 2>nul
        if exist "src\license\license\*.pyd" (
            move /y "src\license\license\*.pyd" "src\license\" >nul 2>&1
            rmdir /s /q "src\license\license" >nul 2>&1
        )
        rmdir /s /q build_cython >nul 2>&1
        del /q "src\license\*.c" >nul 2>&1

        if exist "src\license\crypto.%PYD_SUFFIX%.pyd" (
            echo [OK] Cython .pyd ready for %BUILD_ARCH%
        ) else (
            echo [FATAL] Cython .pyd missing: src\license\crypto.%PYD_SUFFIX%.pyd
            popd
            exit /b 1
        )
    popd
) else (
    echo [skip] Cython skipped
)

REM ---------- 5. SGAtom ----------
echo [3/8] Building SGAtom v%ATOM_VERSION% onefile ...
pushd "%ATOM_PROJECT_DIR%"
    set /a SGATOM_RETRY=0
:retry_sgatom
    set /a SGATOM_RETRY+=1
    if %SGATOM_RETRY% gtr 3 goto sgatom_fatal
    "%PYINSTALLER%" --onefile packaging\SpecDetect_Atom.spec --distpath "%ATOM_BUILD_DIR%"
    if not errorlevel 1 goto sgatom_ok
    echo [RETRY %SGATOM_RETRY%/3] SGAtom failed (likely AV scan), waiting 5s...
    timeout /t 5 >nul
    goto :retry_sgatom
:sgatom_fatal
    echo [FATAL] SGAtom build failed after 3 retries
    popd
    exit /b 1
:sgatom_ok
popd

REM ---------- 6. SOAPProxy ----------
echo [4/8] Building SOAPProxy v%PROXY_VERSION% onefile ...
pushd "%PROXY_PROJECT_DIR%"
    set /a PROXY_RETRY=0
:retry_proxy
    set /a PROXY_RETRY+=1
    if %PROXY_RETRY% gtr 3 goto proxy_fatal
    "%PYINSTALLER%" --onefile packaging\SOAPProxy.spec --distpath "%PROXY_BUILD_DIR%"
    if not errorlevel 1 goto proxy_ok
    echo [RETRY %PROXY_RETRY%/3] SOAPProxy failed (likely AV scan), waiting 5s...
    timeout /t 5 >nul
    goto :retry_proxy
:proxy_fatal
    echo [FATAL] SOAPProxy build failed after 3 retries
    popd
    exit /b 1
:proxy_ok
popd

REM ---------- 7. RMCPProxy ----------
echo [5/8] Building RMCPProxy v%RMCP_PROXY_VERSION% onefile ...
pushd "%RMCP_PROXY_PROJECT_DIR%"
    set /a RMCP_RETRY=0
:retry_rmcp
    set /a RMCP_RETRY+=1
    if %RMCP_RETRY% gtr 3 goto rmcp_fatal
    "%PYINSTALLER%" --onefile packaging\rmcp_proxy.spec --distpath "%RMCP_BUILD_DIR%"
    if not errorlevel 1 goto rmcp_ok
    echo [RETRY %RMCP_RETRY%/3] RMCPProxy failed (likely AV scan), waiting 5s...
    timeout /t 5 >nul
    goto :retry_rmcp
:rmcp_fatal
    echo [FATAL] RMCPProxy build failed after 3 retries
    popd
    exit /b 1
:rmcp_ok
popd

REM ---------- 8. gen_license ----------
echo [6/8] Building gen_license.exe onefile ...
pushd "%ATOM_PROJECT_DIR%"
    set /a GEN_LICENSE_RETRY=0
:retry_gen_license
    set /a GEN_LICENSE_RETRY+=1
    if %GEN_LICENSE_RETRY% gtr 3 goto gen_license_fatal
    "%PYINSTALLER%" --onefile packaging\gen_license.spec --distpath "%GEN_LICENSE_BUILD_DIR%"
    if not errorlevel 1 goto gen_license_ok
    echo [RETRY %GEN_LICENSE_RETRY%/3] gen_license failed (likely AV scan), waiting 5s...
    timeout /t 5 >nul
    goto :retry_gen_license
:gen_license_fatal
    echo [FATAL] gen_license build failed after 3 retries
    popd
    exit /b 1
:gen_license_ok
popd

REM ---------- 9. gen_auth_code ----------
echo [7/8] Building gen_auth_code v%ATOM_VERSION% onefile ...
pushd "%ATOM_PROJECT_DIR%"
    set /a GEN_AUTH_CODE_RETRY=0
:retry_gen_auth_code
    set /a GEN_AUTH_CODE_RETRY+=1
    if %GEN_AUTH_CODE_RETRY% gtr 3 goto gen_auth_code_fatal
    "%PYINSTALLER%" --onefile packaging\gen_auth_code.spec --distpath "%GEN_AUTH_CODE_BUILD_DIR%"
    if not errorlevel 1 goto gen_auth_code_ok
    echo [RETRY %GEN_AUTH_CODE_RETRY%/3] gen_auth_code failed (likely AV scan), waiting 5s...
    timeout /t 5 >nul
    goto :retry_gen_auth_code
:gen_auth_code_fatal
    echo [FATAL] gen_auth_code build failed after 3 retries
    popd
    exit /b 1
:gen_auth_code_ok
popd

REM ---------- 10. Copy to OUTPUT_DIR ----------
echo [8/8] Copying artifacts to %OUTPUT_DIR% ...
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
if not exist "%OUTPUT_DIR%\config" mkdir "%OUTPUT_DIR%\config"
if not exist "%OUTPUT_DIR%\keys"   mkdir "%OUTPUT_DIR%\keys"

copy /y "%ATOM_BUILD_DIR%\SGAtom_v%ATOM_VERSION%.exe"            "%OUTPUT_DIR%\SGAtom_v%ATOM_VERSION%.exe"            >nul
copy /y "%PROXY_BUILD_DIR%\SOAPProxy_v%PROXY_VERSION%.exe"        "%OUTPUT_DIR%\SOAPProxy_v%PROXY_VERSION%.exe"        >nul
copy /y "%RMCP_BUILD_DIR%\rmcp_proxy_v%RMCP_PROXY_VERSION%.exe"   "%OUTPUT_DIR%\rmcp_proxy_v%RMCP_PROXY_VERSION%.exe"   >nul
copy /y "%GEN_LICENSE_BUILD_DIR%\gen_license.exe"                 "%OUTPUT_DIR%\gen_license_v%ATOM_VERSION%.exe"        >nul
copy /y "%GEN_AUTH_CODE_BUILD_DIR%\gen_auth_code_v%ATOM_VERSION%.exe"  "%OUTPUT_DIR%\gen_auth_code_v%ATOM_VERSION%.exe" >nul

if exist "%ATOM_PROJECT_DIR%\config\" xcopy /e /y /q "%ATOM_PROJECT_DIR%\config\*" "%OUTPUT_DIR%\config\"
if exist "%ATOM_PROJECT_DIR%\keys\private_key.pem" copy /y "%ATOM_PROJECT_DIR%\keys\private_key.pem" "%OUTPUT_DIR%\keys\"

echo.
echo ========================================
echo   build_x64.bat DONE
echo ========================================
echo   Output: %OUTPUT_DIR%\
echo     - SGAtom_v%ATOM_VERSION%.exe
echo     - SOAPProxy_v%PROXY_VERSION%.exe
echo     - rmcp_proxy_v%RMCP_PROXY_VERSION%.exe
echo     - gen_license_v%ATOM_VERSION%.exe
echo     - gen_auth_code_v%ATOM_VERSION%.exe
echo ========================================
echo.
endlocal & exit /b 0
