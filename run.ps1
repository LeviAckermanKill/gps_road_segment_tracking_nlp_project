<# GPS Map Matching — Quick Start Script #>
param(
    [switch]$GenerateData,
    [switch]$Test,
    [switch]$Serve
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

# Activate or create virtual environment
$VenvPath = Join-Path $ProjectRoot ".venv"
$ActivateScript = Join-Path $VenvPath "Scripts\Activate.ps1"

if (-not (Test-Path $VenvPath)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    py -3 -m venv $VenvPath
}

if (Test-Path $ActivateScript) {
    . $ActivateScript
} else {
    Write-Host "ERROR: Cannot find venv activation script at $ActivateScript" -ForegroundColor Red
    exit 1
}

# Install dependencies
Write-Host "Installing dependencies..." -ForegroundColor Cyan
python -m pip install --upgrade pip --quiet
python -m pip install -r (Join-Path $ProjectRoot "backend\requirements.txt") --quiet

if ($GenerateData -or -not (Test-Path (Join-Path $ProjectRoot "data\sample_trace_clean.csv"))) {
    Write-Host "Generating test data..." -ForegroundColor Cyan
    python (Join-Path $ProjectRoot "scripts\generate_test_data.py")
}

if ($Test) {
    Write-Host "Running tests..." -ForegroundColor Cyan
    python -m pytest -v
    exit $LASTEXITCODE
}

if ($Serve -or (-not $Test -and -not $GenerateData)) {
    Write-Host ""
    Write-Host "Starting GPS Map Matching server..." -ForegroundColor Green
    Write-Host "Open http://127.0.0.1:5000 in your browser" -ForegroundColor Yellow
    Write-Host ""
    python -m backend.app
}
