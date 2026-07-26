param(
    [string]$OutputDir = "C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\sp500_relative_synergy_20260710",
    [int]$MaxActive = 4,
    [int]$WaveSize = 4,
    [int]$HardFailAttempts = 4,
    [string]$TaskName = ""
)

$ErrorActionPreference = "Stop"
$PauseFlag = "C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\pause_sp500_synergy.flag"
if (Test-Path -LiteralPath $PauseFlag) {
    [ordered]@{
        event = "sp500_synergy_wave_paused"
        time = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        pause_flag = $PauseFlag
    } | ConvertTo-Json -Compress
    exit 0
}
$Runner = "C:\GoogleDrive\TP\07_backtest_code\scripts\run_sp500_relative_synergy_research.py"
$Workdir = "C:\GoogleDrive\TP"
$LogDir = Join-Path $OutputDir "resume_full_loop_logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$HardFailureDir = Join-Path $OutputDir "parallel_shards\manual_hard_failures"
$HardFailureResults = Join-Path $HardFailureDir "official_run_results.csv"

function Read-CandidateMetrics {
    @(Import-Csv -LiteralPath (Join-Path $OutputDir "candidate_map.csv") | Select-Object -ExpandProperty metric -Unique)
}

function Read-DonePairs {
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
    $done
}

function Get-MetricSideAttemptCount {
    param([string]$Metric, [string]$Side)
    $safeMetric = $Metric -replace '[^A-Za-z0-9_.-]', '_'
    $safeSide = $Side -replace '[^A-Za-z0-9_.-]', '_'
    @(Get-ChildItem -LiteralPath $LogDir -Filter "*_$safeMetric`_$safeSide.stdout.log" -ErrorAction SilentlyContinue).Count
}

function Write-HardFailures {
    param([string]$Metric, [string[]]$MissingSides, [int]$Attempts)
    if (-not $MissingSides -or $MissingSides.Count -eq 0) { return }
    New-Item -ItemType Directory -Force -Path $HardFailureDir | Out-Null
    $rows = @()
    foreach ($side in $MissingSides) {
        $rows += [ordered]@{
            benchmark = "SP500"
            metric = $Metric
            side = $side
            top = if ($side -eq "Top") { "True" } else { "False" }
            start_date = ""
            status = "failed"
            message = "manual hard failure after $Attempts process-level attempts"
            run_dir = ""
            sec_list = ""
            perf_ptf = ""
            perf_bench = ""
            plot = ""
        }
    }
    $objects = $rows | ForEach-Object { [pscustomobject]$_ }
    if (Test-Path -LiteralPath $HardFailureResults) {
        $objects | Export-Csv -LiteralPath $HardFailureResults -NoTypeInformation -Append
    }
    else {
        $objects | Export-Csv -LiteralPath $HardFailureResults -NoTypeInformation
    }
}

function Read-ActiveTasks {
    $active = @{}
    $procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*run_sp500_relative_synergy_research.py*" }
    foreach ($proc in $procs) {
        $cmd = [string]$proc.CommandLine
        if ($cmd -match "--metrics\s+([^\s]+)") {
            $metric = $Matches[1]
            $sides = @("Top", "Worst")
            if ($cmd -match "--sides\s+([^\s]+)") {
                $sideArg = $Matches[1]
                if ($sideArg -and $sideArg.ToLowerInvariant() -ne "all") {
                    $sides = @($sideArg.Split(",") | ForEach-Object {
                        $value = $_.Trim()
                        if ($value.ToLowerInvariant() -eq "top") { "Top" }
                        elseif ($value.ToLowerInvariant() -eq "worst") { "Worst" }
                    } | Where-Object { $_ })
                }
            }
            foreach ($side in $sides) {
                $active["$metric|$side"] = [int]$proc.ProcessId
            }
        }
    }
    $active
}

$metrics = Read-CandidateMetrics
$done = Read-DonePairs
$active = Read-ActiveTasks
$remaining = @()
foreach ($metric in $metrics) {
    foreach ($side in @("Top", "Worst")) {
        $key = "$metric|$side"
        if (-not $done.ContainsKey($key)) {
            $attempts = Get-MetricSideAttemptCount -Metric $metric -Side $side
        if ($attempts -ge $HardFailAttempts) {
                Write-HardFailures -Metric $metric -MissingSides @($side) -Attempts $attempts
                $done[$key] = $true
            continue
        }
            $remaining += [pscustomobject]@{ Metric = $metric; Side = $side; Key = $key }
        }
    }
}
$doneRows = $done.Count
$expectedRows = $metrics.Count * 2
$slots = [math]::Max(0, $MaxActive - $active.Count)
$launchCount = [math]::Min([math]::Min($WaveSize, $slots), $remaining.Count)
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$started = @()

foreach ($task in $remaining) {
    if ($started.Count -ge $launchCount) { break }
    if ($active.ContainsKey($task.Key)) { continue }
    $idx = $started.Count
    $wave = "wave_20260710_sp500_synergy_sched_{0}_{1:D2}" -f $stamp, $idx
    $safeMetric = $task.Metric -replace '[^A-Za-z0-9_.-]', '_'
    $safeSide = $task.Side -replace '[^A-Za-z0-9_.-]', '_'
    $stdout = Join-Path $LogDir "$wave`_$safeMetric`_$safeSide.stdout.log"
    $stderr = Join-Path $LogDir "$wave`_$safeMetric`_$safeSide.stderr.log"
    $argsList = @(
        $Runner,
        "--output-dir", $OutputDir,
        "--metrics", $task.Metric,
        "--sides", $task.Side,
        "--workers", "1",
        "--shard-size", "1",
        "--direct-worker",
        "--run-only",
        "--resume",
        "--wave", $wave
    )
    $proc = Start-Process -FilePath "python" -ArgumentList $argsList -WorkingDirectory $Workdir -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $started += [ordered]@{ pid = $proc.Id; metric = $task.Metric; side = $task.Side; key = $task.Key; wave = $wave; stdout = $stdout; stderr = $stderr }
}

$remainingMetricCount = @($remaining | Select-Object -ExpandProperty Metric -Unique).Count

$payload = [ordered]@{
    event = "sp500_synergy_wave_launch"
    time = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    output_dir = $OutputDir
    done_rows = $doneRows
    expected_rows = $expectedRows
    percent = if ($expectedRows -gt 0) { [math]::Round(100.0 * $doneRows / $expectedRows, 4) } else { 0.0 }
    metric_remaining = $remainingMetricCount
    task_remaining = $remaining.Count
    active_count = $active.Count
    max_active = $MaxActive
    launched = $started.Count
    started = $started
}
$payload | ConvertTo-Json -Depth 5 -Compress

if ($remaining.Count -eq 0 -and $TaskName.Trim()) {
    schtasks /Delete /TN $TaskName /F | Out-Null
}
if ($remaining.Count -eq 0) {
    exit 42
}
