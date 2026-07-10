param(
    [string]$OutputDir = "C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\sp500_relative_synergy_20260710",
    [int]$Workers = 2,
    [int]$ExpectedRows = 738,
    [int]$SleepSeconds = 45
)

$ErrorActionPreference = "Continue"
$Runner = "C:\GoogleDrive\TP\07_backtest_code\scripts\run_sp500_relative_synergy_research.py"
$Python = "C:\Python314\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { $Python = "python" }
$LogDir = Join-Path $OutputDir "resume_full_loop_logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$GuardLog = Join-Path $LogDir "sp500_direct_guard.log"

function Write-GuardLog {
    param([string]$Message)
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message" | Add-Content -LiteralPath $GuardLog
}

function Stop-NonSp500Runners {
    $targets = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "python.exe" -and (
            $_.CommandLine -like "*run_eu_small_relative_synergy*" -or
            $_.CommandLine -like "*run_stoxx600_relative_synergy*" -or
            $_.CommandLine -like "*resume_stoxx600_relative_synergy*" -or
            $_.CommandLine -like "*run_direct_resume_loop.py*"
        )
    }
    foreach ($proc in $targets) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    return @($targets).Count
}

function Get-Sp500RunnerCount {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "python.exe" -and
        $_.CommandLine -like "*run_sp500_relative_synergy_research.py*" -and
        $_.CommandLine -like "*$OutputDir*"
    }).Count
}

function Get-TerminalRowCount {
    $done = @{}
    $paths = @()
    $main = Join-Path $OutputDir "official_run_results.csv"
    if (Test-Path -LiteralPath $main) { $paths += $main }
    $shardRoot = Join-Path $OutputDir "parallel_shards"
    if (Test-Path -LiteralPath $shardRoot) {
        $paths += @(Get-ChildItem -LiteralPath $shardRoot -Recurse -Filter official_run_results.csv -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
    }
    foreach ($path in $paths) {
        foreach ($row in (Import-Csv -LiteralPath $path -ErrorAction SilentlyContinue)) {
            $manualHardFailure = ($row.status -eq "failed" -and [string]$row.message -like "*manual hard failure*")
            if ($row.status -in @("success", "skipped") -or $manualHardFailure) {
                $done["$($row.metric)|$($row.side)"] = $true
            }
        }
    }
    return $done.Count
}

function Start-Sp500Pool {
    $wave = "wave_20260710_sp500_guard_pool_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")
    $stdout = Join-Path $LogDir "$wave.stdout.log"
    $stderr = Join-Path $LogDir "$wave.stderr.log"
    $args = @(
        $Runner,
        "--output-dir", $OutputDir,
        "--workers", "$Workers",
        "--shard-size", "1",
        "--fresh-process-per-batch",
        "--run-only",
        "--resume",
        "--wave", $wave
    )
    $proc = Start-Process -FilePath $Python -ArgumentList $args -WorkingDirectory "C:\GoogleDrive\TP" -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
    Write-GuardLog "started wave=$wave pid=$($proc.Id) workers=$Workers stdout=$stdout stderr=$stderr"
}

Write-GuardLog "guard_start output_dir=$OutputDir expected=$ExpectedRows workers=$Workers sleep=$SleepSeconds"
while ($true) {
    $killed = Stop-NonSp500Runners
    $done = Get-TerminalRowCount
    $active = Get-Sp500RunnerCount
    Write-GuardLog "progress done=$done expected=$ExpectedRows active_sp500=$active killed_non_sp500=$killed"
    if ($done -ge $ExpectedRows) {
        Write-GuardLog "complete done=$done"
        exit 0
    }
    if ($active -lt 1) {
        Start-Sp500Pool
    }
    Start-Sleep -Seconds $SleepSeconds
}
