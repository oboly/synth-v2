# TODO — Profit Plan Target Lifecycle History Truth V1

## Status

- Status: open
- Priority: P1
- Target release: Synth v2.23
- Owner layer: market-data history truth + reporting

## Sources

- User-observed IOST/EUR Profit Plan card and TradingView chart on 2026-07-11.
- `src/reporting/manual_short_trader_profit_plan_v1.py`
- `src/reporting/run_manual_short_trader_profit_plan_v1.py`
- `tests/test_manual_short_trader_profit_plan_v1.py`
- `tests/test_profit_plan_action_truth_v1.py`
- `docs/ops/manual_short_trader_profit_plan_v1.md`

## Current state / facts

Observed IOST/EUR card:

- main sell target: `0.0006392232`
- card lifecycle: `UPCOMING`
- card order guidance: `missing: sell @ 0.0006392232`
- current price had pulled back below the target

Observed market chart:

- multiple candles traded above `0.0006392232`
- at least one recent candle also appears to have crossed the target
- current price later returned below the target

Expected lifecycle, when a crossing occurred inside the same active map cycle:

```text
lifecycle_state=PASSED
coverage_state=PASSED_UNFILLED or MISSED_ORDER
retest_context=PULLBACK_BELOW_PASSED_LEVEL
is_active_target=false
```

The current classifier already supports history-aware `REACHED` and `PASSED` states. The likely defect is upstream history authority, activation-boundary selection, or closed-candle freshness rather than simple UI wording.

## Open tasks by priority

### P1 — Forensic IOST lifecycle audit

For the active IOST map, record:

- `map_cycle_id`
- `anchor_end_ts_utc`
- exact target value
- exact maximum market high since activation
- timestamp of first crossing
- latest included history candle timestamp
- whether the crossing occurred in a still-open candle
- whether the visible crossing occurred before or after the active map boundary

Do not infer lifecycle from the chart alone in code. Resolve it from authoritative persisted market history and explicit map-cycle identity.

### P1 — Preserve monotonic target lifecycle

Required invariant:

```text
authoritative high >= target after map activation -> at least REACHED
authoritative high > target after map activation  -> PASSED
REACHED/PASSED/COMPLETED never regress to NEAR/UPCOMING after pullback
```

A previously reached or passed level must not:

- become `active_target` again
- remain in `active_target_exit_zone`
- produce a `missing sell` instruction as though the target were still ahead
- contribute upcoming-target PPP or urgency

### P1 — Fail closed when target history is incomplete

When target-history authority is missing, stale, truncated, or does not cover the complete active map period:

```text
TARGET_LIFECYCLE_UNVERIFIED
```

Do not silently classify the target as `UPCOMING` merely because no crossing was found in incomplete history.

Expose enough evidence in JSON and HTML inspection fields to distinguish:

- verified upcoming
- verified reached/passed
- history unavailable
- history stale
- history coverage starts after map activation
- current/open candle not yet represented

### P1 — Resolve open-candle crossing semantics

Choose and document one deterministic authority contract:

1. closed-candle-only lifecycle with explicit `TARGET_LIFECYCLE_UNVERIFIED_CURRENT_CANDLE`, or
2. persisted authoritative intraperiod high merged with closed-candle history.

Do not use browser chart state or direct broker reads inside reporting.

### P1 — Regression coverage

Add focused tests for:

- target crossed, price pulls back below target, lifecycle remains `PASSED`
- target touched exactly, lifecycle becomes `REACHED`
- target crossed in latest authoritative intraperiod data
- target crossing before current map activation does not contaminate the new map cycle
- history begins after map activation -> fail-closed unverified state
- passed level is removed from active target zone
- passed unfilled target renders `missed sell level`, not `missing sell`
- PPP and action sorting do not treat a passed target as actionable upside

### P2 — Production evidence audit

After implementation, run a read-only audit for IOST and a small sample of other cards with pullbacks below prior targets. Record:

- map identity
- activation timestamp
- target lifecycle evidence
- first-cross timestamp
- current target selection
- rendered order guidance

## Blockers / dependencies

- Canonical active map-cycle identity must be available to the runner.
- Target-history coverage must be provably aligned to that exact map cycle.
- Any native per-level lifecycle projection used as authority must expose freshness and scope identity.

## Boundary

- market-data history truth and reporting only
- read-only market/account inspection
- no broker calls
- no broker writes
- no order submission
- no selection_engine changes
- no decision_gate changes
- no execution_planner changes
- no executor or agent changes
- no shortcut that lets reporting invent execution intent

## Non-goals

- changing fib target mathematics
- changing map selection policy
- repairing or placing orders
- treating TradingView as runtime authority
- carrying lifecycle evidence across unrelated map cycles
- solving this by changing only the visible `UPCOMING` label
