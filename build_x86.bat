@echo off
REM ============================================================
REM  build_x86.bat
REM  Build all 5 EXEs for x86 (32-bit).
REM
REM  - 32-bit Python:    C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32\python.exe
REM  - 32-bit runtime:   SpecDetect_UI_Atom\SpecDetect_Atom\runtime\win32\
REM  - 32-bit output:    dist\win7-x86\
REM  - Cython output:    cp37-win32.pyd
REM
REM  Prerequisites (see docs\BUILD_x86.md):
REM    [ ] Python 3.7.9 x86 installed at PYTHON_X86_HOME
REM    [ ] pip install pyinstaller==4.10 (or 4.5.1)
REM    [ ] pip install -r SpecDetect_POC\requirements.txt
REM    [ ] pip install cryptography<36, cffi, Cython<0.30, pywin32
REM    [ ] Win7 x86 Stub DLLs prepared in runtime\win32\
REM    [ ] VS 2022 BuildTools x86 toolset installed
REM
REM  Usage:
REM      build_x86.bat                Full build
REM      build_x86.bat no-cython      Skip Cython (PyInstaller only)
REM
REM  Isolation from x64 build:
REM    - Does NOT read runtime\win_amd64\ or runtime\ (root)
REM    - Does NOT write dist\win7-x64\
REM    - Does NOT touch src\license\*-amd64.pyd
REM ============================================================

setlocal enabledelayedexpansion

call "%~dp0build_config.bat" x86
if errorlevel 1 (
    echo [build_x86] FATAL: build_config.bat failed
    exit /b 1
)

echo.
echo ========================================
echo   build_x86.bat
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

REM ---------- 1. x86-specific strong check ----------
if not exist "%PYTHON_EXE%" (
    echo [build_x86] FATAL: x86 Python not found: %PYTHON_EXE%
    echo             Install Python 3.7.9 x86 to: %PYTHON_X86_HOME%
    echo             https://www.python.org/ftp/python/3.7.9/python-3.7.9.exe
    exit /b 1
)

REM Verify Python bitness
REM  Python 3.7 on Windows returns "win32" (no dash), so use sys.maxsize not sysconfig.get_platform().
"%PYTHON_EXE%" -c "import sys; sys.exit(0 if sys.maxsize <= 2**32 else 1)"
if errorlevel 1 (
    echo [build_x86] FATAL: "%PYTHON_EXE%" is not 32-bit Python
    "%PYTHON_EXE%" -c "import sys,platform; print('maxsize:', sys.maxsize); print('arch:', platform.architecture()[0])"
    exit /b 1
)

REM ---------- 2. Project subdirs (x86 build dirs separate from x64) ----------
set "ATOM_PROJECT_DIR=%ROOT_DIR%\SpecDetect_UI_Atom\SpecDetect_Atom"
set "PROXY_PROJECT_DIR=%ROOT_DIR%\SpecDetect_POC\soap_proxy"
set "RMCP_PROXY_PROJECT_DIR=%ATOM_PROJECT_DIR%"

set "ATOM_BUILD_DIR=%ATOM_PROJECT_DIR%\build_onedir_x86"
set "PROXY_BUILD_DIR=%PROXY_PROJECT_DIR%\build_onedir_x86"
set "RMCP_BUILD_DIR=%ATOM_PROJECT_DIR%\build_proxy_x86"
set "GEN_LICENSE_BUILD_DIR=%ATOM_PROJECT_DIR%\build_gen_license_x86"
set "GEN_AUTH_CODE_BUILD_DIR=%ATOM_PROJECT_DIR%\build_gen_auth_code_x86"

REM ---------- 3. Clean x86 build artifacts ----------
echo [1/8] Cleaning x86 build artifacts...
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

REM ---------- 4. Cython compile (x86) ----------
REM  Critical: x86 Python produces cp37-win32.pyd.
REM  Clean any residual amd64 .pyd first to avoid contaminating the x86 EXE.
echo [2/8] Cython compiling license module to .pyd x86 ...
if /i not "%~1"=="no-cython" (
    pushd "%ATOM_PROJECT_DIR%"
        if exist "src\license\*.pyd" del /q "src\license\*.pyd"
        if exist "src\license\license\*.pyd" del /q "src\license\license\*.pyd"

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

        REM Double-check no amd64 leak
        dir "src\license\*.pyd" | findstr /i "amd64" >nul
        if not errorlevel 1 (
            echo [FATAL] Found amd64 .pyd in src\license\, would corrupt x86 EXE
            popd
            exit /b 1
        )
    popd
) else (
    echo [skip] Cython skipped
)

