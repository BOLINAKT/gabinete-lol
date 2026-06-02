param(
    [string]$OutDir = "",
    [string[]]$Csv = @(),
    [string]$Artifact = "ml_artifact.json",
    [string]$PlayersArtifact = "players_artifact.json",
    [switch]$SkipHealth
)

$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")
$env:PYTHONPATH = "."

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $OutDir = Join-Path "." ("evidence\release_check_" + $ts)
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$summaryPath = Join-Path $OutDir "summary.txt"
$testsLog = Join-Path $OutDir "tests.log"
$traceLog = Join-Path $OutDir "trace_check.log"
$healthLog = Join-Path $OutDir "health.log"
$healthJson = Join-Path $OutDir "model_health_report.json"

function Write-Summary([string]$msg) {
    Add-Content -Path $summaryPath -Value $msg
    Write-Host $msg
}

Write-Summary ("release_check_at=" + (Get-Date).ToString("s"))
Write-Summary ("out_dir=" + (Resolve-Path $OutDir))

Write-Host "[1/3] Running full test suite..."
$__eap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
cmd /c "python -m unittest discover -s mlcore/tests -p test_*.py" 2>&1 | Tee-Object -FilePath $testsLog
$ErrorActionPreference = $__eap
if ($LASTEXITCODE -ne 0) {
    Write-Summary "tests=FAIL"
    throw "Test suite failed. See: $testsLog"
}
Write-Summary "tests=PASS"

Write-Host "[2/3] Running trace consistency check..."
$__eap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
cmd /c "python tools/check_smoke_trace.py" 2>&1 | Tee-Object -FilePath $traceLog
$ErrorActionPreference = $__eap
if ($LASTEXITCODE -ne 0) {
    Write-Summary "trace_check=FAIL"
    throw "Trace check failed. See: $traceLog"
}
Write-Summary "trace_check=PASS"

if (-not $SkipHealth) {
    Write-Host "[3/3] Running model health report..."
    $csvList = @()
    if ($Csv -and $Csv.Count -gt 0) {
        $csvList = @($Csv)
    } else {
        $dirs = @(".\CSV_DIARIO", ".\CSV_HISTORICO")
        foreach ($d in $dirs) {
            if (Test-Path $d) {
                $found = Get-ChildItem -Path $d -Filter *.csv -File -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
                if ($found) { $csvList += $found }
            }
        }
        if (-not $csvList) {
            $csvList = Get-ChildItem -Path "." -Filter *.csv -File -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
        }
    }
    $csvList = @($csvList | Select-Object -Unique)
    $artifactPath = (Resolve-Path $Artifact -ErrorAction SilentlyContinue)
    $playersArtifactPath = (Resolve-Path $PlayersArtifact -ErrorAction SilentlyContinue)

    if ((-not $artifactPath) -or (-not $playersArtifactPath) -or (-not $csvList) -or ($csvList.Count -eq 0)) {
        Write-Summary "health_report=SKIP (missing csv/artifact)"
        $skipMsg = @(
            "health_report=SKIP",
            ("artifact_exists=" + [bool]$artifactPath),
            ("players_artifact_exists=" + [bool]$playersArtifactPath),
            ("csv_count=" + ($csvList.Count))
        )
        $skipMsg | Set-Content -Path $healthLog
    } else {
        $args = @("tools/model_health_report.py")
        foreach ($c in $csvList) {
            $args += @("--csv", $c)
        }
        $args += @(
            "--artifact", [string]$artifactPath,
            "--players-artifact", [string]$playersArtifactPath,
            "--out", $healthJson
        )
        $argText = ($args -join " ")
        $__eap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        cmd /c ("python " + $argText) 2>&1 | Tee-Object -FilePath $healthLog
        $ErrorActionPreference = $__eap
        if ($LASTEXITCODE -ne 0) {
            Write-Summary "health_report=FAIL"
            throw "Health report failed. See: $healthLog"
        }
        Write-Summary "health_report=PASS"
        Write-Summary ("health_report_json=" + (Resolve-Path $healthJson))
    }
} else {
    Write-Summary "health_report=SKIP (--SkipHealth)"
}

Write-Summary ("tests_log=" + (Resolve-Path $testsLog))
Write-Summary ("trace_log=" + (Resolve-Path $traceLog))
if (Test-Path $healthLog) { Write-Summary ("health_log=" + (Resolve-Path $healthLog)) }

Write-Host "OK: release checks finished."
