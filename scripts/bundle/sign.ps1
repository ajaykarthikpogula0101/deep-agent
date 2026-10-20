# Code-sign the bundle so Windows SmartScreen stops warning on a download.
# Needs a code-signing certificate (Champions buys one: an OV/EV cert as a .pfx, or installed in the user store).
#   powershell -ExecutionPolicy Bypass -File scripts\bundle\sign.ps1 -Bundle C:\rb\Robin -Pfx C:\certs\champions.pfx
#   powershell -ExecutionPolicy Bypass -File scripts\bundle\sign.ps1 -Bundle C:\rb\Robin -Thumbprint <sha1>
# Signs Robin.exe and python\python.exe (Authenticode via signtool) and update.ps1 (PowerShell signature).
# .bat files cannot be signed; Robin.exe is the signed entry point. Run this BEFORE zipping.
param(
  [Parameter(Mandatory = $true)][string]$Bundle,
  [string]$Pfx = "",
  [string]$PfxPassword = "",
  [string]$Thumbprint = "",
  [string]$TimestampUrl = "http://timestamp.digicert.com"
)
$ErrorActionPreference = "Stop"
$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -match "x64" } | Sort-Object FullName -Descending | Select-Object -First 1
if (-not $signtool) { Write-Host "signtool.exe not found: install the Windows SDK (Signing Tools) first."; exit 2 }
if (-not $Pfx -and -not $Thumbprint) { Write-Host "Give -Pfx <file> (and -PfxPassword) or -Thumbprint <sha1>."; exit 2 }

$targets = @("Robin.exe", "python\python.exe") | ForEach-Object { Join-Path $Bundle $_ } | Where-Object { Test-Path $_ }
$certArgs = if ($Pfx) { @("/f", $Pfx) + $(if ($PfxPassword) { @("/p", $PfxPassword) } else { @() }) } else { @("/sha1", $Thumbprint) }
foreach ($t in $targets) {
  & $signtool.FullName sign /fd SHA256 /td SHA256 /tr $TimestampUrl @certArgs $t
  if ($LASTEXITCODE -ne 0) { Write-Host "signing failed for $t"; exit 1 }
}
$cert = if ($Pfx) { Get-PfxCertificate -FilePath $Pfx } else { Get-ChildItem Cert:\CurrentUser\My | Where-Object Thumbprint -eq $Thumbprint }
$ps1 = Join-Path $Bundle "update.ps1"
if (Test-Path $ps1) { Set-AuthenticodeSignature -FilePath $ps1 -Certificate $cert -TimestampServer $TimestampUrl | Out-Null }
Write-Host "Signed: $($targets -join ', '), update.ps1. Now zip the bundle."
