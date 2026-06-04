param(
    [ValidateSet("full", "fast")]
    [string]$SpeedProfile = "full",
    [int]$MinTrainGames = 700,
    [string]$Artifact = "ml_artifact.json",
    [string]$PlayersArtifact = "players_artifact.json",
    [string]$Target = "params_fitted.json",
    [string]$StartStage = "",
    [string]$BaseParams = "",
    [string]$RunId = "",
    [string]$RunsRoot = "ops/full_fit_runs",
    [string]$FitOut = "",
    [string]$ProgressOut = "",
    [string]$CheckpointDir = "",
    [string]$ReportPath = "",
    [string]$LatestLaunchReport = "ops/monitoring/full_fit_launch_latest.json",
    [string]$LatestFinalizeReport = "ops/monitoring/full_fit_finalize_report.json",
    [int]$PollSeconds = 60,
    # 18h: o full fit "full" leva ~14h (players_context_fit e' o gargalo). 6h (valor
    # antigo) fazia o watcher desistir antes do fit terminar -> nao promovia sozinho.
    # 18h cobre com folga; o StaleSeconds ainda pega um fit travado de verdade.
    [int]$TimeoutSeconds = 64800,
    [int]$StaleSeconds = 1800,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot

function Get-PythonCommand {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) {
        return @{ exe = $py.Source; prefix = @() }
    }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        return @{ exe = $launcher.Source; prefix = @("-3") }
    }
    throw "python_not_found"
}

function Resolve-RepoPath([string]$repoRoot, [string]$pathValue, [string]$defaultRel = "") {
    $raw = if ([string]::IsNullOrWhiteSpace($pathValue)) { $defaultRel } else { $pathValue }
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return ""
    }
    if ([System.IO.Path]::IsPathRooted($raw)) {
        return [System.IO.Path]::GetFullPath($raw)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $raw))
}

function Get-DefaultCsvs([string]$repoRoot) {
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($sub in @("CSV_HISTORICO", "CSV_DIARIO")) {
        $dir = Join-Path $repoRoot $sub
        if (-not (Test-Path $dir)) {
            continue
        }
        Get-ChildItem -Path $dir -Filter *.csv -File | Sort-Object FullName | ForEach-Object {
            $out.Add($_.FullName)
        }
    }
    return @($out)
}

function Get-RunningProcess([string]$pattern) {
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match $pattern }
}

function Copy-InputSnapshot([string]$sourcePath, [string]$destPath) {
    $destDir = Split-Path -Parent $destPath
    New-Item -ItemType Directory -Force -Path $destDir | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $destPath -Force
    return [System.IO.Path]::GetFullPath($destPath)
}

function Get-FileSnapshotMeta([string]$role, [string]$sourcePath, [string]$snapshotPath) {
    $src = Get-Item -LiteralPath $sourcePath -ErrorAction Stop
    $snap = Get-Item -LiteralPath $snapshotPath -ErrorAction Stop
    $sha = (Get-FileHash -LiteralPath $snapshotPath -Algorithm SHA256).Hash.ToLowerInvariant()
    return [ordered]@{
        role = $role
        source_path = $src.FullName
        snapshot_path = $snap.FullName
        sha256 = $sha
        size = [int64]$snap.Length
        source_mtime_utc = $src.LastWriteTimeUtc.ToString("o")
        snapshot_mtime_utc = $snap.LastWriteTimeUtc.ToString("o")
    }
}

$fitRunning = @(Get-RunningProcess "mlcore\.fit_ml_params")
if ((-not $DryRun) -and $fitRunning.Count -gt 0) {
    throw ("fit_ml_params_already_running: " + (($fitRunning | Select-Object -ExpandProperty ProcessId) -join ","))
}

$watchRunning = @(Get-RunningProcess "watch_full_fit_and_finalize\.py")
if ((-not $DryRun) -and $watchRunning.Count -gt 0) {
    throw ("watch_full_fit_and_finalize_already_running: " + (($watchRunning | Select-Object -ExpandProperty ProcessId) -join ","))
}

$pycmd = Get-PythonCommand
$csvs = Get-DefaultCsvs $root
if ($csvs.Count -le 0) {
    throw "no_csv_found"
}

