# TODO — Breath Curve

## Status

Parked / open research continuation.

Breath Curve remains research-only, market-only, and account-agnostic.

## Sources

```text
docs/research/breath_curve_template_partial_v1.md
docs/research/breath_curve_regime_gated_policy_preview_v1.md
```

## Known path

```text
partial-cycle matcher
-> policy baseline comparisons
-> regime-gated preview validation
-> strategy scoring board per regime
-> optional paper-candidate contract
-> decision_gate only after validated promotion
```

## P2 — Baseline and regime validation continuation

Status: open / parked.

Tasks:

- Keep Breath Curve research parked from runtime selection until validation is stronger.
- Continue baseline comparisons where useful:
  - same-window buy-and-hold baseline
  - random anchor baseline
  - checkpoint 0.618 vs 0.786 comparison
  - offset-match-only variant
  - symbol/regime buckets
  - optional later 4h partial-cycle test
- Keep regime-gated preview market-only and account-agnostic.
- Do not convert regime-gated results into selection modifiers without validation and explicit promotion review.

## Boundary

```text
No direct orders.
No decision_gate bypass.
No execution_planner/executor logic.
No live/paper trigger from this research lane.
```
