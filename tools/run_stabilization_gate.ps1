param(
    [ValidateSet("quick", "full")]
    [string]$Profile = "quick",
    [int]$Timeout = 180,
    [string]$Out = ""
)

$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")
$env:PYTHONPATH = "."

$args = @("tools\run_stabilization_gate.py", "--profile", $Profile, "--timeout", [string]$Timeout)
if (-not [string]::IsNullOrWhiteSpace($Out)) {
    $args += @("--out", $Out)
}

& python @args
exit $LASTEXITCODE
