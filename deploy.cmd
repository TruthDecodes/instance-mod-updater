@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Update instance-mod-updater app code under this folder from GitHub.
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
set "PS1=%ROOT%scripts\self-update.ps1"

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

if not exist "%ROOT%scripts" mkdir "%ROOT%scripts"
if not exist "%PS1%" (
  echo self-update: downloading updater...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/TruthDecodes/instance-mod-updater/main/scripts/self-update.ps1' -OutFile '%PS1%' -UseBasicParsing"
  if errorlevel 1 (
    echo self-update: could not download scripts\self-update.ps1
    echo Copy that file from the repo into this folder and run deploy.cmd again.
    exit /b 1
  )
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
exit /b %ERRORLEVEL%