$artifactSource = Resolve-RepoPath $root $Artifact
$playersArtifactSource = Resolve-RepoPath $root $PlayersArtifact
$targetResolved = Resolve-RepoPath $root $Target
$startStageResolved = if ([string]::IsNullOrWhiteSpace($StartStage)) { "" } else { $StartStage.Trim().ToLowerInvariant() }
$baseParamsSource = ""
if (-not [string]::IsNullOrWhiteSpace($startStageResolved) -and $startStageResolved -ne "load_inputs") {
    $baseParamsSource = Resolve-RepoPath $root $BaseParams $targetResolved
} elseif (-not [string]::IsNullOrWhiteSpace($BaseParams)) {
    $baseParamsSource = Resolve-RepoPath $root $BaseParams
}
if (-not (Test-Path $artifactSource)) { throw "artifact_not_found" }
if (-not (Test-Path $playersArtifactSource)) { throw "players_artifact_not_found" }
if (-not [string]::IsNullOrWhiteSpace($baseParamsSource) -and -not (Test-Path $baseParamsSource)) { throw "base_params_not_found" }

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "fullfit_${ts}_${SpeedProfile}"
}
$runBase = Resolve-RepoPath $root $RunsRoot
$runRoot = Resolve-RepoPath $runBase $RunId
$inputsDir = Join-Path $runRoot "inputs"
$logsDir = Join-Path $runRoot "logs"
New-Item -ItemType Directory -Force -Path $inputsDir | Out-Null
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

$fitOutResolved = Resolve-RepoPath $root $FitOut (Join-Path $runRoot "params_fitted.full.tmp.json")
$progressResolved = Resolve-RepoPath $root $ProgressOut (Join-Path $runRoot "fit_ml_params_progress.json")
$checkpointResolved = Resolve-RepoPath $root $CheckpointDir (Join-Path $runRoot "checkpoints")
$reportResolved = Resolve-RepoPath $root $ReportPath (Join-Path $runRoot "finalize_report.json")
$latestLaunchReportResolved = Resolve-RepoPath $root $LatestLaunchReport
$latestFinalizeReportResolved = Resolve-RepoPath $root $LatestFinalizeReport
$runManifestPath = Join-Path $runRoot "launch_manifest.json"
$sourceManifestPath = Join-Path $runRoot "source_snapshot_manifest.json"

$fitStdout = Join-Path $logsDir ("fit_full_" + $RunId + ".out.log")
$fitStderr = Join-Path $logsDir ("fit_full_" + $RunId + ".err.log")
$watchStdout = Join-Path $logsDir ("fit_watch_" + $RunId + ".out.log")
$watchStderr = Join-Path $logsDir ("fit_watch_" + $RunId + ".err.log")

$artifactSnapshot = Copy-InputSnapshot $artifactSource (Join-Path $inputsDir "artifacts\ml_artifact.json")
$playersArtifactSnapshot = Copy-InputSnapshot $playersArtifactSource (Join-Path $inputsDir "artifacts\players_artifact.json")
$baseParamsSnapshot = ""
if (-not [string]::IsNullOrWhiteSpace($baseParamsSource)) {
    $baseParamsSnapshot = Copy-InputSnapshot $baseParamsSource (Join-Path $inputsDir "artifacts\params_fitted.base.json")
}

$csvSnapshotPaths = @()
$csvSnapshotMeta = @()
for ($i = 0; $i -lt $csvs.Count; $i++) {
    $src = [System.IO.Path]::GetFullPath($csvs[$i])
    $destName = ('{0:d2}__{1}' -f ($i + 1), [System.IO.Path]::GetFileName($src))
    $dest = Copy-InputSnapshot $src (Join-Path $inputsDir (Join-Path "csvs" $destName))
    $csvSnapshotPaths += $dest
    $csvSnapshotMeta += ,(Get-FileSnapshotMeta -role ("csv[{0}]" -f ($i + 1)) -sourcePath $src -snapshotPath $dest)
}

$sourceManifest = [ordered]@{
    version = "full_fit_source_snapshot_v2"
    run_id = $RunId
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    inputs = [ordered]@{
        artifact = (Get-FileSnapshotMeta -role "artifact" -sourcePath $artifactSource -snapshotPath $artifactSnapshot)
        players_artifact = (Get-FileSnapshotMeta -role "players_artifact" -sourcePath $playersArtifactSource -snapshotPath $playersArtifactSnapshot)
        csvs = @($csvSnapshotMeta)
    }
}
if (-not [string]::IsNullOrWhiteSpace($baseParamsSnapshot)) {
    $sourceManifest.inputs.base_params = (Get-FileSnapshotMeta -role "base_params" -sourcePath $baseParamsSource -snapshotPath $baseParamsSnapshot)
}
$sourceManifest | ConvertTo-Json -Depth 10 | Set-Content -Path $sourceManifestPath -Encoding utf8

