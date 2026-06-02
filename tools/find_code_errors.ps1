param(
    [ValidateSet("quick", "full")]
    [string]$Profile = "quick",
    [string[]]$Path = @(),
    [string]$Out = "",
    [switch]$IncludeRepoChecks
)

$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")
$env:PYTHONPATH = "."

$args = @("tools\find_code_errors.py", "--profile", $Profile)
foreach ($item in $Path) {
    if (-not [string]::IsNullOrWhiteSpace($item)) {
        $args += @("--path", $item)
    }
}
if (-not [string]::IsNullOrWhiteSpace($Out)) {
    $args += @("--out", $Out)
}
if ($IncludeRepoChecks) {
    $args += "--include-repo-checks"
}

& python @args
exit $LASTEXITCODE
