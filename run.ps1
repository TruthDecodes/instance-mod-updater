#Requires -Version 5.1
<#
.SYNOPSIS
  Launch instance-mod-updater on this PC (run as the Windows user that owns the FTB App instance).
  This tool updates mods on an existing FTB App instance. Not an official Feed the Beast product.
  If you still have %PUBLIC%\ftb-instance-updater, move/copy the tree to %PUBLIC%\instance-mod-updater so work jars stay with the new name.

.NOTES
  If you see "running scripts is disabled", either:
    .\run.cmd list
  or:
    powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 list
  Prefer run.cmd so you do not need to touch ExecutionPolicy permanently.

.EXAMPLE
  .\run.cmd list
  powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 check -i "ftb unstable 6" --pack-id 132 --version-id 100392
#>
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

$py = $null
# Bundled embeddable CPython first (no Store stub)
$bundled = Join-Path $Root 'runtime\python\python.exe'
if (Test-Path -LiteralPath $bundled) {
  $py = $bundled
}
if (-not $py) {
  foreach ($c in @('py', 'python', 'python3')) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    $src = [string]$cmd.Source
    if ($src -match 'WindowsApps\\python') { continue }  # Store alias stub
    try {
      $ver = & $cmd --version 2>&1 | Out-String
      if ($ver -match 'Python 3') {
        $py = $src
        break
      }
    } catch { }
  }
}
if (-not $py) {
  $guesses = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
    'C:\Python313\python.exe',
    'C:\Python312\python.exe'
  )
  foreach ($g in $guesses) {
    if (Test-Path -LiteralPath $g) { $py = $g; break }
  }
}
if (-not $py) {
  Write-Error @"
No usable Python found.
Expected bundled: $bundled
Or install python.org 3.11+ (Add to PATH). Disable Store app execution aliases for python.exe if needed.
"@
}

# Refresh app code first, then re-invoke so a rewritten run.ps1 is used.
# Work files / runtime are not touched. Skip: --no-self-update or INSTANCE_UPDATER_NO_SELF_UPDATE=1
# (FTB_NO_SELF_UPDATE=1 still works). Guard: INSTANCE_UPDATER_SELF_UPDATED (FTB_SELF_UPDATED still works).
$skipUpdate = ($env:INSTANCE_UPDATER_NO_SELF_UPDATE -eq '1') -or ($env:FTB_NO_SELF_UPDATE -eq '1') -or ($env:INSTANCE_UPDATER_SELF_UPDATED -eq '1') -or ($env:FTB_SELF_UPDATED -eq '1') -or ($args -contains '--no-self-update') -or ($args.Count -ge 1 -and $args[0] -eq 'self-update')
$selfUpdatePy = Join-Path $Root 'instance_mod_updater\self_update.py'
if (-not $skipUpdate -and (Test-Path -LiteralPath $selfUpdatePy)) {
  $env:PYTHONPATH = $Root
  $env:PYTHONUTF8 = '1'
  & $py -m instance_mod_updater.self_update
  $env:INSTANCE_UPDATER_SELF_UPDATED = '1'
  & $PSCommandPath @args
  exit $LASTEXITCODE
}

# Ensure package is importable without install
$env:PYTHONPATH = $Root
$env:PYTHONUTF8 = '1'
# Interactive console: prefer colored Python output (tool still respects NO_COLOR)
if (-not $env:NO_COLOR -and -not $env:FORCE_COLOR) {
  $env:FORCE_COLOR = '1'
}

if ($env:NO_COLOR) {
  Write-Host "Python: $py"
  Write-Host "Root:   $Root"
  Write-Host "Args:   $args"
} else {
  Write-Host -NoNewline -ForegroundColor Cyan 'Python:  '
  Write-Host $py
  Write-Host -NoNewline -ForegroundColor Cyan 'Root:    '
  Write-Host $Root
  Write-Host -NoNewline -ForegroundColor Cyan 'Args:    '
  Write-Host "$args"
}

& $py -m instance_mod_updater @args
exit $LASTEXITCODE
