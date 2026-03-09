# scripts/build-sidecar.ps1
param()

$ErrorActionPreference = "Stop"

# 智能检测项目根目录
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

Set-Location $ProjectRoot

Write-Host "📂 Project root: $ProjectRoot" -ForegroundColor Cyan

$DestDir = "python_env"
$PythonVersion = "3.12.8"
$BuildDate = "20241219"

# 检测平台
function Get-Platform {
    $arch = [System.Environment]::GetEnvironmentVariable("PROCESSOR_ARCHITECTURE")
    if ($arch -eq "AMD64") {
        return "x86_64-pc-windows-msvc-shared"
    }
    throw "Unsupported architecture: $arch"
}

$Platform = Get-Platform
Write-Host "🔍 Detected platform: $Platform" -ForegroundColor Cyan

$PythonArchive = "cpython-$PythonVersion+$BuildDate-$Platform-install_only.tar.gz"
$DownloadUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/$BuildDate/$PythonArchive"

Write-Host "🔨 Preparing portable Python environment..." -ForegroundColor Yellow

if (Test-Path $DestDir) {
    Remove-Item -Recurse -Force $DestDir
}
New-Item -ItemType Directory -Path $DestDir | Out-Null

$CacheDir = ".cache/python-standalone"
if (-not (Test-Path $CacheDir)) {
    New-Item -ItemType Directory -Path $CacheDir | Out-Null
}

$CachePath = Join-Path $CacheDir $PythonArchive

if (-not (Test-Path $CachePath)) {
    Write-Host "📥 Downloading Python Standalone..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $CachePath
} else {
    Write-Host "✅ Using cached Python Standalone" -ForegroundColor Green
}

Write-Host "📦 Extracting Python runtime..." -ForegroundColor Yellow
tar -xzf $CachePath -C $DestDir

$PythonExe = Join-Path $DestDir "python\python.exe"
$PipExe = Join-Path $DestDir "python\Scripts\pip.exe"

Write-Host "🐍 Python version:" -ForegroundColor Cyan
& $PythonExe --version

Write-Host "📦 Upgrading pip..." -ForegroundColor Yellow
& $PythonExe -m pip install --upgrade pip

Write-Host "📦 Installing dependencies..." -ForegroundColor Yellow
& $PipExe install -r backend/requirements.txt

Write-Host "📋 Copying backend code..." -ForegroundColor Yellow
Copy-Item -Recurse -Force backend/app (Join-Path $DestDir "app")
Copy-Item -Force backend/sidecar_main.py (Join-Path $DestDir "sidecar_main.py")

Write-Host "🧹 Cleaning up..." -ForegroundColor Yellow
Get-ChildItem -Path $DestDir -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem -Path $DestDir -Recurse -File -Filter "*.pyc" | Remove-Item -Force
Get-ChildItem -Path $DestDir -Recurse -File -Filter "*.pyo" | Remove-Item -Force

$Size = (Get-ChildItem -Path $DestDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host "✅ Portable Python environment ready at $ProjectRoot\$DestDir" -ForegroundColor Green
Write-Host "📊 Size: $([math]::Round($Size, 2)) MB" -ForegroundColor Cyan