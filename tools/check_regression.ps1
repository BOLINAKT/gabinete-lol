param(
    [switch]$UpdateFixtures
)

$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")
$env:PYTHONPATH = "."

function Invoke-PythonChecked {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    & python @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code ${LASTEXITCODE}: python $($Args -join ' ')"
    }
}

if ($UpdateFixtures) {
    Write-Host "[1/3] Updating regression fixtures..."
    Invoke-PythonChecked -Args @("tools\update_regression_fixtures.py", "--root", ".")
}

Write-Host "[2/3] Running odds regression tests..."
Invoke-PythonChecked -Args @(
    "-m", "unittest",
    "mlcore.tests.test_odds_regression",
    "mlcore.tests.test_odds_regression_40",
    "mlcore.tests.test_interleague_matchups_regression",
    "mlcore.tests.test_key_matchups_regression",
    "mlcore.tests.test_key_matchups_extended_regression",
    "mlcore.tests.test_players_fusion_regression"
)

Write-Host "[3/3] Running core safety test suite..."
Invoke-PythonChecked -Args @(
    "-m", "unittest",
    "mlcore.tests.test_settings_core",
    "mlcore.tests.test_app_state",
    "mlcore.tests.test_resumo_core",
    "mlcore.tests.test_app_odds_core",
    "mlcore.tests.test_players_state",
    "mlcore.tests.test_players_core",
    "mlcore.tests.test_players_layer_weights",
    "mlcore.tests.test_fit_ml_params",
    "mlcore.tests.test_regression_fixtures",
    "mlcore.tests.test_ui_labels_integrity",
    "mlcore.tests.test_smoke"
)

Write-Host "OK: regression checks passed."
