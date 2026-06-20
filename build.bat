@echo off
REM Unified Build Script for SGAtom + SOAPProxy + RMCPProxy + gen_license

setlocal enabledelayedexpansion

REM ========================================
REM Versions (从 src/version.py 唯一来源读取)
REM ========================================
python "%~dp0get_version.py" "%~dp0."
if errorlevel 1 (
    echo [ERROR] Failed to parse version from get_version.py
    exit /b 1
)

for /f "usebackq tokens=1,2 delims==" %%A in ("%~dp0_version.env") do (
    set "%%A=%%B"
)

REM ========================================
REM Paths
REM ========================================
set "ROOT_DIR=%~dp0"
set "OUTPUT_DIR=%ROOT_DIR%dist"
set "PYINSTALLER=C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37\Scripts\pyinstaller.exe"
set "PYTHON_EXE=C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37\python.exe"

set "ATOM_PROJECT_DIR=%ROOT_DIR%SpecDetect_UI_Atom\SpecDetect_Atom"
set "PROXY_PROJECT_DIR=%ROOT_DIR%SpecDetect_POC\soap_proxy"
set "RMCP_PROXY_PROJECT_DIR=%ROOT_DIR%SpecDetect_POC\rmcp_proxy"

set "ATOM_BUILD_DIR=%ATOM_PROJECT_DIR%\build_onedir"
set "PROXY_BUILD_DIR=%PROXY_PROJECT_DIR%\build_onedir"
set "RMCP_BUILD_DIR=%RMCP_PROXY_PROJECT_DIR%\build_onedir"
set "GEN_LICENSE_BUILD_DIR=%ATOM_PROJECT_DIR%\build_gen_license"
set "GEN_AUTH_CODE_BUILD_DIR=%ATOM_PROJECT_DIR%\build_gen_auth_code"

echo ========================================
echo   Unified Build: SGAtom + SOAPProxy + RMCPProxy + gen_license + gen_auth_code
echo ========================================
echo   Atom:   v%ATOM_VERSION%
echo   Proxy:  v%PROXY_VERSION%
echo   RMCP:   v%RMCP_PROXY_VERSION%
echo ========================================
echo.

if not exist "%PYINSTALLER%" (
    echo [ERROR] PyInstaller not found at:
    echo   %PYINSTALLER%
    exit /b 1
)

REM ========================================
REM Step 1: Clean
REM ========================================
echo [1/9] Cleaning...
if exist "%ATOM_BUILD_DIR%" rmdir /s /q "%ATOM_BUILD_DIR%"
if exist "%PROXY_BUILD_DIR%" rmdir /s /q "%PROXY_BUILD_DIR%"
if exist "%RMCP_BUILD_DIR%" rmdir /s /q "%RMCP_BUILD_DIR%"
if exist "%GEN_LICENSE_BUILD_DIR%" rmdir /s /q "%GEN_LICENSE_BUILD_DIR%"
if exist "%GEN_AUTH_CODE_BUILD_DIR%" rmdir /s /q "%GEN_AUTH_CODE_BUILD_DIR%"
if exist "%OUTPUT_DIR%" rmdir /s /q "%OUTPUT_DIR%"

REM ========================================
REM Step 2: Cython compile license module -> .pyd
REM ========================================
echo [2/9] Cython compiling license module to .pyd...
pushd "%ATOM_PROJECT_DIR%"
    "%PYTHON_EXE%" setup_cython.py build_ext --inplace 2>nul
    REM Move .pyd files from nested dir to correct location
    if exist "src\license\license\*.pyd" (
        move /y "src\license\license\*.pyd" "src\license\" >nul 2>&1
        rmdir /s /q "src\license\license" >nul 2>&1
    )
    rmdir /s /q build_cython >nul 2>&1
    del /q "src\license\*.c" >nul 2>&1
    REM Verify .pyd files exist
    if exist "src\license\crypto.cp37-win_amd64.pyd" (
        echo [OK] Cython .pyd files ready
    ) else (
        echo [WARNING] Cython compile may have failed, checking...
        dir "src\license\*.pyd" 2>nul
    )
popd

REM ========================================
REM Step 3: Build SGAtom
REM ========================================
echo [3/9] Building SGAtom v%ATOM_VERSION% (onefile)...
pushd "%ATOM_PROJECT_DIR%"
    "%PYINSTALLER%" --onefile packaging\SpecDetect_Atom.spec --distpath "%ATOM_BUILD_DIR%"
    if errorlevel 1 (
        echo [ERROR] SGAtom build failed
        popd
        exit /b 1
    )
