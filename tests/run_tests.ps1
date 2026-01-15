# Atlas Platform Test Suite Runner
# Runs all validation tests using the dedicated test virtual environment

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  ATLAS PLATFORM - TEST SUITE RUNNER" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

$VENV_PYTHON = "tests\venv\Scripts\python.exe"

# Check if venv exists
if (-not (Test-Path $VENV_PYTHON)) {
    Write-Host "ERROR: Test virtual environment not found!" -ForegroundColor Red
    Write-Host "Please run: python -m venv tests\venv" -ForegroundColor Yellow
    Write-Host "Then run: tests\venv\Scripts\python.exe -m pip install -r tests\requirements.txt" -ForegroundColor Yellow
    exit 1
}

# Check if dependencies are installed
Write-Host "Checking dependencies..." -ForegroundColor Yellow
$packages = & $VENV_PYTHON -m pip list 2>&1
if ($packages -notmatch "requests" -or $packages -notmatch "psycopg2-binary") {
    Write-Host "ERROR: Missing dependencies!" -ForegroundColor Red
    Write-Host "Please run: tests\venv\Scripts\python.exe -m pip install -r tests\requirements.txt" -ForegroundColor Yellow
    exit 1
}
Write-Host "✓ Dependencies OK`n" -ForegroundColor Green

# Check if Docker is running
Write-Host "Checking Docker services..." -ForegroundColor Yellow
$dockerCheck = docker ps 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Docker is not running!" -ForegroundColor Red
    Write-Host "Please start Docker and run: docker-compose -f infra/docker-compose.yml up -d" -ForegroundColor Yellow
    exit 1
}
Write-Host "✓ Docker running`n" -ForegroundColor Green

# Run tests
Write-Host "Executing test suite..." -ForegroundColor Cyan
Write-Host "This will take approximately 30-60 seconds`n" -ForegroundColor Gray

& $VENV_PYTHON tests\run_all_tests.py

$exitCode = $LASTEXITCODE

Write-Host "`n========================================" -ForegroundColor Cyan
if ($exitCode -eq 0) {
    Write-Host "  ✓ TESTS PASSED - GO FOR DEPLOYMENT" -ForegroundColor Green
} else {
    Write-Host "  ✗ TESTS FAILED - REVIEW RESULTS" -ForegroundColor Red
}
Write-Host "========================================`n" -ForegroundColor Cyan

exit $exitCode
