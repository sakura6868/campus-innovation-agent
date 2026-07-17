# expose.ps1 - Expose the campus innovation agent to the public internet
#             for free via Cloudflare quick tunnel (no login, no server, no card).
#
# Usage (run in project root campus-innovation-agent\ with PowerShell):
#   .\expose.ps1
#   .\expose.ps1 -Port 8011
#
# What it does:
#   1) Install cloudflared via winget if missing (first run may need admin)
#   2) Start uvicorn in background (app-dir=src, 127.0.0.1:<Port>)
#   3) Wait for local /health, then open Cloudflare tunnel
#   4) Print a public https://xxxx.trycloudflare.com URL; Ctrl+C stops everything
#
# Note: quick tunnel URL changes each run. For a fixed URL, create a free
#       Cloudflare account + named tunnel, then: cloudflared tunnel run <name>

param([int]$Port = 8000)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "cloudflared not found, installing via winget (admin may be required)..." -ForegroundColor Yellow
    winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

Write-Host "Starting agent (uvicorn :$Port) ..." -ForegroundColor Cyan
$job = Start-Process -FilePath ".\venv\Scripts\python.exe" `
    -ArgumentList "-m","uvicorn","api:app","--app-dir","src","--host","127.0.0.1","--port",$Port `
    -PassThru -WindowStyle Hidden

$ready = $false
for ($i = 0; $i -lt 25; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
}
if (-not $ready) {
    Write-Host "Local service failed to start. Check venv/deps." -ForegroundColor Red
    Stop-Process -Id $job.Id -Force -ErrorAction SilentlyContinue
    exit 1
}
Write-Host "Local service ready: http://127.0.0.1:$Port" -ForegroundColor Green

Write-Host "Opening Cloudflare tunnel (free, no login)..." -ForegroundColor Cyan
try {
    & cloudflared tunnel --url "http://localhost:$Port"
} finally {
    Write-Host "`nTunnel closed, stopping local service..." -ForegroundColor Yellow
    Stop-Process -Id $job.Id -Force -ErrorAction SilentlyContinue
}
