@echo off
REM ============================================================
REM  setup_x86_env.bat
REM  One-shot installer for 32-bit Python 3.7.9 build dependencies.
REM
REM  Python path (hardcoded in build_config.bat):
REM    C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32\
REM
REM  Usage: just double-click.
REM
REM  Implementation note: uses goto labels instead of if (...) blocks
REM  to avoid cmd's bracket-parsing trap with echo lines that contain
REM  parentheses.
REM ============================================================

set "PYTHON_X86=C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32\python.exe"

if not exist "%PYTHON_X86%" goto FATAL_NO_PYTHON

echo ========================================
echo   setup_x86_env.bat
echo ========================================
echo   Python: %PYTHON_X86%
echo.

REM 1. Verify 32-bit
"%PYTHON_X86%" -c "import sys,struct; plat=sys.platform; bits=struct.calcsize('P')*8; sys.exit(0 if plat=='win32' and bits==32 else 1)"
if errorlevel 1 goto FATAL_NOT_32BIT
echo [OK] 32-bit confirmed

REM 2. Upgrade pip
echo.
echo [1/6] Upgrading pip ...
"%PYTHON_X86%" -m pip install --upgrade pip
if errorlevel 1 goto FATAL_PIP

REM 3. PyInstaller 4.10 (try official, fallback to 4.5.1)
echo.
echo [2/6] Installing PyInstaller 4.10 from PyPI official source ...
"%PYTHON_X86%" -m pip install --index-url https://pypi.org/simple/ pyinstaller==4.10
if errorlevel 1 goto WARN_PYI_OFFICIAL
echo [OK] PyInstaller 4.10 installed
goto SKIP_PYI_FALLBACK

:WARN_PYI_OFFICIAL
echo [WARN] Official source 4.10 failed, trying tuna 4.5.1 ...
"%PYTHON_X86%" -m pip install pyinstaller==4.5.1
if errorlevel 1 goto FATAL_PYI
echo [NOTE] Downgraded to PyInstaller 4.5.1

:SKIP_PYI_FALLBACK

REM 4. cryptography less than 36 for Win7
echo.
echo [3/6] Installing cryptography less than 36 for Win7 ...
"%PYTHON_X86%" -m pip install "cryptography<36"
if errorlevel 1 goto FATAL_CRYPTO

REM 5. cffi
echo.
echo [4/6] Installing cffi ...
"%PYTHON_X86%" -m pip install cffi
if errorlevel 1 goto FATAL_CFFI

REM 6. Cython less than 0.30
echo.
echo [5/6] Installing Cython less than 0.30 ...
"%PYTHON_X86%" -m pip install "Cython<0.30"
if errorlevel 1 goto FATAL_CYTHON

REM 7. pywin32
echo.
echo [6/6] Installing pywin32 ...
"%PYTHON_X86%" -m pip install pywin32
if errorlevel 1 goto WARN_PYWIN32
goto AFTER_PYWIN32

:WARN_PYWIN32
echo [WARN] pywin32 install failed - may affect win32 API usage

:AFTER_PYWIN32

echo.
echo ========================================
echo   Verify installed packages
echo ========================================
"%PYTHON_X86%" -m pip list 2>nul | findstr /i "pyinstaller cryptography cffi cython pywin32"
"%PYTHON_X86%" -c "import cryptography, cffi, Cython; print('[OK] cryptography, cffi, Cython importable')" 2>nul

echo.
echo ========================================
echo   Verify PyInstaller 32-bit bootloader
echo ========================================
if exist "%PYTHON_X86%\Lib\site-packages\PyInstaller\bootloader\Windows-32bit\run.exe" goto OK_BOOTLOADER
echo [FATAL] Windows-32bit run.exe MISSING
echo         Try:
echo             "%PYTHON_X86%" -m pip uninstall pyinstaller
echo             "%PYTHON_X86%" -m pip install pyinstaller==4.10
exit /b 1

:OK_BOOTLOADER
echo [OK] Windows-32bit bootloader exists

echo.
echo ========================================
echo   setup_x86_env.bat DONE
echo ========================================
echo.
echo Next:
echo   1. Prepare Win7 x86 Stub DLLs in runtime\win32\
echo      see docs BUILD_x86.md section 2.4
echo   2. Run build_x86.bat
echo.
exit /b 0

REM ============================================================
REM  Error labels
REM ============================================================

:FATAL_NO_PYTHON
echo [FATAL] x86 Python not found: %PYTHON_X86%
echo         Install Python 3.7.9 32-bit to that path first.
echo         https://www.python.org/ftp/python/3.7.9/python-3.7.9.exe
exit /b 1

:FATAL_NOT_32BIT
echo [FATAL] Not 32-bit Python
"%PYTHON_X86%" -c "import sys,struct; print('platform:', sys.platform); print('bits:', struct.calcsize('P')*8)"
exit /b 1

:FATAL_PIP
echo [FATAL] pip upgrade failed
exit /b 1

:FATAL_PYI
echo [FATAL] PyInstaller install failed -- tried both official 4.10 and tuna 4.5.1
exit /b 1

:FATAL_CRYPTO
echo [FATAL] cryptography install failed
exit /b 1

:FATAL_CFFI
echo [FATAL] cffi install failed
exit /b 1

:FATAL_CYTHON
echo [FATAL] Cython install failed
exit /b 1
