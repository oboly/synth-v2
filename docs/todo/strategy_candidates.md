# TODO — Strategy Candidates

## Status

Open design questions. No implementation yet.

## Source

```text
docs/research/strategy_candidate_horizon_buckets_v1.md
```

## Core rule

```text
Asset != strategy.
```

Correct selection unit:

```text
candidate = (
    asset,
    strategy_family,
    horizon_bucket,
    setup_context,
    validation_state,
)
```

## P2 — Horizon bucket design review

Status: open.

Tasks:

- Decide whether selection_engine should rank per horizon bucket independently.
- Specify how same-asset candidates conflict or reinforce each other.
- Specify how decision_gate resolves exposure when multiple active candidates target the same asset.
- Define graduation rules from `BREATH_CURVE_RESEARCH` to runtime-eligible candidate buckets only after validation.
- Preserve the rule: asset is not a strategy.

## Boundary

```text
selection_engine may rank market-only candidates.
decision_gate resolves account-aware exposure/conflicts/sizing/permission.
execution_planner/executor do not contain candidate logic.
```

No direct buy/sell/order logic belongs here.

## P2 — Swing pullback 168h research lead

Status: research lead / not paper-ready.

Source:

```text
docs/research/strategy_candidate_registry_v1.md
```

Context:

The 72h/168h swing pullback variants produced strong per-symbol returns but failed global promotion due to:

```text
MIN_WINRATE_NOT_MET
MIN_POSITIVE_MONTH_RATIO_NOT_MET
WORST_MONTH_AVG_LOSS_EXCEEDED
```

Likely missing components:

- exit algorithm
- regime filter
- symbol-specific promotion layer
- parent-state logic review

Tasks:

- Keep the 168h branch as a research lead, not a live or paper candidate.
- Revisit only through explicit validation of exit logic, regime filtering, and symbol-specific promotion rules.
- Do not stage arena-v2 candidates through the older `swing_pullback_recovery_v5` contract.

## P3 — Legacy Synth v1 regime/strategy prior review

Status: parked research prior.

Source:

```text
docs/legacy_synth_v1_regime_strategy_priors.md
```

Tasks:

- Define a v2 `regime_selector` contract.
- Define a v2 `strategy_selector` contract.
- Build a research export with `asset_id`, `symbol`, `interval_code`, `asof_ts_utc`, `regime_code`, `candidate_strategy_family`, and `source_prior`.
- Validate old priors on current v2 feature/signal data.
- Only then consider selection_engine integration.

Boundary:

```text
Legacy priors are microscope data, not steering input.
Do not implement direct old Synth v1 strategy routing in live code.
No selection/advice/decision/execution changes without a separate reviewed task.
```
