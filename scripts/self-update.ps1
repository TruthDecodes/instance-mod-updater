#Requires -Version 5.1
<#
.SYNOPSIS
  Refresh instance-mod-updater app code from GitHub.
  This tool updates mods on an existing FTB App instance. Not an official Feed the Beast product.

  Copies only launchers, scripts, and the Python package.
  Does not touch runtime\, staged jars, reports, manifests, backups,
  pack caches, or any extra files you added.

  Prefer deploy.cmd or run.cmd (those call this, or the Python module).
  Keep the allowlists here in sync with instance_mod_updater/self_update.py.
#>
[CmdletBinding()]
param(
  [string]$Root,
  [string]$Repo = 'TruthDecodes/instance-mod-updater',
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

# Prefer the Python implementation when the package is already present.
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
if ($py -and (Test-Path -LiteralPath $pyMod)) {
  $env:PYTHONPATH = $Root
  $env:PYTHONUTF8 = '1'
  $pass = @()
  if ($Root) { $pass += @('--root', $Root) }
  if ($Ref) { $pass += @('--ref', $Ref) }
  & $py -m instance_mod_updater.self_update @pass
  exit $LASTEXITCODE
}

# Bootstrap (no Python module yet): git fast-forward, else zip extract.
$AllowFiles = @(
  'run.cmd', 'run.ps1', 'run-bypass.ps1', 'deploy.cmd',
  'README.md', 'CHANGELOG.md', 'LICENSE', 'pyproject.toml',
  'SECURITY.md', 'CONTRIBUTING.md',
  '.gitignore', '.editorconfig'
)
$AllowDirs = @('instance_mod_updater', 'scripts', 'tests')
$SkipDirNames = @('__pycache__', '.git', 'runtime', '.serena')

function Copy-CodeTree([string]$SrcRoot) {
  foreach ($rel in $AllowFiles) {
    $src = Join-Path $SrcRoot $rel
    if (Test-Path -LiteralPath $src -PathType Leaf) {
      Copy-Item -LiteralPath $src -Destination (Join-Path $Root $rel) -Force
    }
  }
  foreach ($dir in $AllowDirs) {
    $srcDir = Join-Path $SrcRoot $dir
    if (-not (Test-Path -LiteralPath $srcDir)) { continue }
    Get-ChildItem -LiteralPath $srcDir -Recurse -File | ForEach-Object {
      if ($_.Extension -in @('.pyc', '.pyo')) { return }
      $rel = $_.FullName.Substring($srcDir.Length).TrimStart('\', '/')
      $parts = $rel -split '[\\/]'
      foreach ($part in $parts) {
        if ($SkipDirNames -contains $part) { return }
      }
      $dst = Join-Path $Root (Join-Path $dir $rel)
      $dstParent = Split-Path -Parent $dst
      if (-not (Test-Path -LiteralPath $dstParent)) {
        New-Item -ItemType Directory -Force -Path $dstParent | Out-Null
      }
      Copy-Item -LiteralPath $_.FullName -Destination $dst -Force
    }
  }
}

try {
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  $git = Get-Command git -ErrorAction SilentlyContinue
  $gitDir = Join-Path $Root '.git'
  if ($git -and (Test-Path -LiteralPath $gitDir)) {
    Push-Location $Root
    try {
      $old = (& git --no-pager rev-parse --short HEAD 2>$null)
      if ($LASTEXITCODE -eq 0) {
        & git --no-pager fetch --quiet origin 2>$null
        if ($LASTEXITCODE -ne 0) {
          Write-Upd "git fetch failed; using current code ($old)"
          exit 0
        }
        $branch = (& git --no-pager rev-parse --abbrev-ref HEAD).Trim()
        $upstream = $null
        $u = & git --no-pager rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null
        if ($LASTEXITCODE -eq 0 -and $u) { $upstream = $u.Trim() }
        if (-not $upstream -and $branch -and $branch -ne 'HEAD') {
          & git --no-pager show-ref --verify --quiet "refs/remotes/origin/$branch"
          if ($LASTEXITCODE -eq 0) { $upstream = "origin/$branch" }
        }
        if (-not $upstream) {
          $want = if ($Ref) { $Ref } else { 'main' }
          & git --no-pager show-ref --verify --quiet "refs/remotes/origin/$want"
          if ($LASTEXITCODE -eq 0) { $upstream = "origin/$want" }
        }
        if (-not $upstream) {
          Write-Upd "no upstream; using current code ($old)"
          exit 0
        }
        $behind = (& git --no-pager rev-list --count "HEAD..$upstream").Trim()
        if ($behind -eq '0') {
          Write-Upd "already current ($old)"
          exit 0
        }
        & git --no-pager merge --ff-only $upstream
        if ($LASTEXITCODE -ne 0) {
          Write-Upd "fast-forward failed; leaving code as-is ($old)"
          exit 0
        }
        $new = (& git --no-pager rev-parse --short HEAD).Trim()
        Write-Upd "updated $old -> $new"
        exit 0
      }
    } finally {
      Pop-Location
    }
  }

  $headers = @{
    'User-Agent' = 'instance-mod-updater-self-update'
    'Accept'     = 'application/vnd.github+json'
  }
  $want = $Ref
  if (-not $want) {
    try {
      $meta = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo" -Headers $headers -TimeoutSec 15
      $want = $meta.default_branch
    } catch {
      $want = 'main'
    }
  }
  $commit = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/commits/$want" -Headers $headers -TimeoutSec 15
  $remoteSha = [string]$commit.sha
  $shaFile = Join-Path $Root '.self-update-sha'
  $localSha = $null
  if (Test-Path -LiteralPath $shaFile) {
    $localSha = (Get-Content -LiteralPath $shaFile -TotalCount 1 -ErrorAction SilentlyContinue)
    if ($localSha) { $localSha = $localSha.Trim() }
  }
  if ($localSha -and $localSha -eq $remoteSha) {
    Write-Upd ("already current ({0})" -f $remoteSha.Substring(0, 7))
    exit 0
  }

  $tmp = Join-Path $env:TEMP ("instance-upd-" + [guid]::NewGuid().ToString('n'))
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  try {
    $zip = Join-Path $tmp 'src.zip'
    $zipUrl = "https://codeload.github.com/$Repo/zip/refs/heads/$want"
    Invoke-WebRequest -Uri $zipUrl -OutFile $zip -UseBasicParsing -TimeoutSec 60
    Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force
    $extracted = Get-ChildItem -LiteralPath $tmp -Directory | Select-Object -First 1
    if (-not $extracted) { throw 'zip had no folder' }
    Copy-CodeTree $extracted.FullName
    Set-Content -LiteralPath $shaFile -Value $remoteSha -Encoding ASCII
    $short = $remoteSha.Substring(0, 7)
    if ($localSha) {
      Write-Upd ("updated {0} -> {1}" -f $localSha.Substring(0, 7), $short)
    } else {
      Write-Upd "updated to $short"
    }
  } finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
  }
} catch {
  Write-Upd ("skipped ({0})" -f $_.Exception.Message)
  exit 0
}
exit 0