popd

REM ========================================
REM Step 4: Build SOAPProxy
REM ========================================
echo [4/9] Building SOAPProxy v%PROXY_VERSION% (onefile)...
pushd "%PROXY_PROJECT_DIR%"
    "%PYINSTALLER%" --onefile packaging\SOAPProxy.spec --distpath "%PROXY_BUILD_DIR%"
    if errorlevel 1 (
        echo [ERROR] SOAPProxy build failed
        popd
        exit /b 1
    )
popd

REM ========================================
REM Step 5: Build RMCPProxy
REM ========================================
echo [5/9] Building RMCPProxy v%RMCP_PROXY_VERSION% (onefile)...
pushd "%RMCP_PROXY_PROJECT_DIR%"
    "%PYINSTALLER%" --onefile packaging\rmcp_proxy.spec --distpath "%RMCP_BUILD_DIR%"
    if errorlevel 1 (
        echo [ERROR] RMCPProxy build failed
        popd
        exit /b 1
    )
popd

REM ========================================
REM Step 6: Build gen_license
REM ========================================
echo [6/10] Building gen_license.exe (onefile)...
pushd "%ATOM_PROJECT_DIR%"
    "%PYINSTALLER%" --onefile packaging\gen_license.spec --distpath "%GEN_LICENSE_BUILD_DIR%"
    if errorlevel 1 (
        echo [ERROR] gen_license build failed
        popd
        exit /b 1
    )
popd

REM ========================================
REM Step 7: Build gen_auth_code
REM ========================================
echo [7/10] Building gen_auth_code.exe (onefile)...
pushd "%ATOM_PROJECT_DIR%"
    "%PYINSTALLER%" --onefile packaging\gen_auth_code.spec --distpath "%GEN_AUTH_CODE_BUILD_DIR%"
    if errorlevel 1 (
        echo [ERROR] gen_auth_code build failed
        popd
        exit /b 1
    )
popd

REM ========================================
REM Copy files
REM ========================================
echo [8/10] Creating output structure...
mkdir "%OUTPUT_DIR%" 2>nul

echo [9/10] Copying executables...
copy /y "%ATOM_BUILD_DIR%\SGAtom_v%ATOM_VERSION%.exe" "%OUTPUT_DIR%\SGAtom_v%ATOM_VERSION%.exe"
copy /y "%PROXY_BUILD_DIR%\SOAPProxy_v%PROXY_VERSION%.exe" "%OUTPUT_DIR%\SOAPProxy_v%PROXY_VERSION%.exe"
copy /y "%RMCP_BUILD_DIR%\rmcp_proxy_v%RMCP_PROXY_VERSION%.exe" "%OUTPUT_DIR%\rmcp_proxy_v%RMCP_PROXY_VERSION%.exe"
copy /y "%GEN_LICENSE_BUILD_DIR%\gen_license.exe" "%OUTPUT_DIR%\"
copy /y "%GEN_AUTH_CODE_BUILD_DIR%\gen_auth_code_v%ATOM_VERSION%.exe" "%OUTPUT_DIR%\"

echo [10/10] Copying config files...
mkdir "%OUTPUT_DIR%\config" 2>nul
mkdir "%OUTPUT_DIR%\keys" 2>nul
if exist "%ATOM_PROJECT_DIR%\config\" xcopy /e /y /q "%ATOM_PROJECT_DIR%\config\*" "%OUTPUT_DIR%\config\"
if exist "%ATOM_PROJECT_DIR%\keys\private_key.pem" copy /y "%ATOM_PROJECT_DIR%\keys\private_key.pem" "%OUTPUT_DIR%\keys\"
if exist "%RMCP_PROXY_PROJECT_DIR%\config\rmcp_settings.json" copy /y "%RMCP_PROXY_PROJECT_DIR%\config\rmcp_settings.json" "%OUTPUT_DIR%\config\"

echo.
echo ========================================
echo   Build Complete!
echo ========================================
echo.
echo Output: %OUTPUT_DIR%\
echo   SGAtom_v%ATOM_VERSION%.exe
echo   SOAPProxy_v%PROXY_VERSION%.exe
echo   rmcp_proxy_v%RMCP_PROXY_VERSION%.exe
echo   gen_license.exe
echo   gen_auth_code_v%ATOM_VERSION%.exe
echo.
pause