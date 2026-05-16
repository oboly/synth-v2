# Market Breath V1 Sensor Classification Summary

## Status

Status: characterized and parked until a downstream use-case explicitly needs it.

This summary closes the current Market Breath V1.1 calibration and outcome-measurement research loop. It does not add code, change thresholds, add strategy logic, or promote anything to runtime.

## Research sequence covered

```text
Market Breath V1.1 calibration audit
-> sparse phase diagnostics
-> neutral rest-bucket review
-> outcome validation dry run
-> outcome findings review
-> bucketed outcome analysis
-> longer-history / regime-dependency mapping
-> sensor classification summary
```

## Core design conclusion

Market Breath V1 should be treated as a regime-dependent state / risk-timing classifier.

It should not be treated as a universal action engine.

Correct interpretation path:

```text
phase label + regime context -> context interpretation
```

Not:

```text
phase label -> direct runtime action
```

System rule:

```text
Regime first.
Signal second.
Execution last.
```

## Phase classifications

### NEUTRAL_TRANSITION

Classification:

```text
BASELINE_REST_BUCKET
```

Interpretation:

`NEUTRAL_TRANSITION` is structurally dominant and should remain the conservative rest bucket for now. Its dominance constrains validation design, but it does not prove that Market Breath V1 thresholds are wrong.

Use:

- baseline for comparing other phases
- broad rest-state context
- not an action signal

### COLLAPSE_RESET

Classification:

```text
REGIME_DEPENDENT_RESET_BOUNCE_CONTEXT_CANDIDATE
```

Finding:

`COLLAPSE_RESET` had strong first-pass 24-candle outcome behavior, but longer-history rolling windows showed mixed behavior. Treat any outperformance as regime-dependent.

Interpretation:

This phase may identify reset/bounce-prone conditions in some regimes, but it is not universal.

Use:

- candidate context for further regime-aware review
- possible reset/bounce sensor label
- not runtime eligible

### EXHALE_EXPANSION

Classification:

```text
REGIME_DEPENDENT_LATE_RISK_EXHAUSTION_CONTEXT_CANDIDATE
```

Finding:

`EXHALE_EXPANSION` underperformed the neutral baseline in first-pass validation and had no sufficient outperforming buckets in the bucketed pass. Longer-history rolling windows showed repeated underperformance in sampled windows.

Interpretation:

This phase appears more useful as a late-risk / exhaustion context candidate than as a naive continuation label.

Use:

- possible avoid-chasing / late-expansion context
- possible risk overlay candidate after future validation
- not runtime eligible

### OVERBREATH_EXTENSION

Classification:

```text
LATE_RISK_EXHAUSTION_CONTEXT_CANDIDATE_WITH_SAMPLE_CAUTION
```

Finding:

`OVERBREATH_EXTENSION` underperformed in sufficient sampled windows and is consistent with late-risk / exhaustion behavior, but sample mass remains limited.

Use:

- exploratory late-risk context
- sample-cautious research label
- not runtime eligible

### INHALE_ACCUMULATION

Classification:

```text
LOW_SAMPLE_EXPLORATORY
```

Finding:

`INHALE_ACCUMULATION` remains too sparse for strong conclusions.

### HOLD_COMPRESSION

Classification:

```text
LOW_SAMPLE_REACHABILITY_QUESTION
```

Finding:

`HOLD_COMPRESSION` is near-unreachable in the sampled data. This is a reachability/calibration question only.

## Threshold calibration decision

Threshold calibration remains blocked.

Reason:

- V1 thresholds were intentionally conservative.
- Neutral dominance alone is not a defect.
- Regime-dependent behavior is expected and does not imply threshold failure.
- No specific measurement or reachability problem has been proven beyond `HOLD_COMPRESSION` being sparse.

Only reopen threshold calibration for a specific reachability or measurement problem.

## Runtime decision

No runtime promotion.

Market Breath V1 is not promoted to runtime behavior, candidate ranking, permission logic, execution planning, or automation.

## Recommended parked state

Current state:

```text
characterized sensor
research-only
market-only
account-agnostic
parked until downstream use-case
```

No further action is required from this research loop unless one of the following happens:

- a downstream research lane needs a regime-aware state/risk label
- a specific threshold reachability problem is opened
- explicit regime labels are added and need Market Breath re-evaluation
- longer history becomes materially different and warrants rerun

## Downstream path if resumed

If resumed, the correct path is:

```text
Market Breath phase labels
-> explicit regime labels
-> context interpretation validation
-> optional feature candidate review
-> selection_engine only after validation
-> decision_gate for account-aware permission
-> execution_planner
-> executor
```

## Boundaries

- Research-only.
- Market-only.
- Account-agnostic.
- No A+ input.
- No PRO input.
- No symbolic labels.
- No Market Breath V1 threshold changes.
- No strategy logic.
- No runtime promotion.
- No database writes.
- No operational chain changes.

## Non-goals

- Do not declare strategy edge.
- Do not derive position sizing.
- Do not add candidate promotion.
- Do not continue analysis only because a context was characterized.

Stable or repeated behavior means the sensor may be understood well enough for now. It does not automatically create a new task.
