# Share the locally running assistant with someone else through a temporary public link (Cloudflare quick tunnel).
# Usage:  share.cmd            (from the project folder; the assistant must already be running on port 8080)
#         share.cmd -Port 8089
# The link lives only while this window stays open and the laptop is awake; close the window to take it down.
# Each run gets a new random *.trycloudflare.com address; a fixed address needs a Cloudflare or ngrok account.
param([int]$Port = 8080)
$ErrorActionPreference = "Continue"
$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf) { $cf = Get-ChildItem "C:\Program Files (x86)\cloudflared", "C:\Program Files\cloudflared", "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter cloudflared.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName }
if (-not $cf) { Write-Host "cloudflared is not installed. Run:  winget install --id Cloudflare.cloudflared" -ForegroundColor Red; exit 1 }
try { $h = Invoke-RestMethod "http://127.0.0.1:$Port/healthz" -TimeoutSec 3 } catch { Write-Host "Nothing is running on port $Port. Start the assistant first with run.cmd, then run share.cmd again." -ForegroundColor Red; exit 1 }
Write-Host "Assistant $($h.version) is running on port $Port. Opening the tunnel..." -ForegroundColor Yellow
$log = Join-Path $env:TEMP "deep-share-tunnel.log"
if (Test-Path $log) { Remove-Item $log -Force }
$p = Start-Process -FilePath $cf -ArgumentList "tunnel", "--url", "http://localhost:$Port", "--no-autoupdate" -RedirectStandardError $log -NoNewWindow -PassThru
$url = $null
foreach ($i in 1..40) { Start-Sleep -Seconds 1; if (Test-Path $log) { $m = Select-String -Path $log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1; if ($m) { $url = $m.Matches[0].Value; break } } }
if (-not $url) { Write-Host "The tunnel did not report a link in 40 s. Log: $log" -ForegroundColor Red; Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue; exit 1 }
Write-Host ""
Write-Host "Share these with the host (they work while this window stays open):" -ForegroundColor Green
Write-Host "  Chat (full panel):            $url/" -ForegroundColor Cyan
Write-Host "  As it looks on the website:   $url/site" -ForegroundColor Cyan
Write-Host "  Console (needs ADMIN_TOKEN):  $url/admin" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C or close this window to stop sharing." -ForegroundColor Yellow
try { Wait-Process -Id $p.Id } finally { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
