param(
    [string]$OutputDir = "C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\sp500_relative_synergy_20260710",
    [string]$WavePrefix = "wave_20260710_sp500_synergy_ps_loop",
    [int]$Limit = 0,
    [int]$Retries = 3,
    [int]$MetricTimeoutSeconds = 900,
    [switch]$Finalize,
    [switch]$StopOnFailure
)

$ErrorActionPreference = "Stop"
$Runner = "C:\GoogleDrive\TP\07_backtest_code\scripts\run_sp500_relative_synergy_research.py"
$Workdir = "C:\GoogleDrive\TP"
$LogDir = Join-Path $OutputDir "resume_full_loop_logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Read-CandidateMetrics {
    $path = Join-Path $OutputDir "candidate_map.csv"
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing candidate_map.csv: $path"
    }
    @(Import-Csv -LiteralPath $path | Select-Object -ExpandProperty metric -Unique)
}

function Read-DonePairs {
    $done = @{}
    $paths = @()
    $main = Join-Path $OutputDir "official_run_results.csv"
    if (Test-Path -LiteralPath $main) {
        $paths += $main
    }
    $shardRoot = Join-Path $OutputDir "parallel_shards"
    if (Test-Path -LiteralPath $shardRoot) {
        $paths += @(Get-ChildItem -LiteralPath $shardRoot -Recurse -Filter official_run_results.csv -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
    }
    foreach ($path in $paths) {
        foreach ($row in (Import-Csv -LiteralPath $path -ErrorAction SilentlyContinue)) {
            if ($row.status -in @("success", "skipped")) {
                $done["$($row.metric)|$($row.side)"] = $true
            }
        }
    }
    $done
}

function Get-ProgressPayload {
    param([string[]]$Metrics)
    $done = Read-DonePairs
    $remaining = @()
    foreach ($metric in $Metrics) {
        if (-not ($done.ContainsKey("$metric|Top") -and $done.ContainsKey("$metric|Worst"))) {
            $remaining += $metric
        }
    }
    $doneRows = $done.Count
    $expectedRows = $Metrics.Count * 2
    [ordered]@{
        event = "sp500_synergy_ps_loop_progress"
        time = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        output_dir = $OutputDir
        metric_total = $Metrics.Count
        metric_done = $Metrics.Count - $remaining.Count
        metric_remaining = $remaining.Count
        done_rows = $doneRows
        expected_rows = $expectedRows
        percent = if ($expectedRows -gt 0) { [math]::Round(100.0 * $doneRows / $expectedRows, 4) } else { 0.0 }
        next_metric = if ($remaining.Count -gt 0) { $remaining[0] } else { "" }
    }
}

function Test-MetricDone {
    param([string]$Metric)
    $done = Read-DonePairs
    $done.ContainsKey("$Metric|Top") -and $done.ContainsKey("$Metric|Worst")
}

function Run-OneMetric {
    param([string]$Metric, [int]$Sequence)
    $wave = "{0}_{1}_{2:D5}" -f $WavePrefix, (Get-Date -Format "yyyyMMdd_HHmmss"), $Sequence
    $safeMetric = $Metric -replace '[^A-Za-z0-9_.-]', '_'
    $stdout = Join-Path $LogDir "$wave`_$safeMetric.stdout.log"
    $stderr = Join-Path $LogDir "$wave`_$safeMetric.stderr.log"
    $argsList = @(
        $Runner,
        "--output-dir", $OutputDir,
        "--metrics", $Metric,
        "--workers", "1",
        "--shard-size", "1",
        "--direct-worker",
        "--run-only",
        "--resume",
        "--wave", $wave
    )
    $startPayload = [ordered]@{
        event = "sp500_synergy_ps_loop_metric_start"
        time = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        metric = $Metric
        wave = $wave
        sequence = $Sequence
    }
    $startPayload | ConvertTo-Json -Compress
    $proc = Start-Process -FilePath "python" -ArgumentList $argsList -WorkingDirectory $Workdir -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $timedOut = $false
    try {
        Wait-Process -Id $proc.Id -Timeout $MetricTimeoutSeconds -ErrorAction Stop
    }
    catch {
        $timedOut = $true
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    $proc.Refresh()
    [ordered]@{
        event = "sp500_synergy_ps_loop_metric_exit"
        time = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        metric = $Metric
        wave = $wave
        timed_out = $timedOut
        exit_code = if ($timedOut) { "timeout" } else { $proc.ExitCode }
        stdout = $stdout
        stderr = $stderr
    } | ConvertTo-Json -Compress
}

$metrics = Read-CandidateMetrics
$launched = 0
while ($true) {
    $progress = Get-ProgressPayload -Metrics $metrics
    $progress | ConvertTo-Json -Compress
    if ([int]$progress.metric_remaining -eq 0) {
        if ($Finalize) {
            $wave = "{0}_finalize_{1}" -f $WavePrefix, (Get-Date -Format "yyyyMMdd_HHmmss")
            & python $Runner --output-dir $OutputDir --workers 1 --shard-size 1 --resume --wave $wave
            exit $LASTEXITCODE
        }
        exit 0
    }
    if ($Limit -gt 0 -and $launched -ge $Limit) {
        exit 0
    }

    $metric = [string]$progress.next_metric
    $success = $false
    for ($attempt = 1; $attempt -le [math]::Max(1, $Retries); $attempt++) {
        [ordered]@{
            event = "sp500_synergy_ps_loop_metric_attempt"
            time = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            metric = $metric
            attempt = $attempt
            launched = $launched + 1
        } | ConvertTo-Json -Compress
        Run-OneMetric -Metric $metric -Sequence ($launched + 1)
        if (Test-MetricDone -Metric $metric) {
            $success = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    $launched += 1
    if (-not $success) {
        [ordered]@{
            event = "sp500_synergy_ps_loop_metric_incomplete_after_retries"
            time = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            metric = $metric
        } | ConvertTo-Json -Compress
        if ($StopOnFailure) {
            exit 2
        }
    }
    Start-Sleep -Seconds 1
}
