# Entry Quality / CQ Shadow v1

Issue: #542
Status: research-only, shadow-only

## Purpose

Measure a market-only Entry Quality / Conviction Quality score without changing current production selection or trading authority.

Core quantities:

```text
CQ = Entry Quality, normalized 0..1
Entry Strength = PPP * CQ
```

PPP remains owned by its existing canonical producer/contract. This research lane never reconstructs PPP from levels and never treats CQ as a probability of target realization.

## Phase-0 reconciliation result

Selection Engine v2 already computes `trade_quality_score` from symbol-local market evidence. CQ v0 therefore uses that existing score directly as the independent local-quality baseline:

```text
entry_quality_score = clamp01(trade_quality_score)
```

This is deliberate. The existing `selection_score` already equals the local trade-quality score plus timing refinement minus quality penalties. Repeating that algebra for CQ would make CQ identical to `selection_score` and invalidate the planned baseline comparison.

The shadow table therefore persists both `trade_quality_score` and `selection_score`. Timing refinement and quality penalties are also retained as observable source fields, but are not applied again to CQ v0.

Required 1d or 4h quality `BLOCKED` makes CQ unavailable (`BLOCKED`). A blocked 1h quality state does not by itself block the higher-timeframe CQ.

CQ v0 is intentionally a conservative baseline, not the final CQ v1 cross-market model.

## Persistence and time identity

Research observations are stored only in:

```text
research_entry_quality_shadow
```

`asof_ts_utc` is the canonical source/evidence snapshot timestamp carried by the Selection Engine row. It is never runner wall-clock time. `created_ts_utc` remains the separate persistence/process timestamp.

This distinction is required for deterministic replay and forward-outcome joins: rerunning the same market snapshot must not fabricate a new observation identity merely because the runner was invoked later.

The table preserves the source Selection Engine quantities, CQ model version, quality states, reasons/blockers, optional PPP provenance, and optional Entry Strength.

It is not an input to current production selection ranking, `decision_gate`, `execution_planner`, executor, broker, or order handling.

## PPP input contract

The research runner does not query or recreate PPP itself.

Optional PPP can be provided through a CSV with explicit provenance:

```text
symbol,ppp_pct,ppp_kind,ppp_source_ref
AAVE,20.0,ACTIONABLE_PPP,<canonical reference>
```

Supported kinds are exactly:

```text
ACTIONABLE_PPP
PLANNING_PPP
```

A single run may contain only one PPP kind. Mixed Planning/Actionable datasets fail closed so Entry Strength comparisons cannot silently mix two different PPP semantics.

All four CSV fields are required. Missing value/provenance, unknown kind, or mixed kinds reject the input rather than producing Entry Strength.

This allows #552/#561 to stabilize the canonical user-facing PPP semantics independently before any future direct integration.

## Runner

```text
python -m src.research.run_entry_quality_shadow_v1 --out-csv /tmp/cq_shadow.csv
```

Database persistence is explicit opt-in:

```text
python -m src.research.run_entry_quality_shadow_v1 --write-db
```

No production ranking change occurs in either mode.

## Forward evaluation

The emitted CSV/table is the Phase-1 dataset anchor. Future outcome labeling should join by asset/venue/source-as-of time and compare at minimum:

```text
PPP-only
trade_quality_score
current selection_score
CQ v0
Entry Strength = PPP * CQ
```

For CQ v0, `trade_quality_score` and `CQ v0` intentionally have equal numeric values. CQ v0 adds the explicit CQ state/blocking/provenance contract while preserving the existing local-quality score as baseline. The distinct comparison becomes meaningful when CQ v1 adds validated cross-market context; until then, `selection_score` remains a genuinely separate baseline because it includes timing refinement and quality penalties.

Outcome labeling belongs in research/backtest code and must not feed future-aware labels into live inference.

## Promotion gate

Do not promote Entry Strength into production ranking until:

1. PPP semantics/provenance are canonical and stable;
2. CQ shadow outcomes are measured against current baselines;
3. cross-market CQ v1 inputs are added only from validated upstream market observations;
4. evidence supports a ranking promotion;
5. the production contract is explicitly versioned and reviewed.

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
