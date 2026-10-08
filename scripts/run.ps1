# One-command local start: Docker Desktop -> Postgres (pgvector) -> the assistant on http://localhost:8080
# Usage (from anywhere):   powershell -ExecutionPolicy Bypass -File "C:\Users\Ajay karthik pogula\deependhq-assistant\scripts\run.ps1"
# or double-click / run    run.cmd   in the project folder.
param([int]$Port = 8080)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$python = "D:\deependhq-venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

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
$env:OPENBLAS_NUM_THREADS = "1"
$env:OMP_NUM_THREADS = "1"
if (-not $env:FASTEMBED_CACHE_PATH -and (Test-Path "D:\hf-models")) { $env:FASTEMBED_CACHE_PATH = "D:\hf-models" }
Write-Host "Starting the assistant on http://localhost:$Port  (Ctrl+C to stop)" -ForegroundColor Green
& $python -m uvicorn app.main:app --port $Port
