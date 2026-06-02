# ML V3 Execution Plan (Code-Mapped)

Objective:
- Evolve current ML winner/odds engine to a stronger probabilistic core (near "10/10"),
- without breaking current production flow (A/B/C layers, guards, operations).

Scope:
- ML map/series probability path.
- Interleague robustness.
- Calibration quality for fair decimal odds.
- Players signal quality.

Current status (2026-03-05):
- Phase-0 full gate executed.
- A/B for dynamic-k executed on full history.
- Result: dynamic-k OFF outperformed ON on fused metrics in full gate; keep OFF in production for now.

Non-goal:
- Full monolith extraction in this phase.

---

## 1) Priority Order (Highest -> Lowest)

1. Dynamic skill core unification (team + players + uncertainty)
2. Calibration stack hardening (global + contextual)
3. Interleague hierarchy and transfer reliability
4. Players context upgrade (role/champion continuity, transfer priors)
5. Layer simplification / duplicate logic reduction
6. Ops + guardrails automation for safe promotion

---

## 2) Where To Change (File Map)

Core state and training:
- `mlcore/elo.py`
- `mlcore/players_layer.py`
- `mlcore/state_team_artifact.py`
- `mlcore/train_offline.py`
- `mlcore/fit_ml_params.py`
- `mlcore/calibration.py`
- `mlcore/calibration_diagnostics.py`
- `mlcore/walkforward_report.py`

Live/pre-live pipeline:
- `app_core/ml_pre_engine_core.py`
- `app_core/ml_pre_live_pipeline_core.py`
- `app_core/ml_live_pipeline_core.py`
- `app_core/hier_calibration_core.py`
- `app_core/style_matchup_core.py`
- `app_core/meta_blend_core.py`
- `app_core/state_strength_core.py`
- `app_core/series_bo_core.py`
- `app_core/runtime_tuning_core.py`

UI integration and configuration:
- `plays_app.py`

Tests:
- `mlcore/tests/test_elo_core.py`
- `mlcore/tests/test_players_layer_weights.py`
- `mlcore/tests/test_hier_calibration_core.py`
- `mlcore/tests/test_ml_pre_engine_core.py`
- `mlcore/tests/test_ml_pre_live_pipeline_core.py`
- `mlcore/tests/test_ml_live_pipeline_core.py`
- `mlcore/tests/test_style_matchup_core.py`
- `mlcore/tests/test_state_strength_core.py`
- `mlcore/tests/test_series_bo_core.py`
- `mlcore/tests/test_meta_blend_core.py`
- `mlcore/tests/test_runtime_tuning_core.py`
- `mlcore/tests/test_ml_parity_golden.py`

---

## 3) Phased Delivery

### Phase 0 - Baseline lock and gate (must-have before deeper changes)

Deliverables:
- Reproducible baseline gate report (`promote/shadow_only/reject`).
- Targeted regression tests run + health metrics snapshot.

Implementation:
- New runner: `tools/run_ml_v3_phase0_baseline.py`

Acceptance:
- No critical test failure.
- Walkforward and calibration reports generated.
- Decision recorded in JSON.

Run:
```powershell
python tools/run_ml_v3_phase0_baseline.py --mode recent
python tools/run_ml_v3_phase0_baseline.py --mode full
```

---

### Phase 1 - Dynamic skill core v3 (team+players in one probabilistic contract)

Goal:
- Move from scattered logic to a single latent skill contract:
  - mean skill (`mu`)
  - uncertainty (`sigma`)
  - volatility/drift control

Implementation:
- Expand model parameters and update flow in `mlcore/elo.py`.
- Align players transfer uncertainty in `mlcore/players_layer.py`.
- Store/reuse skill uncertainty in `mlcore/state_team_artifact.py`.
- Wire training/tuning in `mlcore/train_offline.py` and `mlcore/fit_ml_params.py`.

Acceptance:
- Non-inferior logloss/brier globally.
- Better stability in low-sample and interleague spots.
- Trace explains uncertainty contribution.

---

### Phase 2 - Calibration v3 (odds quality)

Goal:
- Improve fair-odds fidelity by stronger probability calibration.

Implementation:
- Keep current calibrator path, add contextual calibration regime:
  - global
  - same-league
  - interleague
  - BO bucket
  - patch status bucket
- Files:
  - `mlcore/calibration.py`
  - `mlcore/calibration_diagnostics.py`
  - `app_core/hier_calibration_core.py`
  - `app_core/runtime_tuning_core.py`

Acceptance:
- ECE down or non-inferior with better tail reliability.
- No collapse to 50/50 in healthy-signal spots.
- Better consistency between `p_map_used` and shown decimal odds.

---

### Phase 3 - Interleague engine hardening

Goal:
- Make cross-league predictions mathematically safer and more coherent.

Implementation:
- Strengthen macro hierarchy and transfer dampening:
  - `mlcore/elo.py`
  - `mlcore/players_layer.py`
  - `app_core/hier_calibration_core.py`
  - `app_core/state_strength_core.py`
  - `app_core/style_matchup_core.py`
  - `app_core/meta_blend_core.py`
  - `app_core/series_bo_core.py`

Acceptance:
- Lower instability for interleague outputs.
- Clear interleague trace fields (`scope`, `pair signal`, shrink, cap).

---

### Phase 4 - Players upgrade (towards ML-level quality)

Goal:
- Push players block closer to ML quality with richer context.

Implementation:
- Improve prior/transfer modeling in:
  - `mlcore/players_layer.py`
  - `mlcore/fit_ml_params.py`
  - `app_core/ml_pre_engine_core.py`
- Extend reliability components (continuity, recency, interleague transfer risk).

Acceptance:
- Players-only model improves and fused model stays stable.
- No regressions in manual lineup workflow.

---

### Phase 5 - Duplicate logic cleanup and single source of truth

Goal:
- Remove repeated league/macro/interregional logic and reduce drift bugs.

Implementation:
- Introduce one shared canonicalization helper module in `mlcore` and consume from `app_core`/`plays_app`.
- Replace duplicated macro maps progressively.

Acceptance:
- No behavior regression (parity tests + focused regression fixtures).
- Lower maintenance overhead for new league name changes.

---

## 4) Success Metrics (promotion contract)

Primary:
- Global logloss (walkforward)
- Global brier (walkforward)
- Fused ECE (calibration diagnostics)

Secondary:
- By-league logloss/brier drift
- Interleague reliability bands
- Share of unstable low-evidence shifts

Hard stop:
- Any critical unit/regression test failure.
- Odds semantic regression on anchors.

---

## 5) Immediate Next Actions

1. Run phase-0 in `recent` mode and archive output.
2. Run phase-0 in `full` mode (2024+2025+2026) and archive output.
3. Start Phase 1 changes in `mlcore/elo.py` + `mlcore/players_layer.py` behind feature flags.
4. Promote only with gate evidence (`promote` decision) and keep rollback path active.
