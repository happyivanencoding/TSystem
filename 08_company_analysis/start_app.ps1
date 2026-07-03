# Check if Python is installed
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Python is not installed or not in PATH." -ForegroundColor Red
    exit 1
}

# Check if Node is installed
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Node.js is not installed or not in PATH." -ForegroundColor Red
    exit 1
}

# Ensure we are in the script's directory
Set-Location $PSScriptRoot

Write-Host "Starting Company Analysis App..." -ForegroundColor Cyan

# 1. Setup Backend
Write-Host "Setting up Backend..." -ForegroundColor Yellow
cd backend
if (-not (Test-Path "venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv venv
}

# Activate to install reqs
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Use relative path string for python executable
$venvPython = ".\venv\Scripts\python.exe"
Write-Host "Starting Backend Server..."
Start-Process -FilePath $venvPython -ArgumentList "-m uvicorn main:app --reload --port 8000" -NoNewWindow
cd ..

# 2. Setup Frontend
Write-Host "Setting up Frontend..." -ForegroundColor Yellow
cd frontend
if (-not (Test-Path "node_modules")) {
    Write-Host "Installing Node dependencies..."
    npm install
}

# Start Frontend
Write-Host "Starting Frontend..." -ForegroundColor Green
if ($IsWindows -or $env:OS -match "Windows_NT") {
    Start-Process -FilePath "npm.cmd" -ArgumentList "run dev" -NoNewWindow
} else {
    Start-Process -FilePath "npm" -ArgumentList "run dev" -NoNewWindow
}

# Open Browser
Start-Sleep -Seconds 5
Start-Process "http://localhost:5173"

Write-Host "App is running!" -ForegroundColor Cyan
