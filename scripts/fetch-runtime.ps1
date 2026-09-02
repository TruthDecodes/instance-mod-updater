#Requires -Version 5.1
<#
.SYNOPSIS
  Download Windows embeddable CPython into runtime\python for offline use.
  Prefer this over the Microsoft Store "python" stub.

  The zip is hashed before extract. Pins are the official python.org MD5
  plus the SHA256 from that release's SPDX SBOM.
#>
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Dest = Join-Path $Root 'runtime\python'
# Pins must match scripts/embed_runtime.py (Release zip staging).
$Ver = '3.12.10'
$ZipName = "python-$Ver-embed-amd64.zip"
$Url = "https://www.python.org/ftp/python/$Ver/$ZipName"
$ExpectSha256 = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'
$ExpectMd5 = 'fe8ef205f2e9c3ba44d0cf9954e1abd3'
$Tmp = Join-Path $env:TEMP $ZipName

Write-Host "Downloading $Url ..."
Invoke-WebRequest -Uri $Url -OutFile $Tmp -UseBasicParsing

$sha = (Get-FileHash -LiteralPath $Tmp -Algorithm SHA256).Hash.ToLowerInvariant()
$md5 = (Get-FileHash -LiteralPath $Tmp -Algorithm MD5).Hash.ToLowerInvariant()
if ($sha -ne $ExpectSha256 -or $md5 -ne $ExpectMd5) {
  Remove-Item -LiteralPath $Tmp -Force -ErrorAction SilentlyContinue
  throw "Checksum mismatch for $ZipName (sha256=$sha md5=$md5). Refusing to extract."
}
Write-Host "Checksum OK ($ExpectSha256)"

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
Write-Host "Run: .\run.cmd"
