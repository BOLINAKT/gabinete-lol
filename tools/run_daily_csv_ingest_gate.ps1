$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "ops\csv_ingest\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

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

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$stdoutLog = Join-Path $logDir ("csv_ingest_gate_" + $ts + ".out.log")
$stderrLog = Join-Path $logDir ("csv_ingest_gate_" + $ts + ".err.log")
$auditOut = Join-Path $logDir ("league_catalog_audit_" + $ts + ".out.log")
$auditErr = Join-Path $logDir ("league_catalog_audit_" + $ts + ".err.log")
$pycmd = Get-PythonCommand
$args = @() + $pycmd.prefix + @(
    "tools/run_csv_ingest_gate.py"
)

$proc = Start-Process -FilePath $pycmd.exe -ArgumentList $args -WorkingDirectory $root -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -Wait -PassThru -WindowStyle Hidden
if ($proc.ExitCode -eq 0) {
    $auditArgs = @() + $pycmd.prefix + @(
        "tools/audit_league_catalog.py"
    )
    $auditProc = Start-Process -FilePath $pycmd.exe -ArgumentList $auditArgs -WorkingDirectory $root -RedirectStandardOutput $auditOut -RedirectStandardError $auditErr -Wait -PassThru -WindowStyle Hidden
    exit $auditProc.ExitCode
}
exit $proc.ExitCode
