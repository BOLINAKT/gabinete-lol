$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "ops\monitoring\logs"
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
$stdoutLog = Join-Path $logDir ("ml_monitoring_" + $ts + ".out.log")
$stderrLog = Join-Path $logDir ("ml_monitoring_" + $ts + ".err.log")
$pycmd = Get-PythonCommand
$args = @() + $pycmd.prefix + @(
    "tools/run_ml_monitoring_window.py",
    "--days", "7",
    "--run-regression",
    "--run-anchor",
    "--timeout", "900",
    "--anchor-timeout", "420"
)

$proc = Start-Process -FilePath $pycmd.exe -ArgumentList $args -WorkingDirectory $root -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -Wait -PassThru -WindowStyle Hidden
exit $proc.ExitCode
