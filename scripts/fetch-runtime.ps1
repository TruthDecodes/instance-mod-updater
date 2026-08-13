#Requires -Version 5.1
<#
.SYNOPSIS
  Download Windows embeddable CPython into runtime\python for offline use.
  Prefer this over the Microsoft Store "python" stub.
#>
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Dest = Join-Path $Root 'runtime\python'
$Ver = '3.12.10'
$ZipName = "python-$Ver-embed-amd64.zip"
$Url = "https://www.python.org/ftp/python/$Ver/$ZipName"
$Tmp = Join-Path $env:TEMP $ZipName

Write-Host "Downloading $Url ..."
Invoke-WebRequest -Uri $Url -OutFile $Tmp -UseBasicParsing
if (Test-Path -LiteralPath $Dest) {
  Remove-Item -LiteralPath $Dest -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
Expand-Archive -LiteralPath $Tmp -DestinationPath $Dest -Force

# Allow importing the app package from repo root
$Pth = Get-ChildItem -LiteralPath $Dest -Filter 'python*._pth' | Select-Object -First 1
if (-not $Pth) { throw "python*._pth missing under $Dest" }
@(
  'python312.zip'
  '.'
  '..\..'
  'import site'
) | Set-Content -LiteralPath $Pth.FullName -Encoding ASCII

$Py = Join-Path $Dest 'python.exe'
& $Py --version
Write-Host "OK runtime at $Dest"
Write-Host "Run: .\run.cmd list"