REM ---------- 5. SGAtom (x86) ----------
echo [3/8] Building SGAtom v%ATOM_VERSION% onefile x86 ...
pushd "%ATOM_PROJECT_DIR%"
    "%PYINSTALLER%" --onefile packaging\SpecDetect_Atom.spec --distpath "%ATOM_BUILD_DIR%"
    if errorlevel 1 (
        echo [FATAL] SGAtom build failed
        popd
        exit /b 1
    )
popd

REM ---------- 6. SOAPProxy (x86) ----------
echo [4/8] Building SOAPProxy v%PROXY_VERSION% onefile x86 ...
pushd "%PROXY_PROJECT_DIR%"
    "%PYINSTALLER%" --onefile packaging\SOAPProxy.spec --distpath "%PROXY_BUILD_DIR%"
    if errorlevel 1 (
        echo [FATAL] SOAPProxy build failed
        popd
        exit /b 1
    )
popd

REM ---------- 7. RMCPProxy (x86) ----------
echo [5/8] Building RMCPProxy v%RMCP_PROXY_VERSION% onefile x86 ...
pushd "%RMCP_PROXY_PROJECT_DIR%"
    "%PYINSTALLER%" --onefile packaging\rmcp_proxy.spec --distpath "%RMCP_BUILD_DIR%"
    if errorlevel 1 (
        echo [FATAL] RMCPProxy build failed
        popd
        exit /b 1
    )
popd

REM ---------- 8. gen_license (x86) ----------
echo [6/8] Building gen_license.exe onefile x86 ...
pushd "%ATOM_PROJECT_DIR%"
    "%PYINSTALLER%" --onefile packaging\gen_license.spec --distpath "%GEN_LICENSE_BUILD_DIR%"
    if errorlevel 1 (
        echo [FATAL] gen_license build failed
        popd
        exit /b 1
    )
popd

REM ---------- 9. gen_auth_code (x86) ----------
echo [7/8] Building gen_auth_code v%ATOM_VERSION% onefile x86 ...
pushd "%ATOM_PROJECT_DIR%"
    "%PYINSTALLER%" --onefile packaging\gen_auth_code.spec --distpath "%GEN_AUTH_CODE_BUILD_DIR%"
    if errorlevel 1 (
        echo [FATAL] gen_auth_code build failed
        popd
        exit /b 1
    )
popd

REM ---------- 10. Copy to OUTPUT_DIR with _x86 suffix ----------
echo [8/8] Copying artifacts to %OUTPUT_DIR% ...
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
if not exist "%OUTPUT_DIR%\config" mkdir "%OUTPUT_DIR%\config"
if not exist "%OUTPUT_DIR%\keys"   mkdir "%OUTPUT_DIR%\keys"

copy /y "%ATOM_BUILD_DIR%\SGAtom_v%ATOM_VERSION%.exe"            "%OUTPUT_DIR%\SGAtom_v%ATOM_VERSION%_x86.exe"            >nul
copy /y "%PROXY_BUILD_DIR%\SOAPProxy_v%PROXY_VERSION%.exe"        "%OUTPUT_DIR%\SOAPProxy_v%PROXY_VERSION%_x86.exe"        >nul
copy /y "%RMCP_BUILD_DIR%\rmcp_proxy_v%RMCP_PROXY_VERSION%.exe"   "%OUTPUT_DIR%\rmcp_proxy_v%RMCP_PROXY_VERSION%_x86.exe"   >nul
copy /y "%GEN_LICENSE_BUILD_DIR%\gen_license.exe"                 "%OUTPUT_DIR%\gen_license_v%ATOM_VERSION%_x86.exe"        >nul
copy /y "%GEN_AUTH_CODE_BUILD_DIR%\gen_auth_code_v%ATOM_VERSION%.exe"  "%OUTPUT_DIR%\gen_auth_code_v%ATOM_VERSION%_x86.exe" >nul

if exist "%ATOM_PROJECT_DIR%\config\" xcopy /e /y /q "%ATOM_PROJECT_DIR%\config\*" "%OUTPUT_DIR%\config\"
if exist "%ATOM_PROJECT_DIR%\keys\private_key.pem" copy /y "%ATOM_PROJECT_DIR%\keys\private_key.pem" "%OUTPUT_DIR%\keys\"

echo.
echo ========================================
echo   build_x86.bat DONE
echo ========================================
echo   Output: %OUTPUT_DIR%\
echo     - SGAtom_v%ATOM_VERSION%_x86.exe
echo     - SOAPProxy_v%PROXY_VERSION%_x86.exe
echo     - rmcp_proxy_v%RMCP_PROXY_VERSION%_x86.exe
echo     - gen_license_v%ATOM_VERSION%_x86.exe
echo     - gen_auth_code_v%ATOM_VERSION%_x86.exe
echo ========================================
echo.
echo   Before deploy, ensure runtime\win32\ has all 32-bit Stub DLLs.
echo   See docs\BUILD_x86.md section 2.4.
echo.
endlocal & exit /b 0
