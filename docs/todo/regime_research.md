# TODO — Regime Research

## Status

Active next research lane.

## Purpose

Track the next market-only research sequence after the committed rotation replay, discovered regime clustering, and astro context baseline work.

This lane exists to keep the next measurements explicit before any classifier or tuning discussion:

- rerun `rotation_destination_historical_replay_audit_v2` full-ish with the newer summaries
- inspect symbol-by-confidence and symbol-by-curve-sanity outcomes
- run `market_regime_discovery_v1` full-ish
- compare discovered regimes with existing labels only after clustering
- design `symbol_breath_profile_v1`
- design `regime_interaction_audit_v1`
- later design `replay_safe_regime_classifier_v1`

## Completed baseline

Committed baseline work already done:

- `rotation_destination_historical_replay_audit_v2`
- v2 CLI/docs cleanup and extra summaries
- `market_regime_discovery_v1`
- `astro_cycle_context_v1`

These are research baselines, not tuning approvals.

## P1 — Immediate reruns and reads

Status: next.

Tasks:

- Rerun `rotation_destination_historical_replay_audit_v2` full-ish with the newer summary outputs.
- Inspect `summary_by_symbol_and_confidence_v2.csv`.
- Inspect `summary_by_symbol_and_curve_sanity_v2.csv`.
- Recheck included-only versus excluded-only confidence summaries before any interpretation drift.
- Keep this lane market-only and account-agnostic.

## P1 — Discovered regime pass

Status: next.

Tasks:

- Run `market_regime_discovery_v1` full-ish on a broader window.
- Review `summary_by_discovered_regime_v1.csv`.
- Review `regime_feature_centers_v1.csv`.
- Review `regime_forward_outcomes_v1.csv`.
- Compare discovered regimes with existing labels only after clustering via:
  - `comparison_discovered_vs_existing_regime_v1.csv`
  - `comparison_discovered_vs_curve_sanity_v1.csv`

Rule:

```text
existing labels may be joined after clustering for comparison only
existing labels must not become clustering input in this lane
```

## P2 — Symbol participation and breath profile design

Status: design next.

Tasks:

- Design `symbol_breath_profile_v1`.
- Focus on symbol-specific breath rhythm, phase behavior, and cross-asset participation context.
- Define required inputs, sampling, and output schema before implementation.
- Keep this as research-only characterization, not ranking logic.

Future measurement design note:

- add `phase_stability_score`
- add `symbol_breath_coherence_score`
- add `phase_lag_vs_anchor`
- add `trend_continuation_score`

These must remain separate from coverage or measurement-availability fields.

## P2 — Regime interaction audit design

Status: design next.

Tasks:

- Design `regime_interaction_audit_v1`.
- Define how discovered regimes interact with:
  - symbol breath profiles
  - destination confidence buckets
  - curve sanity states
- Keep this lane descriptive first; no runtime gating or threshold tuning.

## P3 — Later classifier work

Status: later / blocked on earlier reads.

Task:

- Design `replay_safe_regime_classifier_v1` only after:
  - discovered regime review is complete
  - symbol breath profile design is complete
  - regime interaction audit design is complete

## Parked

Status: parked until the regime path is mature.

Parked items:

- `astro_regime_interaction_audit_v1`
- deeper lunar/solar correlation research

Rule:

```text
no astro use before discovered regimes and symbol_breath_profile_v1 exist
```

## Boundary

```text
research-only
market-only
no selection_engine use
no decision_gate changes
no execution_planner changes
no executor changes
no broker/orders/account work
no dashboard tuning
```

## Sources

- `docs/research/rotation_destination_historical_replay_audit_v2.md`
- `docs/research/market_regime_discovery_v1.md`
- `docs/research/astro_cycle_context_v1.md`
- `src/research/run_rotation_destination_historical_replay_audit_v2.py`
- `src/research/run_market_regime_discovery_v1.py`
- `src/research/run_astro_cycle_context_v1.py`
