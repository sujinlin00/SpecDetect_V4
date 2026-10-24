@echo off
rem ============================================================================
rem  SGAtom / SpecDetect_Atom  -  "Unable to get system disk serial" diagnostic
rem
rem  Usage :  diag_disk_serial.bat [SGAtom_DIR]
rem           e.g.  diag_disk_serial.bat D:\SGAtom_v1.7.8
rem
rem  Output:  disk_serial_diag.txt  (next to this script, or %TEMP%\)
rem            Send that file back to engineering.
rem
rem  Run as Administrator if possible (some disk serial fields need elevation).
rem  NOTE: this file is intentionally pure ASCII so it runs on any locale/codepage.
rem ============================================================================
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "SGATOM_DIR=%~1"
if "%SGATOM_DIR%"=="" set "SGATOM_DIR=D:\SGAtom_v1.7.8"

rem ---------- log file ----------
set "LOG=%SCRIPT_DIR%disk_serial_diag.txt"
echo.>"%LOG%" 2>nul
if not exist "%LOG%" set "LOG=%TEMP%\disk_serial_diag.txt"
echo.>"%LOG%" 2>nul

echo(
echo ================================================================
echo   SGAtom disk-serial diagnostic
echo   target dir : %SGATOM_DIR%
echo   log file   : %LOG%
echo ================================================================
echo(

net session >nul 2>&1
if errorlevel 1 (
  echo [WARN] Not running as Administrator. Some disk serial fields may be empty.
  echo [WARN] Right-click the .bat - Run as administrator - for complete results.
  echo(
)

rem ============================== 01 environment ==============================
echo [01/16] environment .......................... DONE
echo ================================================================>>"%LOG%"
echo === 01 ENVIRONMENT ===>>"%LOG%"
echo date/time : %DATE% %TIME%>>"%LOG%"
echo host      : %COMPUTERNAME%>>"%LOG%"
echo user      : %USERNAME%>>"%LOG%"
echo cwd       : %CD%>>"%LOG%"
echo.>>"%LOG%"
ver>>"%LOG%" 2>&1
wmic os get Caption,Version,BuildNumber,OSArchitecture>>"%LOG%" 2>&1
echo.>>"%LOG%"

rem ============================== 02 tools ==============================
echo [02/16] tool availability .................... DONE
echo === 02 TOOL AVAILABILITY ===>>"%LOG%"
where wmic>>"%LOG%" 2>&1
if errorlevel 1 (echo WMIC_PRESENT=NO>>"%LOG%") else (echo WMIC_PRESENT=YES>>"%LOG%")
where powershell>>"%LOG%" 2>&1
if errorlevel 1 (echo PWSH5_PRESENT=NO>>"%LOG%") else (echo PWSH5_PRESENT=YES>>"%LOG%")
where pwsh>>"%LOG%" 2>&1
if errorlevel 1 (echo PWSH7_PRESENT=NO>>"%LOG%") else (echo PWSH7_PRESENT=YES>>"%LOG%")
powershell -NoProfile -Command "$PSVersionTable.PSVersion.ToString()">>"%LOG%" 2>&1
echo.>>"%LOG%"

rem ============================== 03 repro code bug A ==============================
echo [03/16] repro: code's real WMIC call ........... DONE
echo === 03 REPRO - EXACT WMIC CALL MADE BY hardware.py ===>>"%LOG%"
echo (this is what src/license/hardware.py runs: 'wmic' 'diskdrive where Index=0' 'get' 'serialnumber')>>"%LOG%"
wmic "diskdrive where Index=0" get serialnumber>>"%LOG%" 2>&1
echo.>>"%LOG%"

rem ============================== 04 wmic correct ==============================
echo [04/16] wmic with correct arguments ............ DONE
echo === 04 WMIC (correct arg splitting) ===>>"%LOG%"
wmic diskdrive where Index=0 get serialnumber>>"%LOG%" 2>&1
echo.>>"%LOG%"
wmic diskdrive get Index,Model,SerialNumber,Size>>"%LOG%" 2>&1
echo.>>"%LOG%"

rem ============================== 05 repro code path B ==============================
echo [05/16] repro: code's PowerShell fallback ...... DONE
echo === 05 REPRO - POWERSHELL FALLBACK USED BY hardware.py ===>>"%LOG%"
echo (hardware.py runs: (Get-WmiObject Win32_diskdrive).serialnumber)>>"%LOG%"
powershell -NoProfile -Command "(Get-WmiObject Win32_diskdrive).serialnumber">>"%LOG%" 2>&1
echo.>>"%LOG%"

rem ============================== 06 markers ==============================
echo [06/16] empty / non-empty markers .............. DONE
echo === 06 MACHINE READABLE MARKERS ===>>"%LOG%"
powershell -NoProfile -Command "if ((Get-WmiObject Win32_diskdrive).serialnumber) { 'PS_WMI_DISK=NONEMPTY' } else { 'PS_WMI_DISK=EMPTY' }">>"%LOG%" 2>&1
powershell -NoProfile -Command "if ((Get-CimInstance Win32_DiskDrive).SerialNumber) { 'PS_CIM_DISK=NONEMPTY' } else { 'PS_CIM_DISK=EMPTY' }">>"%LOG%" 2>&1
powershell -NoProfile -Command "if ((Get-WmiObject Win32_diskdrive) -eq $null) { 'PS_WMI_CLASS=NULL' } else { 'PS_WMI_CLASS=OK' }">>"%LOG%" 2>&1
powershell -NoProfile -Command "if ((Get-CimInstance Win32_DiskDrive) -eq $null) { 'PS_CIM_CLASS=NULL' } else { 'PS_CIM_CLASS=OK' }">>"%LOG%" 2>&1
powershell -NoProfile -Command "$v=@(Get-WmiObject Win32_diskdrive).serialnumber; 'DISK_SERIAL_COUNT=' + $v.Count; if($v.Count -gt 1){'PS_WMI_MULTI_DISK=YES'}else{'PS_WMI_MULTI_DISK=NO'}">>"%LOG%" 2>&1
echo.>>"%LOG%"

rem ============================== 07/08 disk detail ==============================
echo [07/16] disk detail (CIM) ..................... DONE
echo === 07 DISK DETAIL - Get-CimInstance Win32_DiskDrive ===>>"%LOG%"
powershell -NoProfile -Command "Get-CimInstance Win32_DiskDrive | Select-Object Index,Model,SerialNumber,Size,InterfaceType,PNPDeviceID | Format-List">>"%LOG%" 2>&1
echo.>>"%LOG%"

echo [08/16] disk detail (WMI) ...................... DONE
echo === 08 DISK DETAIL - Get-WmiObject Win32_DiskDrive ===>>"%LOG%"
powershell -NoProfile -Command "Get-WmiObject Win32_DiskDrive | Select-Object Index,Model,SerialNumber,Size | Format-List">>"%LOG%" 2>&1
echo.>>"%LOG%"

rem ============================== 09 physical disk ==============================
echo [09/16] physical disk (Storage namespace) ....... DONE
echo === 09 Get-PhysicalDisk ===>>"%LOG%"
powershell -NoProfile -Command "Get-PhysicalDisk | Select-Object DeviceId,FriendlyName,SerialNumber,UniqueId,BusType | Format-List">>"%LOG%" 2>&1
echo.>>"%LOG%"

rem ============================== 10 partitions ==============================
echo [10/16] partition / drive letter map ........... DONE
echo === 10 PARTITIONS -> DRIVE LETTERS ===>>"%LOG%"
powershell -NoProfile -Command "Get-Partition | Select-Object DiskNumber,PartitionNumber,DriveLetter,Type,Size | Format-Table -AutoSize">>"%LOG%" 2>&1
echo.>>"%LOG%"

rem ============================== 11 which disk is the system disk ==============================
echo [11/16] real system disk (SystemDrive) ......... DONE
echo === 11 SYSTEM DISK (resolved via SystemDrive, NOT Index=0) ===>>"%LOG%"
powershell -NoProfile -Command "'SystemDrive=' + $env:SystemDrive">>"%LOG%" 2>&1
powershell -NoProfile -Command "$d=$env:SystemDrive.TrimEnd(':'); Get-Partition -DriveLetter $d | Get-Disk | Select-Object Number,Model,SerialNumber | Format-List">>"%LOG%" 2>&1
powershell -NoProfile -Command "$d=$env:SystemDrive.TrimEnd(':'); $s=(Get-Partition -DriveLetter $d -ErrorAction SilentlyContinue | Get-Disk -ErrorAction SilentlyContinue).SerialNumber; if($s) { 'SYS_DISK=' + $s.Trim() } else { 'SYS_DISK=EMPTY' }">>"%LOG%" 2>&1
powershell -NoProfile -Command "$d=$env:SystemDrive.TrimEnd(':'); $n=(Get-Partition -DriveLetter $d -ErrorAction SilentlyContinue | Get-Disk -ErrorAction SilentlyContinue).Number; if($n -ne $null) { 'SYS_DISK_INDEX=' + $n } else { 'SYS_DISK_INDEX=UNKNOWN' }">>"%LOG%" 2>&1
echo.>>"%LOG%"

rem ============================== 12 wmi service ==============================
echo [12/16] WMI service status .................... DONE
echo === 12 WMI SERVICE / PROVIDERS ===>>"%LOG%"
powershell -NoProfile -Command "Get-Service Winmgmt | Select-Object Name,Status,StartType | Format-List">>"%LOG%" 2>&1
powershell -NoProfile -Command "Get-Service -Name 'W32Time','WinDefend','Sense' -ErrorAction SilentlyContinue | Select-Object Name,Status | Format-Table -AutoSize">>"%LOG%" 2>&1
echo.>>"%LOG%"

rem ============================== 13 timing vs 10s timeout ==============================
echo [13/16] WMI query timing (code timeout = 10s) .. DONE
echo === 13 TIMING (code uses a 10s timeout - compare!) ===>>"%LOG%"
powershell -NoProfile -Command "'WMI_QUERY_MS=' + [int](Measure-Command { Get-WmiObject Win32_diskdrive | Out-Null }).TotalMilliseconds">>"%LOG%" 2>&1
powershell -NoProfile -Command "'CIM_QUERY_MS=' + [int](Measure-Command { Get-CimInstance Win32_DiskDrive | Out-Null }).TotalMilliseconds">>"%LOG%" 2>&1
powershell -NoProfile -Command "'PS_STARTUP_MS=' + [int](Measure-Command { powershell -NoProfile -Command exit }).TotalMilliseconds">>"%LOG%" 2>&1
echo.>>"%LOG%"

rem ============================== 14 volume serial ==============================
echo [14/16] volume serial (fallback id) ............ DONE
echo === 14 VOLUME SERIAL (alternative stable id) ===>>"%LOG%"
wmic logicaldisk get DeviceID,VolumeSerialNumber,FileSystem>>"%LOG%" 2>&1
vol %SystemDrive%>>"%LOG%" 2>&1
echo.>>"%LOG%"

rem ============================== 15 app files ==============================
echo [15/16] SGAtom files and app log .............. DONE
echo === 15 SGATOM DIR ===>>"%LOG%"
dir "%SGATOM_DIR%">>"%LOG%" 2>&1
dir "%SGATOM_DIR%\config">>"%LOG%" 2>&1
dir "%SGATOM_DIR%\config\license.dat">>"%LOG%" 2>&1
echo.>>"%LOG%"
echo === 16 APP LOG TAIL (last 150 lines of each .log) ===>>"%LOG%"
if exist "%SGATOM_DIR%\logs\*.log" (
  for %%F in ("%SGATOM_DIR%\logs\*.log") do (
    echo ---- %%~nxF ---->>"%LOG%"
    powershell -NoProfile -Command "Get-Content -LiteralPath '%%~fF' -Tail 150 -ErrorAction SilentlyContinue">>"%LOG%" 2>&1
    echo.>>"%LOG%"
  )
) else (
  echo (no *.log found in %SGATOM_DIR%\logs\)>>"%LOG%"
)
echo === 16b SEARCH APP LOG FOR THE DISK-SERIAL WARNING ===>>"%LOG%"
powershell -NoProfile -Command "$p=-join (0x65E0,0x6CD5,0x83B7,0x53D6,0x7CFB,0x7EDF,0x76D8,0x5E8F,0x5217,0x53F7 | ForEach-Object {[char]$_}); $m=Get-ChildItem -Path '%SGATOM_DIR%\logs\*.log' -ErrorAction SilentlyContinue | Select-String -Pattern $p -Encoding Default; if($m){ $m | ForEach-Object { $_.Filename + ':' + $_.LineNumber + ': ' + $_.Line }; 'DISK_WARN_FOUND=YES' } else { 'DISK_WARN_FOUND=NO' }">>"%LOG%" 2>&1
echo.>>"%LOG%"

rem ============================== summary ==============================
echo(
echo ================================================================
echo  SUMMARY
echo ================================================================
findstr /C:"WMIC_PRESENT" /C:"PWSH5_PRESENT" /C:"PS_WMI_DISK" /C:"PS_CIM_DISK" /C:"PS_WMI_CLASS" /C:"PS_CIM_CLASS" /C:"DISK_SERIAL_COUNT" /C:"PS_WMI_MULTI_DISK" /C:"SYS_DISK" /C:"WMI_QUERY_MS" /C:"CIM_QUERY_MS" /C:"PS_STARTUP_MS" /C:"DISK_WARN_FOUND" "%LOG%"
echo(
echo Full log: %LOG%
echo Please send that file back to engineering.
echo(
pause
exit /b 0
