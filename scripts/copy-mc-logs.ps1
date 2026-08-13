#Requires -Version 5.1
# Run as the desktop user who owns FTB. Copies latest instance log to Public for agent/tools.
$ErrorActionPreference = 'Stop'
$instName = if ($args[0]) { $args[0] } else { 'ftb unstable 6' }
$inst = Join-Path $env:LOCALAPPDATA (".ftba\instances\$instName")
$dest = 'C:\Users\Public\mc-crash-dump'
$logD = Join-Path $dest 'logs'
$crD = Join-Path $dest 'crash-reports'
New-Item -ItemType Directory -Force -Path $logD, $crD | Out-Null
$srcLog = Join-Path $inst 'logs\latest.log'
if (-not (Test-Path -LiteralPath $srcLog)) { throw "Missing $srcLog" }
Copy-Item -LiteralPath $srcLog -Destination (Join-Path $logD 'latest.log') -Force
Copy-Item -LiteralPath $srcLog -Destination (Join-Path $logD ("latest-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))) -Force
Write-Host "OK logs -> $logD\latest.log"
$cr = Join-Path $inst 'crash-reports'
if (Test-Path -LiteralPath $cr) {
  Get-ChildItem -LiteralPath $cr -File | Sort-Object LastWriteTime -Descending | Select-Object -First 5 | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $crD $_.Name) -Force
    Write-Host "OK crash $($_.Name)"
  }
}
$dbg = Join-Path $inst 'logs\debug.log'
if (Test-Path -LiteralPath $dbg) {
  Copy-Item -LiteralPath $dbg -Destination (Join-Path $logD 'debug.log') -Force
  Write-Host "OK debug.log"
}
Write-Host "Done."
