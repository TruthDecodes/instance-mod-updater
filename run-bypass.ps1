#Requires -Version 5.1
# Thin wrapper: same as run.ps1 but documents Bypass. Prefer run.cmd when policy blocks scripts.
# Usage if you insist on PowerShell:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\run-bypass.ps1 list
$ErrorActionPreference = 'Stop'
& "$PSScriptRoot\run.ps1" @args
exit $LASTEXITCODE
