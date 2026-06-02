$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$monitorScript = Join-Path $PSScriptRoot "run_daily_ml_monitoring.ps1"
$csvScript = Join-Path $PSScriptRoot "run_daily_csv_ingest_gate.ps1"

$tasks = @(
    @{
        Name = "GabineteLOL_ML_Monitor_Daily"
        Time = "09:10"
        Script = $monitorScript
    },
    @{
        Name = "GabineteLOL_CSV_Ingest_Gate_Daily"
        Time = "09:20"
        Script = $csvScript
    }
)

foreach ($task in $tasks) {
    $tr = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + $task.Script + '"'
    schtasks /Create /F /SC DAILY /TN $task.Name /TR $tr /ST $task.Time | Out-Null
}

foreach ($task in $tasks) {
    schtasks /Query /TN $task.Name /V /FO LIST
    ""
}
