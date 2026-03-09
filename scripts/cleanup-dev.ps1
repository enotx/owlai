# scripts/cleanup-dev.ps1

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

Write-Host "🧹 Cleaning up Owl development environment..." -ForegroundColor Cyan
Write-Host "📂 Project root: $ProjectRoot" -ForegroundColor Cyan

Write-Host "   Stopping processes..." -ForegroundColor Yellow
Get-Process | Where-Object { $_.ProcessName -like "*Owl*" -or $_.ProcessName -like "*app*" } | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process | Where-Object { $_.CommandLine -like "*sidecar_main.py*" } | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process | Where-Object { $_.ProcessName -eq "cargo" } | Stop-Process -Force -ErrorAction SilentlyContinue

$PortFile = Join-Path $env:USERPROFILE ".owl_backend_port"
if (Test-Path $PortFile) {
    Write-Host "   Removing port file..." -ForegroundColor Yellow
    Remove-Item $PortFile -Force
}

$TauriDir = Join-Path $ProjectRoot "frontend\src-tauri"
if (Test-Path $TauriDir) {
    Write-Host "   Cleaning cargo build artifacts..." -ForegroundColor Yellow
    Set-Location $TauriDir
    cargo clean
}

Write-Host "✅ Cleanup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "💡 You can now run: npm run tauri:dev" -ForegroundColor Cyan