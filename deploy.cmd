@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Update instance-mod-updater app code from a signed GitHub Release.
REM This tool updates mods on an existing FTB App instance. Not an official Feed the Beast product.
REM Leaves runtime, staged jars, reports, manifests, backups, and extra local files alone.
REM Usage (from C:\Users\Public\instance-mod-updater):
REM   deploy.cmd
REM   deploy.cmd --check-only
REM If you still have %PUBLIC%\ftb-instance-updater, move/copy the tree to %PUBLIC%\instance-mod-updater so work jars stay with the new name.

set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%"
set "PYTHONUTF8=1"
set "PY="

if exist "%ROOT%runtime\python\python.exe" set "PY=%ROOT%runtime\python\python.exe"
if not defined PY (
  where py >nul 2>&1 && (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY=py -3"
  )
)
if not defined PY (
  for /f "delims=" %%I in ('where python 2^>nul') do (
    echo %%I | findstr /I /C:"\WindowsApps\python" >nul
    if errorlevel 1 (
      if not defined PY set "PY=%%I"
    )
  )
)

if defined PY if exist "%ROOT%instance_mod_updater\self_update.py" (
  %PY% -m instance_mod_updater.self_update %*
  exit /b %ERRORLEVEL%
)

echo self-update: need Python 3.11+ and instance_mod_updater\self_update.py
echo A signed GitHub Release is required. Unsigned default-branch zips are not used.
echo   1. Unpack a signed release, or clone the repo
echo   2. Run: powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\fetch-runtime.ps1"
echo   3. Run deploy.cmd again
exit /b 1
