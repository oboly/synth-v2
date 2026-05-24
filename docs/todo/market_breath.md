# TODO — Market Breath

## Status

Characterized / parked until downstream use-case.

Market Breath V1 is now characterized as a Synth-native, regime-dependent state / risk-timing sensor from market data.

A+ symbolic reports are parked and must not be used as input for Market Breath.

## Final summary

Canonical summary:

- docs/research/market_breath_v1_sensor_classification_summary.md

Current conclusion:

- Market Breath V1 is best treated as a regime-dependent state / risk-timing classifier.
- It is not a universal action engine.
- Threshold calibration remains blocked.
- No runtime promotion is allowed.
- No further action is required unless a downstream use-case explicitly needs this sensor.

## Design rule — regime first

Assume Market Breath phase meaning is regime-dependent unless proven otherwise.

Do not evaluate phases as universal signals.

Correct question:

- In which regime does this phase/context work, fail, invert, or become unusable?

Incorrect question:

- Does this phase work universally?

Working interpretation path:

```text
phase label + regime context -> context interpretation
```

Not:

```text
phase label -> direct runtime action
```

Classification targets for future analysis:

- stable context candidate
- regime-dependent context
- inverted in some regimes
- low-sample / unusable
- late-risk warning
- reset/bounce context candidate

If a phase/context is stable across multiple regimes, that does not automatically create a new action item. It can simply mean the sensor interpretation is sufficiently characterized and should be parked until a downstream use-case explicitly needs it.

System rule:

```text
Regime first.
Signal second.
Execution last.
```

## Sources

- docs/research/market_breath_v1_1_calibration_audit.md
- docs/research/market_breath_v1_1_neutral_rest_bucket_review.md
- docs/research/market_breath_outcome_validation_v1.md
- docs/research/market_breath_outcome_validation_v1_findings.md
- docs/research/market_breath_outcome_bucket_analysis_v1.md
- docs/research/market_breath_regime_stability_validation_v1.md
- docs/research/market_breath_v1_sensor_classification_summary.md
- src/research/run_market_breath_v1_1_calibration_audit.py
- src/research/run_market_breath_outcome_validation_v1.py
- src/research/run_market_breath_outcome_bucket_analysis_v1.py
- src/research/run_market_breath_regime_stability_validation_v1.py
- data/research/market_breath_v1_1_calibration_audit/calibration_summary_v1.json
- data/research/market_breath_v1_1_calibration_audit/phase_distribution_by_asof_v1.jsonl
- data/research/market_breath_outcome_validation_v1/outcome_summary_v1.json
- data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl
- data/research/market_breath_outcome_bucket_analysis_v1/bucket_summary_v1.json
- data/research/market_breath_outcome_bucket_analysis_v1/bucket_rows_v1.jsonl
- data/research/market_breath_regime_stability_validation_v1/stability_summary_v1.json
- data/research/market_breath_regime_stability_validation_v1/window_summary_v1.jsonl

## Phase classifications

### NEUTRAL_TRANSITION

Status: characterized.

Classification:

```text
BASELINE_REST_BUCKET
```

Use as baseline/rest-state context, not runtime action.

### COLLAPSE_RESET

Status: characterized.

Classification:

```text
REGIME_DEPENDENT_RESET_BOUNCE_CONTEXT_CANDIDATE
```

First-pass results were strong, but longer-history rolling windows were mixed. Treat as regime-dependent context only.

### EXHALE_EXPANSION

Status: characterized.

Classification:

```text
REGIME_DEPENDENT_LATE_RISK_EXHAUSTION_CONTEXT_CANDIDATE
```

Repeated underperformance in sampled windows suggests late-risk / exhaustion context, not naive continuation.

### OVERBREATH_EXTENSION

Status: characterized with sample caution.

Classification:

```text
LATE_RISK_EXHAUSTION_CONTEXT_CANDIDATE_WITH_SAMPLE_CAUTION
```

Repeated underperformance in sufficient sampled windows, but sample mass remains limited.

### INHALE_ACCUMULATION

Status: low sample.

Classification:

```text
LOW_SAMPLE_EXPLORATORY
```

### HOLD_COMPRESSION

Status: low sample / reachability question.

Classification:

```text
LOW_SAMPLE_REACHABILITY_QUESTION
```

## Completed loop

Completed sequence:

```text
P0 audit interpretation cleanup
P1 neutral rest-bucket review
P2 threshold calibration kept blocked
P3 outcome validation dry runner
P4 outcome validation findings review
P5 bucketed outcome analysis
P6 longer-history / regime-dependency mapping
P7 sensor classification summary
```

## Parked state

No further work is needed in this loop unless one of the following happens:

- a downstream research lane needs a regime-aware state/risk label
- explicit regime labels are added and need Market Breath re-evaluation
- a specific threshold reachability problem is opened
- longer history becomes materially different and warrants rerun

## P1 — Regime cockpit page

Status: open / downstream cockpit use-case.

Add:

```text
/synth/regime.html
```

Language rule:

- Use `Market Breath` spelling for breath rhythm/phase context.
- Use `participation` where possible for cross-asset participation context.
- Use `breadth` only where it explicitly means market breadth participation/alignment.

Current downstream candidates, if reopened later:

- `symbol_breath_profile_v1`
- `regime_interaction_audit_v1`

Per-asset display:

- `market_breath_phase`
- `market_breath_state`
- `market_breath_context_state`
- `momentum_score`
- `relative_strength_score`
- `btc_alignment_score`
- `breadth_alignment_score`
- A+ legacy freshness/context

Boundary:

- Regime page is read-only cockpit context.
- Market Breath remains market-only and account-agnostic.
- Do not convert Market Breath into buy/sell logic.

## Boundary

- Research-only.
- Market-only.
- Account-agnostic.
- No A+ input.
- No PRO input.
- No symbolic labels.
- No Market Breath V1 threshold changes.
- No strategy logic.
- No selection engine changes.
- No advice engine changes.
- No decision gate changes.
- No execution planner changes.
- No executor or order changes.
- No broker calls.
- No broker writes.
- No order submission.
- No DB writes.
- No operational chain changes.
- No runtime promotion.

## Non-goals

- Do not continue analysis only because a context was characterized.
- Do not promote characterized contexts without a downstream use-case and separate validation path.
- Do not convert Market Breath directly into action logic.
