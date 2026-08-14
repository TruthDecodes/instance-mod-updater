#Requires -Version 5.1
<#
.SYNOPSIS
  Refresh instance-mod-updater app code from a signed GitHub Release.
  This tool updates mods on an existing FTB App instance. Not an official Feed the Beast product.

  Delegates to the Python verifier. Unsigned default-branch zips are not used.
  Copies only launchers, scripts, and the Python package.
  Does not touch runtime\, staged jars, reports, manifests, backups,
  pack caches, or any extra files you added.
#>
[CmdletBinding()]
param(
  [string]$Root,
  [string]$Ref
)

$ErrorActionPreference = 'Stop'
if (-not $Root) {
  $Root = Split-Path -Parent $PSScriptRoot
}
$Root = [System.IO.Path]::GetFullPath($Root)

function Write-Upd([string]$Message) {
  Write-Host "self-update: $Message"
}

$pyMod = Join-Path $Root 'instance_mod_updater\self_update.py'
$bundled = Join-Path $Root 'runtime\python\python.exe'
$py = $null
if (Test-Path -LiteralPath $bundled) { $py = $bundled }
if (-not $py) {
  foreach ($c in @('py', 'python')) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) { $py = [string]$cmd.Source; break }
  }
}
if (-not $py -or -not (Test-Path -LiteralPath $pyMod)) {
  Write-Upd "need Python 3.11+ and instance_mod_updater\self_update.py to verify a signed release."
  Write-Upd "run scripts\fetch-runtime.ps1, or unpack a signed GitHub Release zip, then retry."
  exit 1
}

$env:PYTHONPATH = $Root
$env:PYTHONUTF8 = '1'
$pass = @()
if ($Root) { $pass += @('--root', $Root) }
if ($Ref) { $pass += @('--ref', $Ref) }
& $py -m instance_mod_updater.self_update @pass
exit $LASTEXITCODE
