[CmdletBinding()]
param(
    [int]$Port = 8060
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$pythonPath = Join-Path $repoRoot ".venv_tp\Scripts\python.exe"
$dashboardUrl = "http://127.0.0.1:$Port/"
$healthUrl = $dashboardUrl
$logDir = Join-Path $repoRoot ".tmp_dashboard_work\launcher"
$stdoutLog = Join-Path $logDir "system_dashboard.stdout.log"
$stderrLog = Join-Path $logDir "system_dashboard.stderr.log"

function Test-TpDashboard {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -eq 200 -and $response.Content -match "TP System Dashboard"
    }
    catch {
        return $false
    }
}

function Show-LaunchError {
    param([string]$Message)

    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        $Message,
        "TP Web App 启动失败",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    Show-LaunchError "未找到 Python 环境：`n$pythonPath"
    exit 1
}

if (-not (Test-TpDashboard)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null

    try {
        Start-Process `
            -FilePath $pythonPath `
            -ArgumentList @(
                "-m",
                "presentation_layer.cli",
                "system-dashboard",
                "--host",
                "127.0.0.1",
                "--port",
                $Port
            ) `
            -WorkingDirectory $repoRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutLog `
            -RedirectStandardError $stderrLog | Out-Null
    }
    catch {
        Show-LaunchError "无法启动 TP Web App：`n$($_.Exception.Message)"
        exit 1
    }

    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Milliseconds 500
        if (Test-TpDashboard) {
            $ready = $true
            break
        }
    }

    if (-not $ready) {
        $details = ""
        if (Test-Path -LiteralPath $stderrLog) {
            $details = (Get-Content -LiteralPath $stderrLog -Tail 12 -ErrorAction SilentlyContinue) -join "`n"
        }
        Show-LaunchError "服务未能在 30 秒内启动。`n`n日志：$stderrLog`n`n$details"
        exit 1
    }
}

Start-Process $dashboardUrl
