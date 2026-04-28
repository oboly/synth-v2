# Paper Candidate Contract V1

## Layer

Research / paper-candidate boundary contract.

This contract defines the safe transport shape between:

```text
research preview
→ paper_candidate_contract
→ future decision_gate adapter
```

It is intentionally not a trading strategy, not a decision layer, and not an execution layer.

## Purpose

The contract exists so promoted research candidates can be shaped consistently before any later account-aware layer sees them.

It allows us to move from research output toward paper evaluation without leaking account or execution concerns into research code.

## Current primary producer

```text
src/research/run_swing_pullback_v5_paper_candidate_preview_v1.py
```

Current promoted research candidate:

```text
swing_pullback_recovery_v5
```

## Forbidden fields

A paper candidate must not contain account, portfolio, wallet, balance, position, order, execution plan, broker, or fill information.

Those belong later in account-aware and execution-aware layers.

## Boundary rule

The contract may say:

```text
this market candidate exists
```

It may not say:

```text
buy this now
place an order
allocate balance
open a position
```

## Current status

```text
RESEARCH_CONTRACT_READY
```

This enables future adapter design, but does not approve live or paper execution wiring.

## Next allowed step

Design a future adapter that reads contract-valid candidates and presents them to `decision_gate`.

No shortcut from research preview to execution.

## Execution regime label

`execution_regime_label` is a normalized market-only execution-context regime label carried by the paper-candidate transport contract.

Allowed values:

- `TREND_UP`
- `RANGE`
- `TREND_DOWN`

The field must be derived upstream of `decision_gate` from research context. `decision_gate` may pass it through as `SelectionInputRow.regime_label_4h`, but must not derive it from `rotation_bucket` or `classification_code`.
