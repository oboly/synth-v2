# TODO — Breath Curve

## GitHub Issue migration

Status: migrated

Operational status/priority is owned by GitHub Issues.

Section ownership:
- P2 Baseline and regime validation continuation + P2 Non-overlap and regime-difference follow-up -> Issue #282

Unmigrated executable scope:
- none

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

## P2 — Non-overlap and regime-difference follow-up

Status: open / parked.

Sources:

```text
docs/research/breath_curve_broader_history_findings_20260513.md
docs/research/breath_curve_non_overlap_validation_findings_20260513.md
docs/research/breath_curve_regime_gate_findings_20260513.md
```

Tasks:

- Keep the strongest prior Breath Curve candidate demoted after failed non-overlap / older-history validation.
- Build a regime-difference diagnostic before reopening any promotion discussion.
- Compare the winning Jan-Apr 2026 windows against failed older windows.
- Check whether the supportive BTC/ETH bear context remains explainable in older regimes.
- Optionally test A+ transition overlays only as archive/comparator research, not active Market Breath input.
- Treat any surviving result as research-only until non-overlapping validation is materially stronger.

Boundary:

```text
No runtime promotion.
No selection modifier.
No strategy candidate promotion from the failed non-overlap run.
```

## Boundary

```text
No direct orders.
No decision_gate bypass.
No execution_planner/executor logic.
No live/paper trigger from this research lane.
```
