param(
    [string]$OutputDir = "C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\sp500_relative_synergy_20260710",
    [int]$MaxActive = 4,
    [int]$WaveSize = 4,
    [int]$HardFailAttempts = 4,
    [string]$TaskName = ""
)

$ErrorActionPreference = "Stop"
$Runner = "C:\GoogleDrive\TP\07_backtest_code\scripts\run_sp500_relative_synergy_research.py"
$Python = "C:\Python314\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { $Python = "python" }
$Workdir = "C:\GoogleDrive\TP"
$LogDir = Join-Path $OutputDir "resume_full_loop_logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$HardFailureDir = Join-Path $OutputDir "parallel_shards\manual_hard_failures"
$HardFailureResults = Join-Path $HardFailureDir "official_run_results.csv"

function Read-CandidateMetrics {
    $candidateMap = Join-Path $OutputDir "candidate_map.csv"
    if (-not (Test-Path -LiteralPath $candidateMap)) {
        throw "candidate_map.csv not found: $candidateMap"
    }
    @(Import-Csv -LiteralPath $candidateMap | Select-Object -ExpandProperty metric -Unique)
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
    $existing = @{}
    if (Test-Path -LiteralPath $HardFailureResults) {
        foreach ($row in (Import-Csv -LiteralPath $HardFailureResults -ErrorAction SilentlyContinue)) {
            $existing["$($row.metric)|$($row.side)"] = $true
        }
    }
    $rows = @()
    foreach ($side in $MissingSides) {
        $key = "$Metric|$side"
        if ($existing.ContainsKey($key)) { continue }
        $rows += [pscustomobject][ordered]@{
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
    if ($rows.Count -eq 0) { return }
    if (Test-Path -LiteralPath $HardFailureResults) {
        $rows | Export-Csv -LiteralPath $HardFailureResults -NoTypeInformation -Append
    }
    else {
        $rows | Export-Csv -LiteralPath $HardFailureResults -NoTypeInformation
    }
}

function Read-ActiveTasks {
    $active = @{}
    $procs = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "python.exe" -and
        $_.CommandLine -like "*run_sp500_relative_synergy_research.py*" -and
        $_.CommandLine -like "*$OutputDir*"
    }
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
$expected = $metrics.Count * 2
$done = Read-DonePairs
$active = Read-ActiveTasks
$remaining = @()
foreach ($metric in $metrics) {
    foreach ($side in @("Top", "Worst")) {
        $key = "$metric|$side"
        if (-not $done.ContainsKey($key) -and -not $active.ContainsKey($key)) {
            $remaining += [pscustomobject]@{
                Metric = $metric
                Side = $side
                Attempts = Get-MetricSideAttemptCount -Metric $metric -Side $side
            }
        }
    }
}

if ($done.Count -ge $expected) {
    [ordered]@{
        event = "sp500_synergy_wave_complete"
        time = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        done = $done.Count
        expected = $expected
    } | ConvertTo-Json -Compress
    exit 42
}

$launchable = @()
foreach ($task in $remaining) {
    if ($task.Attempts -ge $HardFailAttempts) {
        Write-HardFailures -Metric $task.Metric -MissingSides @($task.Side) -Attempts $task.Attempts
        $done["$($task.Metric)|$($task.Side)"] = $true
    }
    else {
        $launchable += $task
    }
}

$activeSlots = [Math]::Max(0, $MaxActive - $active.Count)
$take = [Math]::Min([Math]::Min($WaveSize, $activeSlots), $launchable.Count)
if ($take -le 0) {
    [ordered]@{
        event = "sp500_synergy_wave_idle"
        time = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        done = $done.Count
        expected = $expected
        active = $active.Count
        remaining = [Math]::Max(0, $expected - $done.Count - $active.Count)
    } | ConvertTo-Json -Compress
    if ($done.Count -ge $expected) { exit 42 }
    exit 0
}

$selected = @($launchable | Select-Object -First $take)
$i = 0
foreach ($task in $selected) {
    $safeMetric = $task.Metric -replace '[^A-Za-z0-9_.-]', '_'
    $safeSide = $task.Side -replace '[^A-Za-z0-9_.-]', '_'
    $wave = "wave_20260710_sp500_synergy_fullrun_{0}_{1:D2}" -f (Get-Date -Format "yyyyMMdd_HHmmss_fff"), $i
    $stdout = Join-Path $LogDir "$($wave)_$safeMetric`_$safeSide.stdout.log"
    $stderr = Join-Path $LogDir "$($wave)_$safeMetric`_$safeSide.stderr.log"
    $args = @(
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
    $proc = Start-Process -FilePath $Python -ArgumentList $args -WorkingDirectory $Workdir -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
    [ordered]@{
        event = "sp500_synergy_wave_launched"
        time = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        pid = $proc.Id
        metric = $task.Metric
        side = $task.Side
        attempts = $task.Attempts + 1
        wave = $wave
    } | ConvertTo-Json -Compress
    $i += 1
}

[ordered]@{
    event = "sp500_synergy_wave_summary"
    time = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    launched = $selected.Count
    active_before = $active.Count
    done = $done.Count
    expected = $expected
    remaining_before_launch = $remaining.Count
} | ConvertTo-Json -Compress
