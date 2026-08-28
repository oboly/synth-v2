# Entry Quality / CQ Shadow v1

Issue: #542
Status: research-only, shadow-only

## Purpose

Measure a market-only Entry Quality / Conviction Quality score without changing current production selection or trading authority.

```text
CQ = Entry Quality, normalized 0..1
Entry Strength = PPP * CQ
```

PPP remains owned by its canonical producer/contract. This lane never reconstructs PPP from levels and never treats CQ as a probability of target realization.

## CQ v0 reconciliation

Selection Engine v2 already computes `trade_quality_score` from symbol-local market evidence. CQ v0 therefore uses that score directly:

```text
entry_quality_score = clamp01(trade_quality_score)
```

This is deliberate. Existing `selection_score` already equals `trade_quality_score + timing_refinement_score - quality_penalty`; repeating that algebra would make CQ identical to the production score and invalidate baseline comparison.

The shadow dataset persists `trade_quality_score`, `selection_score`, timing refinement, quality penalties, quality states, CQ, PPP provenance, and optional Entry Strength.

Required 1d or 4h quality `BLOCKED` makes CQ unavailable. A blocked 1h quality state does not itself block the higher-timeframe CQ.

## Replay-safe evidence identity

Research observations are stored only in `research_entry_quality_shadow`.

Observation identity is **not** runner time and is not a single maximum source timestamp. The runner reads and persists all six source timestamps that can influence Selection Engine scoring:

```text
quality_ts_1d_utc
quality_ts_4h_utc
quality_ts_1h_utc
signal_ts_1d_utc
signal_ts_4h_utc
signal_ts_1h_utc
```

A deterministic SHA-256 `evidence_key` fingerprints that complete timestamp tuple. The unique persistence identity is:

```text
asset_id + venue + evidence_key + cq_model_version
```

`asof_ts_utc` is retained as the maximum timestamp in the evidence tuple for convenient chronological joins, but it is **not** sufficient by itself to identify an observation. `created_ts_utc` remains process/persistence time.

This prevents a newer quality or signal row from overwriting an earlier shadow observation even when another source timestamp is later than both. Missing any required evidence timestamp fails closed.

## PPP input contract

Optional PPP is supplied through explicit-provenance CSV:

```text
symbol,ppp_pct,ppp_kind,ppp_source_ref
AAVE,20.0,ACTIONABLE_PPP,<canonical reference>
```

Supported kinds are exactly `ACTIONABLE_PPP` and `PLANNING_PPP`. One run may contain only one kind. Missing values/provenance, unknown kinds, or mixed kinds fail closed.

This lets #552/#561 stabilize user-facing PPP semantics independently before direct integration.

## Runner

A normal shadow run always writes CSV to:

```text
data/research/entry_quality_shadow_v1/entry_quality_shadow_v1.csv
```

`--out-csv` overrides the destination. `--write-db` explicitly enables research-table persistence and still writes CSV.

Lifecycle output follows:

```text
STARTED
SAFETY
PHASE_START / PHASE_END
FINISHED
```

A failed run emits exactly one terminal `FAILED`. `STARTED` is emitted before the database connection attempt.

No production ranking change occurs in either mode.

## Forward evaluation

The emitted CSV/table is the Phase-1 dataset anchor. Future outcome labeling should compare at minimum:

```text
PPP-only
trade_quality_score
current selection_score
CQ v0
Entry Strength = PPP * CQ
```

For CQ v0, `trade_quality_score` and CQ intentionally have equal numeric values. CQ v1 becomes distinct only when validated cross-market context is added. Outcome labels remain research/backtest-only and must never leak into live inference.

## Promotion gate

Do not promote Entry Strength into production ranking until PPP semantics are stable, shadow outcomes beat or improve current baselines, cross-market CQ inputs are validated upstream observations, evidence supports promotion, and the production contract is explicitly versioned/reviewed.

## Safety invariants

```text
research_only=1
shadow_only=1
selection_ranking_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_writes=0
orders=0
```
