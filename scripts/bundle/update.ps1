# Robin updater (Windows). Double-click "Update Robin.bat" or run: powershell -ExecutionPolicy Bypass -File update.ps1 [-Check]
#
# Reads UPDATE_URL from .env (a manifest.json published next to the zip), compares its version with the local
# VERSION file, downloads the zip, verifies its SHA-256, and swaps the program folders.
# Keeps: .env, data\ (database + chat history), uploads\. Replaces: app, static, python, models, docs, VERSION,
# README.txt, Start Robin.bat, Update Robin.bat, update.ps1, Robin.exe, requirements.txt.
# Robin must be closed first (refuses while the server port is in use). A Postgres left behind by a closed
# window is stopped cleanly before the swap. The swap renames the old folders aside first, so a locked file
# can never leave the install half-replaced; leftovers are removed on the next run.
param([switch]$Check, [string]$Manifest = "")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Read-Env([string]$key) {
  if (-not (Test-Path ".env")) { return "" }
  foreach ($line in Get-Content ".env") { if ($line -match "^\s*$key\s*=\s*([^#]*)") { return $Matches[1].Trim() } }
  return ""
}
function Stop-EmbeddedPostgres {
  # Best effort: a Postgres left behind by a closed window holds files in python\ open. Stop it cleanly
  # (pg_ctl), then by PID from postmaster.pid, then by binary path under this install. Never aborts the update.
  try {
    $dataDir = Join-Path $root "data\pg"
    $pidFile = Join-Path $dataDir "postmaster.pid"
    $pgctl = Get-ChildItem -Path (Join-Path $root "python") -Recurse -Filter pg_ctl.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pgctl -and (Test-Path $pidFile)) {
      & $pgctl.FullName stop -D $dataDir -m fast -w -t 20 2>$null | Out-Null
    }
    $first = ""
    if (Test-Path $pidFile) { $first = [string](Get-Content $pidFile -TotalCount 1 -ErrorAction SilentlyContinue) }
    if ($first -and $first.Trim() -match '^\d+$' -and (Get-Process -Id ([int]$first.Trim()) -ErrorAction SilentlyContinue)) {
      Write-Host "Stopping the database left running by a closed window ..."
      Stop-Process -Id ([int]$first.Trim()) -Force -ErrorAction SilentlyContinue
    }
    $mine = Join-Path $root "python"
    Get-Process postgres -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($mine, [System.StringComparison]::OrdinalIgnoreCase) } |
      Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
  } catch {
    Write-Host "Could not stop a leftover database cleanly: $($_.Exception.Message). Continuing."
  }
}
function Remove-Leftovers {
  Get-ChildItem -Path $root -Filter "*.old-*" -ErrorAction SilentlyContinue | ForEach-Object {
    Remove-Item -Recurse -Force $_.FullName -ErrorAction SilentlyContinue
  }
}

Remove-Leftovers
$url = if ($Manifest) { $Manifest } else { Read-Env "UPDATE_URL" }
if (-not $url) { Write-Host "No UPDATE_URL in .env: this install does not know where updates are published."; exit 2 }
$local = if (Test-Path "VERSION") { (Get-Content "VERSION" -TotalCount 1).Trim() } else { "0" }

Write-Host "Checking $url ..."
$m = Invoke-RestMethod -Uri $url -TimeoutSec 30
if (-not $m.version -or -not $m.zip -or -not $m.sha256) { Write-Host "The manifest is missing version, zip or sha256."; exit 2 }
Write-Host "Installed: $local   Available: $($m.version)"
if ($m.version -eq $local) { Write-Host "Robin is up to date."; exit 0 }
if ($Check) { Write-Host "An update is available. Run Update Robin.bat to install it."; exit 3 }

$port = Read-Env "PORT"; if (-not $port) { $port = "8080" }
if (Get-NetTCPConnection -LocalPort ([int]$port) -State Listen -ErrorAction SilentlyContinue) {
  Write-Host "Robin is running on port $port. Close the Robin window first, then run the update again."; exit 4
}
Stop-EmbeddedPostgres

$zipUrl = if ($m.zip -match '^https?://') { $m.zip } else { ($url -replace '[^/]+$', '') + $m.zip }
$tmp = Join-Path $env:TEMP ("robin-update-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
$zip = Join-Path $tmp "robin.zip"
Write-Host "Downloading $zipUrl ..."
Invoke-WebRequest -Uri $zipUrl -OutFile $zip -TimeoutSec 600
$hash = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLower()
if ($hash -ne $m.sha256.ToLower()) { Write-Host "Download did not verify (sha256 mismatch). Nothing was changed."; Remove-Item -Recurse -Force $tmp; exit 5 }
Write-Host "Verified. Unpacking ..."
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$new = Get-ChildItem -Path $tmp -Directory | Where-Object { Test-Path (Join-Path $_.FullName "app") } | Select-Object -First 1
if (-not $new) { Write-Host "The zip does not look like a Robin bundle. Nothing was changed."; Remove-Item -Recurse -Force $tmp; exit 5 }

$stamp = Get-Date -Format "yyyyMMddHHmmss"
$replace = @("app", "static", "python", "models", "docs", "VERSION", "README.txt", "Start Robin.bat", "Update Robin.bat", "update.ps1", "Robin.exe", "requirements.txt")
foreach ($item in $replace) {
  $src = Join-Path $new.FullName $item
  if (-not (Test-Path $src)) { continue }
  $dst = Join-Path $root $item
  if (Test-Path $dst) {
    $aside = "$dst.old-$stamp"
    Move-Item -Path $dst -Destination $aside   # rename succeeds even if a file inside is open; delete would not
  }
  Move-Item -Path $src -Destination $dst
}
Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
Remove-Leftovers
Start-Sleep -Seconds 3   # a just-stopped process may still hold a file for a moment
Remove-Leftovers         # anything still locked is removed by the next run
if (-not (Test-Path (Join-Path $root "python\python.exe"))) { Write-Host "Update finished but python\python.exe is missing; re-run the update."; exit 6 }
Write-Host "Updated to $($m.version). Your settings (.env) and data folder were kept. Start Robin as usual."
exit 0
