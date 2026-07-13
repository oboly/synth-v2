# TODO — Regime Research

## Status

Active next research lane.

## Purpose

Track the next market-only research sequence after the committed rotation replay, discovered regime clustering baseline, and astro context dataset baseline work.

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

These are committed research baselines, not tuning approvals.

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

## P2 — BTC-to-alt shock propagation / lead-lag replay

Status: observation logged / research design required.

Observed example:

```text
date: 2026-07-13
timezone: Europe/Amsterdam, to be verified against source timestamps
anchor event: BTC dip around 02:00
follower event: HYPE dip around 06:00
observed lag: approximately 4 hours
```

Interpretation:

This is a potentially useful leader-follower observation, not evidence of causality or a stable 4-hour rule. It may reflect genuine delayed propagation, different liquidity and participant composition, exchange/session timing, candle alignment, or coincidence.

Research target:

Design `btc_alt_shock_propagation_replay_v1` as a leak-free, market-only replay that measures whether BTC downside and upside shocks systematically reach individual altcoins with repeatable delays.

Required measurements:

- detect BTC anchor events using explicit, versioned shock definitions;
- measure follower response windows at 0h, 1h, 2h, 4h, 6h, 8h, 12h, and 24h;
- evaluate downside and upside propagation separately;
- measure lag to first material move, lag to maximum response, response magnitude, recovery time, and direction agreement;
- compare raw returns with BTC-beta-adjusted and market-relative returns;
- test event-time alignment on 5m, 15m, 1h, and 4h bars where coverage permits;
- stratify by symbol, liquidity, volatility, sector/theme, market regime, BTC dominance context, and session/time-of-day;
- test whether lag behavior changes during broad risk-off, selective rotation, and strong alt-participation regimes;
- distinguish direct BTC response from delayed sector/leader propagation;
- include HYPE as the seed example, then evaluate the full eligible universe;
- use multiple-testing controls and out-of-sample windows before interpreting stable leader-follower edges.

Minimum outputs:

```text
anchor_event_count
follower_event_count
median_lag_to_first_response
median_lag_to_max_response
lag_distribution
direction_agreement_rate
response_magnitude
beta_adjusted_response
false_propagation_rate
regime_breakdown
symbol_breakdown
timeframe_breakdown
session_breakdown
out_of_sample_stability
```

Guardrails:

```text
No fixed 4-hour delay may be assumed from one observation.
No look-ahead event matching.
BTC context remains global market context, not a per-asset account signal.
No selection_engine, decision_gate, execution_planner, executor, broker, order, or account changes.
Any later runtime use requires a separately validated promotion contract.
```

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
no astro use before discovered regime review and symbol_breath_profile_v1 design exist
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
