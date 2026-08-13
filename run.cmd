@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%"
set "PYTHONUTF8=1"
set "PY="

REM 1) Bundled embeddable CPython (preferred; no Store stub)
if exist "%ROOT%runtime\python\python.exe" (
  set "PY=%ROOT%runtime\python\python.exe"
  goto :found
)

REM 2) py launcher
where py >nul 2>&1 && (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
  if not errorlevel 1 (
    set "PY=py -3"
    goto :found
  )
)

REM 3) Real python on PATH — reject WindowsApps Store alias
for /f "delims=" %%I in ('where python 2^>nul') do (
  echo %%I | findstr /I /C:"\WindowsApps\python" >nul
  if errorlevel 1 (
    "%%I" -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
    if not errorlevel 1 (
      set "PY=%%I"
      goto :found
    )
  )
)

echo.
echo No usable Python found.
echo   1. Run:  powershell -NoProfile -ExecutionPolicy Bypass -File "%%~dp0scripts\fetch-runtime.ps1"
echo   2. Or install python.org 3.11+ and tick "Add python.exe to PATH".
echo Disable Settings ^> Apps ^> Advanced ^> App execution aliases for python.exe if the Store stub steals the name.
echo.
exit /b 1

:found
REM Interactive console: prefer colored Python output (tool still respects NO_COLOR).
if not defined NO_COLOR if not defined FORCE_COLOR set "FORCE_COLOR=1"

REM Refresh app code first, then re-invoke this file so a new run.cmd is used.
REM Work files / runtime are not touched. Skip: --no-self-update or INSTANCE_UPDATER_NO_SELF_UPDATE=1
REM (FTB_NO_SELF_UPDATE=1 still works). In-process guard: INSTANCE_UPDATER_SELF_UPDATED (FTB_SELF_UPDATED still works).
if /I "%INSTANCE_UPDATER_NO_SELF_UPDATE%"=="1" goto :run
if /I "%FTB_NO_SELF_UPDATE%"=="1" goto :run
if defined INSTANCE_UPDATER_SELF_UPDATED goto :run
if defined FTB_SELF_UPDATED goto :run
if /I "%~1"=="self-update" goto :run
echo %*| findstr /I /C:"--no-self-update" >nul && goto :run
if exist "%ROOT%instance_mod_updater\self_update.py" (
  %PY% -m instance_mod_updater.self_update
  set "INSTANCE_UPDATER_SELF_UPDATED=1"
  "%~f0" %*
  exit /b %ERRORLEVEL%
)

:run
REM Bright cyan labels for the launcher banner (ESC = char 27). VT hosts: Windows Terminal / modern conhost.
for /f %%E in ('echo prompt $E^| cmd') do set "ESC=%%E"
if defined NO_COLOR (
  echo Python: %PY%
  echo Root:   %CD%
  echo Args:   %*
) else (
  echo %ESC%[96mPython:%ESC%[0m  %PY%
  echo %ESC%[96mRoot:%ESC%[0m    %CD%
  echo %ESC%[96mArgs:%ESC%[0m    %*
)

%PY% -m instance_mod_updater %*
exit /b %ERRORLEVEL%
