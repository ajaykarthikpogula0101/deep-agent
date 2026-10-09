# Share the locally running assistant with someone else through a temporary public link.
# Usage:  share.cmd            (from the project folder; the assistant must already be running on port 8080)
#         share.cmd -Port 8089
# Tries a Cloudflare quick tunnel first (needs cloudflared), then localhost.run over the built-in ssh (no install, no account).
# The link lives only while this window stays open and the laptop is awake; close the window to take it down.
# Each run gets a new random address; a fixed address needs a Cloudflare, ngrok or localhost.run account.
param([int]$Port = 8080, [switch]$Ssh)
$ErrorActionPreference = "Continue"
try { $h = Invoke-RestMethod "http://127.0.0.1:$Port/healthz" -TimeoutSec 3 } catch { Write-Host "Nothing is running on port $Port. Start the assistant first with run.cmd, then run share.cmd again." -ForegroundColor Red; exit 1 }
Write-Host "Assistant $($h.version) is running on port $Port. Opening the tunnel..." -ForegroundColor Yellow

function Show-Links($url) {
  Write-Host ""
  Write-Host "Share these with the host (they work while this window stays open):" -ForegroundColor Green
  Write-Host "  Chat (full panel):            $url/" -ForegroundColor Cyan
  Write-Host "  As it looks on the website:   $url/site" -ForegroundColor Cyan
  Write-Host "  Console (needs ADMIN_TOKEN):  $url/admin" -ForegroundColor Cyan
  Write-Host ""
  Write-Host "Press Ctrl+C or close this window to stop sharing." -ForegroundColor Yellow
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
# ---- 1. Cloudflare quick tunnel
$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf) { $cf = Get-ChildItem "C:\Program Files (x86)\cloudflared", "C:\Program Files\cloudflared" -Recurse -Filter cloudflared.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName }
if ($cf -and -not $Ssh) {
  $log = Join-Path $env:TEMP "deep-share-cf-$stamp.log"
  $p = Start-Process -FilePath $cf -ArgumentList "tunnel", "--url", "http://127.0.0.1:$Port", "--no-autoupdate" -RedirectStandardError $log -NoNewWindow -PassThru
  $url = $null
  foreach ($i in 1..30) { Start-Sleep -Seconds 1; if (Test-Path $log) { $m = Select-String -Path $log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches; if ($m) { $url = ($m.Matches | % { $_.Value } | ? { $_ -ne 'https://api.trycloudflare.com' } | Select-Object -First 1); if ($url) { break } } } }
  if ($url) { Show-Links $url; try { Wait-Process -Id $p.Id } finally { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }; exit 0 }
  Write-Host "Cloudflare quick tunnel did not answer (on this network its API request times out); using localhost.run instead." -ForegroundColor Yellow
  Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
}

# ---- 2. localhost.run over ssh (forward to 127.0.0.1, never 'localhost': Windows resolves that to IPv6 and uvicorn listens on IPv4)
$slog = Join-Path $env:TEMP "deep-share-ssh-$stamp.log"
$sp = Start-Process -FilePath ssh -ArgumentList "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30", "-o", "ExitOnForwardFailure=yes", "-R", "80:127.0.0.1:$Port", "nokey@localhost.run" -RedirectStandardOutput $slog -NoNewWindow -PassThru
$url = $null
foreach ($i in 1..60) { Start-Sleep -Seconds 1; if (Test-Path $slog) { $m = Select-String -Path $slog -Pattern 'https://[a-z0-9.-]+\.lhr\.life' -AllMatches; if ($m) { $url = $m.Matches[0].Value; break } } }
if (-not $url) { Write-Host "No tunnel could be opened. Log: $slog" -ForegroundColor Red; Stop-Process -Id $sp.Id -Force -ErrorAction SilentlyContinue; exit 1 }
Show-Links $url
try { Wait-Process -Id $sp.Id } finally { Stop-Process -Id $sp.Id -Force -ErrorAction SilentlyContinue }
