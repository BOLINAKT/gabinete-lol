param(
    [switch]$Apply,
    [string]$ArchiveRoot = "ops/archive/workspace_cleanup",
    [int]$OlderThanDays = 2
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$archiveDir = Join-Path $repoRoot $ArchiveRoot
$now = Get-Date
$cutoff = $now.AddDays(-1 * [math]::Abs($OlderThanDays))
$dryRun = -not $Apply.IsPresent

function New-ArchivePath {
    param(
        [string]$ArchiveBase,
        [string]$RelativePath
    )
    return Join-Path $ArchiveBase $RelativePath
}

function Add-Candidate {
    param(
        [System.Collections.Generic.List[object]]$Bucket,
        [System.IO.FileSystemInfo]$Item,
        [string]$Category,
        [string]$Reason
    )
    $Bucket.Add([PSCustomObject]@{
        Category = $Category
        Type = $(if ($Item.PSIsContainer) { "dir" } else { "file" })
        RelativePath = $Item.FullName.Substring($repoRoot.Length).TrimStart('\')
        Length = $(if ($Item.PSIsContainer) { $null } else { [int64]$Item.Length })
        LastWriteTime = $Item.LastWriteTime
        Reason = $Reason
    }) | Out-Null
}

$candidates = New-Object 'System.Collections.Generic.List[object]'

# Root temp artifacts produced by local smoke/probe runs.
Get-ChildItem $repoRoot -File | Where-Object {
    $_.Name -like 'tmp_*' -and $_.LastWriteTime -lt $cutoff
} | ForEach-Object {
    Add-Candidate -Bucket $candidates -Item $_ -Category "root_tmp" -Reason "temporary smoke/probe artifact"
}

# Root zero-byte logs from aborted or superseded runs.
Get-ChildItem $repoRoot -File | Where-Object {
    ($_.Name -like '*.out.log' -or $_.Name -like '*.err.log') -and $_.Length -eq 0 -and $_.LastWriteTime -lt $cutoff
} | ForEach-Object {
    Add-Candidate -Bucket $candidates -Item $_ -Category "zero_log" -Reason "empty log file"
}

# Smoke checkpoints only; do not touch the active full-fit checkpoint directory.
$smokeCheckpointRoot = Join-Path $repoRoot 'ops\fit_checkpoints'
if (Test-Path $smokeCheckpointRoot) {
    Get-ChildItem $smokeCheckpointRoot -Directory | Where-Object {
        $_.Name -match 'smoke' -and $_.LastWriteTime -lt $cutoff
    } | ForEach-Object {
        Add-Candidate -Bucket $candidates -Item $_ -Category "smoke_checkpoint" -Reason "smoke checkpoint directory"
    }
}

$report = [PSCustomObject]@{
    version = "workspace_cleanup_v1"
    generated_at = (Get-Date).ToString("o")
    dry_run = [bool]$dryRun
    archive_root = $ArchiveRoot
    older_than_days = [int]$OlderThanDays
    candidate_count = $candidates.Count
    by_category = @{}
    candidates = $candidates
}

$grouped = $candidates | Group-Object Category
foreach ($g in $grouped) {
    $report.by_category[$g.Name] = [int]$g.Count
}

if (-not $dryRun) {
    New-Item -ItemType Directory -Force -Path $archiveDir | Out-Null
    foreach ($item in $candidates) {
        $src = Join-Path $repoRoot $item.RelativePath
        $dst = New-ArchivePath -ArchiveBase $archiveDir -RelativePath $item.RelativePath
        $dstDir = Split-Path -Parent $dst
        if (-not (Test-Path $src)) {
            continue
        }
        New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
        Move-Item -LiteralPath $src -Destination $dst -Force
    }
}

$reportPath = Join-Path $repoRoot 'ops\monitoring\workspace_cleanup_report.json'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $reportPath) | Out-Null
$report | ConvertTo-Json -Depth 6 | Set-Content -Path $reportPath -Encoding UTF8

Write-Host ("Cleanup report: {0}" -f $reportPath)
Write-Host ("Dry-run: {0}" -f $dryRun)
Write-Host ("Candidates: {0}" -f $candidates.Count)
foreach ($g in $grouped | Sort-Object Name) {
    Write-Host (" - {0}: {1}" -f $g.Name, $g.Count)
}
