# One action: virtualenv + requirements if missing -> python -m app.launch
#   (embedded Postgres + pgvector unless DATABASE_URL points at a reachable server)
# Usage: double-click run.cmd, or   powershell -ExecutionPolicy Bypass -File <project>\scripts\run.ps1 [-Port 8080] [-Docker]
#   -Docker keeps the previous path: Docker Desktop -> docker compose db -> uvicorn (existing deployments).
param([int]$Port = 8080, [switch]$Docker)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
# RUN_PYTHON and FASTEMBED_CACHE_PATH may be set in .env (a virtualenv or model cache outside the project)
$dotenv = @{}
if (Test-Path ".env") { Get-Content ".env" | ForEach-Object { if ($_ -match '^\s*(RUN_PYTHON|FASTEMBED_CACHE_PATH)\s*=\s*([^#]*)') { $dotenv[$Matches[1]] = $Matches[2].Trim() } } }
$python = @($dotenv["RUN_PYTHON"], ".venv\Scripts\python.exe") | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

# 0. virtualenv + runtime requirements (first run only; dev tools live in requirements-dev.txt)
if (-not $python) {
  $base = @("py -3.11", "py -3.12", "python") | Where-Object { try { & cmd /c "$_ --version" 2>$null | Out-Null; $LASTEXITCODE -eq 0 } catch { $false } } | Select-Object -First 1
  if (-not $base) { Write-Host "Python 3.11+ not found. Install it from python.org, then run this again." -ForegroundColor Red; exit 1 }
  Write-Host "Creating .venv with $base ..." -ForegroundColor Yellow
  & cmd /c "$base -m venv .venv"
  $python = ".venv\Scripts\python.exe"
}
& $python -c "import pgserver, fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installing runtime requirements ..." -ForegroundColor Yellow
  & $python -m pip install -q -r requirements.txt
  if ($LASTEXITCODE -ne 0) { Write-Host "pip install failed. Check your network and run this again." -ForegroundColor Red; exit 1 }
}
if (-not $env:FASTEMBED_CACHE_PATH -and $dotenv["FASTEMBED_CACHE_PATH"]) { $env:FASTEMBED_CACHE_PATH = $dotenv["FASTEMBED_CACHE_PATH"] }
$env:OPENBLAS_NUM_THREADS = "1"
$env:OMP_NUM_THREADS = "1"

if (-not $Docker) {
  & $python -m app.launch --port $Port
  exit $LASTEXITCODE
}

# -Docker: previous path, unchanged
# 1. Docker Desktop (per-user install; it stops when you sign out)
docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
  $exe = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\Docker Desktop.exe"
  if (-not (Test-Path $exe)) { $exe = "C:\Program Files\Docker\Docker\Docker Desktop.exe" }
  Write-Host "Starting Docker Desktop..." -ForegroundColor Yellow
  Start-Process -FilePath $exe
  $ok = $false
  foreach ($i in 1..80) { Start-Sleep -Seconds 3; docker info 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { $ok = $true; break } }
  if (-not $ok) { Write-Host "Docker did not come up in 4 minutes. Open Docker Desktop manually and run this again." -ForegroundColor Red; exit 1 }
}

# 2. Postgres
docker compose up -d db 2>&1 | Out-Null
$healthy = $false
foreach ($i in 1..40) { Start-Sleep -Seconds 2; $st = docker ps --filter "name=deependhq-assistant-db-1" --format "{{.Status}}"; if ($st -match "healthy") { $healthy = $true; break } }
if (-not $healthy) { Write-Host "Postgres is not healthy yet ($st). Check: docker compose logs db" -ForegroundColor Red; exit 1 }
Write-Host "Postgres ready." -ForegroundColor Green

# 3. the assistant
Write-Host "Starting the assistant on http://localhost:$Port  (Ctrl+C to stop)" -ForegroundColor Green
& $python -m uvicorn app.main:app --port $Port
