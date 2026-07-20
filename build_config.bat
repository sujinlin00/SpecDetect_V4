@echo off
REM ============================================================
REM  build_config.bat
REM  Centralized path and version setup for dual-arch builds.
REM
REM  CRITICAL implementation note: do NOT use "if (...) else (...)"
REM  multi-line blocks here. cmd.exe's preprocessor counts every
REM  "(" and ")" character (even inside quoted set values), so a
REM  path like "C:\Program Files (x86)\..." inside an if block
REM  breaks block parsing. Use goto dispatch instead.
REM
REM  Usage: call "%~dp0build_config.bat" x64
REM         call "%~dp0build_config.bat" x86
REM
REM  Exports: BUILD_ARCH, PYTHON_EXE, PYINSTALLER, VCVARS,
REM           RUNTIME_DIR, PYD_SUFFIX, OUTPUT_DIR, ROOT_DIR,
REM           ATOM_VERSION, PROXY_VERSION, RMCP_PROXY_VERSION
REM ============================================================

REM ---------- 1. Resolve BUILD_ARCH (single line) ----------
if /i "%~1"=="x64"      set "BUILD_ARCH=x64"
if /i "%~1"=="x86"      set "BUILD_ARCH=x86"
if /i "%~1"=="win64"    set "BUILD_ARCH=x64"
if /i "%~1"=="win32"    set "BUILD_ARCH=x86"
if "%BUILD_ARCH%"==""   set "BUILD_ARCH=x64"

if /i not "%BUILD_ARCH%"=="x64" if /i not "%BUILD_ARCH%"=="x86" goto FATAL_BAD_ARCH

REM ---------- 2. Common paths (no parens in values) ----------
set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"

REM VS install path contains parens -- set at top level only
set "VS_INSTALL=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"
set "PYTHON_X86_HOME=C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32"

REM ---------- 3. Arch dispatch via goto (NO if/else blocks) ----------
if /i "%BUILD_ARCH%"=="x86" goto DISPATCH_X86

REM x64 settings
set "PYTHON_EXE=C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37\python.exe"
set "PYINSTALLER=C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37\Scripts\pyinstaller.exe"
set "VCVARS=%VS_INSTALL%\VC\Auxiliary\Build\vcvars64.bat"
set "RUNTIME_DIR=%ROOT_DIR%\SpecDetect_UI_Atom\SpecDetect_Atom\runtime\win_amd64"
set "PYD_SUFFIX=cp37-win_amd64"
set "OUTPUT_DIR=%ROOT_DIR%\dist\win7-x64"
goto COMMON

:DISPATCH_X86
set "PYTHON_EXE=%PYTHON_X86_HOME%\python.exe"
set "PYINSTALLER=%PYTHON_X86_HOME%\Scripts\pyinstaller.exe"
set "VCVARS=%VS_INSTALL%\VC\Auxiliary\Build\vcvars32.bat"
set "RUNTIME_DIR=%ROOT_DIR%\SpecDetect_UI_Atom\SpecDetect_Atom\runtime\win32"
set "PYD_SUFFIX=cp37-win32"
set "OUTPUT_DIR=%ROOT_DIR%\dist\win7-x86"

:COMMON

REM ---------- 4. Read versions from get_version.py ----------
"%PYTHON_EXE%" "%ROOT_DIR%\get_version.py" "%ROOT_DIR%" >nul
if errorlevel 1 goto FATAL_NO_GETVERSION

for /f "usebackq tokens=1,2 delims==" %%A in ("%ROOT_DIR%\_version.env") do (
    set "%%A=%%B"
)

REM ---------- 5. Pre-flight checks ----------
if not exist "%PYTHON_EXE%" goto FATAL_NO_PYTHON
if not exist "%PYINSTALLER%" goto FATAL_NO_PYINSTALLER

REM Warn (not error) for missing vcvars
if not exist "%VCVARS%" goto WARN_NO_VCVARS
goto SKIP_VCVARS_WARN

:WARN_NO_VCVARS
echo [build_config] WARN: vcvars not found: %VCVARS%
echo             OK if you are not rebuilding Win7 Stub DLLs.
:SKIP_VCVARS_WARN

REM Warn for missing runtime dir
if not exist "%RUNTIME_DIR%" goto WARN_NO_RUNTIME
goto SKIP_RUNTIME_WARN

:WARN_NO_RUNTIME
echo [build_config] NOTE: runtime dir missing: %RUNTIME_DIR%
echo             For Win7 deployment prepare Stub DLLs here.
:SKIP_RUNTIME_WARN

REM ---------- 6. Prepare output dir ----------
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

echo [build_config] OK arch=%BUILD_ARCH% python="%PYTHON_EXE%" output="%OUTPUT_DIR%" pyd_suffix=%PYD_SUFFIX%
exit /b 0

REM ============================================================
REM  Error labels
REM ============================================================

:FATAL_BAD_ARCH
echo [build_config] FATAL: Unknown arch "%~1". Use x64 or x86.
exit /b 1

:FATAL_NO_GETVERSION
echo [build_config] FATAL: Cannot read versions with "%PYTHON_EXE%"
exit /b 1

:FATAL_NO_PYTHON
echo [build_config] FATAL: Python not found: %PYTHON_EXE%
echo             For arch %BUILD_ARCH% install Python first.
exit /b 1

:FATAL_NO_PYINSTALLER
echo [build_config] FATAL: PyInstaller not found: %PYINSTALLER%
echo             Run: "%PYTHON_EXE%" -m pip install pyinstaller==4.10
exit /b 1
