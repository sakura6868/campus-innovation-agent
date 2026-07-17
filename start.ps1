param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
}

if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker compose up --build
    exit $LASTEXITCODE
}

if (-not (Test-Path "venv\Scripts\python.exe")) {
    python -m venv venv
    .\venv\Scripts\python.exe -m pip install -r requirements.txt
}

& .\venv\Scripts\python.exe -m uvicorn api:app --app-dir src --host 127.0.0.1 --port $Port