$fitArgs = @() + $pycmd.prefix + @(
    "-u",
    "-m", "mlcore.fit_ml_params",
    "--artifact", $artifactSnapshot,
    "--players-artifact", $playersArtifactSnapshot,
    "--out", $fitOutResolved,
    "--min-train-games", [string]$MinTrainGames,
    "--speed-profile", $SpeedProfile,
    "--progress-out", $progressResolved,
    "--checkpoint-dir", $checkpointResolved,
    "--run-label", $RunId,
    "--resume"
)
if (-not [string]::IsNullOrWhiteSpace($startStageResolved)) {
    $fitArgs += @("--start-stage", $startStageResolved)
}
if (-not [string]::IsNullOrWhiteSpace($baseParamsSnapshot)) {
    $fitArgs += @("--base-params", $baseParamsSnapshot)
}
foreach ($csv in $csvSnapshotPaths) {
    $fitArgs += @("--csv", $csv)
}

$watchArgs = @() + $pycmd.prefix + @(
    "tools/watch_full_fit_and_finalize.py",
    "--fit-out", $fitOutResolved,
    "--target", $targetResolved,
    "--report", $reportResolved,
    "--progress", $progressResolved,
    "--checkpoint-dir", $checkpointResolved,
    "--fit-stdout-log", $fitStdout,
    "--artifact", $artifactSnapshot,
    "--players-artifact", $playersArtifactSnapshot,
    "--source-manifest", $sourceManifestPath,
    "--run-id", $RunId,
    "--latest-report-alias", $latestFinalizeReportResolved,
    "--poll-seconds", [string]$PollSeconds,
    "--timeout-seconds", [string]$TimeoutSeconds,
    "--stale-seconds", [string]$StaleSeconds
)

$manifest = [ordered]@{
    version = "full_fit_launch_v3"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    repo_root = $root
    run_id = $RunId
    run_root = $runRoot
    speed_profile = $SpeedProfile
    min_train_games = $MinTrainGames
    start_stage = $startStageResolved
    target = $targetResolved
    base_params_source = $baseParamsSource
    source_manifest = $sourceManifestPath
    snapshot_artifact = $artifactSnapshot
    snapshot_players_artifact = $playersArtifactSnapshot
    snapshot_base_params = $baseParamsSnapshot
    snapshot_csvs = @($csvSnapshotPaths)
    fit_out = $fitOutResolved
    progress_out = $progressResolved
    checkpoint_dir = $checkpointResolved
    report_path = $reportResolved
    latest_finalize_report = $latestFinalizeReportResolved
    fit_stdout_log = $fitStdout
    fit_stderr_log = $fitStderr
    watcher_stdout_log = $watchStdout
    watcher_stderr_log = $watchStderr
    fit_args = @($fitArgs)
    watcher_args = @($watchArgs)
    dry_run = [bool]$DryRun
}

if ($DryRun) {
    $manifest | ConvertTo-Json -Depth 10 | Set-Content -Path $runManifestPath -Encoding utf8
    Write-Output ("DRY_RUN: launch manifest saved -> " + $runManifestPath)
    exit 0
}

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$fitProc = Start-Process -FilePath $pycmd.exe -ArgumentList $fitArgs -WorkingDirectory $root -RedirectStandardOutput $fitStdout -RedirectStandardError $fitStderr -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 1
$watchArgs += @("--fit-pid", [string]$fitProc.Id)
$watchProc = Start-Process -FilePath $pycmd.exe -ArgumentList $watchArgs -WorkingDirectory $root -RedirectStandardOutput $watchStdout -RedirectStandardError $watchStderr -PassThru -WindowStyle Hidden

$manifest["fit_pid"] = $fitProc.Id
$manifest["watcher_pid"] = $watchProc.Id
$manifest | ConvertTo-Json -Depth 10 | Set-Content -Path $runManifestPath -Encoding utf8
$manifest | ConvertTo-Json -Depth 10 | Set-Content -Path $latestLaunchReportResolved -Encoding utf8

Write-Output ("OK: isolated full fit launched | run_id=" + $RunId + " fit_pid=" + $fitProc.Id + " watcher_pid=" + $watchProc.Id)
Write-Output ("manifest=" + $runManifestPath)
exit 0
