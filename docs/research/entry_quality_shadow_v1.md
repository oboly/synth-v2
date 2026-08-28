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

Selection Engine v2 already computes `trade_quality_score` from symbol-local market evidence. CQ v0 therefore evolves that existing quantity instead of creating a parallel quality model.

CQ v0 uses:

```text
entry_quality_score = clamp01(
    trade_quality_score
    + timing_refinement_score
    - quality_penalty
)
```

Required 1d or 4h quality `BLOCKED` makes CQ unavailable (`BLOCKED`). A blocked 1h quality state only removes/refuses timing refinement and does not by itself block the higher-timeframe CQ.

This formula is intentionally conservative and exists to establish a measurable baseline. It is not the final CQ v1 cross-market model.

## Persistence

Research observations are stored only in:

```text
research_entry_quality_shadow
```

The table preserves the source Selection Engine quantities, CQ model version, quality states, reasons/blockers, optional PPP provenance, and optional Entry Strength.

It is not an input to current production selection ranking, `decision_gate`, `execution_planner`, executor, broker, or order handling.

## PPP input contract

The research runner does not query or recreate PPP itself.

Optional PPP can be provided through a CSV with explicit provenance:

```text
symbol,ppp_pct,ppp_kind,ppp_source_ref
AAVE,20.0,ACTIONABLE_PPP,<canonical reference>
```

All four fields are required by the CSV contract. If PPP value, kind, or source reference is absent, Entry Strength remains unavailable.

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

The emitted CSV/table is the Phase-1 dataset anchor. Future outcome labeling should join by asset/venue/as-of time and compare at minimum:

```text
PPP-only
trade_quality_score
current selection_score
CQ v0
Entry Strength = PPP * CQ
```

Outcome labeling belongs in research/backtest code and must not feed future-aware labels into live inference.

## Promotion gate

Do not promote Entry Strength into production ranking until:

1. PPP semantics/provenance are canonical and stable;
2. CQ v0 forward outcomes are measured against current baselines;
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
