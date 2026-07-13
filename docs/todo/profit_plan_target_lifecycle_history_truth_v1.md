# TODO — Profit Plan Target Lifecycle History Truth V1

## Status

```text
active P1
Target release: Synth v2.23
Owner: market-data history truth + reporting consumption
```

## Sources

- User-observed IOST/EUR Profit Plan card and chart on 2026-07-11.
- `src/reporting/manual_short_trader_profit_plan_v1.py`
- `src/reporting/run_manual_short_trader_profit_plan_v1.py`
- `tests/test_manual_short_trader_profit_plan_v1.py`
- `tests/test_profit_plan_action_truth_v1.py`
- `docs/architecture/native_short_map_level_status_contract_v1.md`
- `docs/todo/native_short_map_level_status_v1.md`

## Current state / facts

Observed card state:

```text
market: IOST-EUR
target: 0.0006392232
lifecycle: UPCOMING
guidance: missing sell @ 0.0006392232
```

Observed chart context showed candles above the same target followed by a pullback below it.
Chart appearance is diagnostic evidence only; runtime truth must come from persisted authoritative history aligned to the exact active map cycle.

The native infrastructure gap is closed:

- canonical `current_map_cycle_id` exists in scope-status truth;
- `native_short_map_level_status_v1` persistence, materializer, runner, chain integration, and runtime wiring are merged and accepted;
- V1 target roles have explicit `ACTIVE` / `REACHED` / `PASSED` semantics.

The remaining defect is therefore not “build a level-status subsystem.” It is to prove the exact IOST history boundary and make Profit Plan consume monotonic canonical lifecycle truth without fallback regression.

## P1 — Forensic IOST audit

For the active IOST map, record:

- full scope identity;
- `current_map_id` and `current_map_cycle_id`;
- `anchor_end_ts_utc` / activation boundary;
- exact canonical target role and unrounded value;
- latest projection and map-level rebuild timestamps;
- latest included authoritative candle timestamp;
- maximum authoritative high since activation;
- first touch/cross timestamp;
- first qualifying closed-4h continuation timestamp, when applicable;
- whether any visible crossing occurred before activation;
- whether the latest crossing exists only in an open candle not yet represented by the chosen authority.

Audit only. No mutation and no chart-derived code path.

## P1 — Monotonic lifecycle invariant

Required invariant:

```text
authoritative high >= target after activation -> at least REACHED
qualifying authoritative closed 4h close > target -> PASSED
REACHED / PASSED / COMPLETED never regress to ACTIVE / NEAR / UPCOMING after pullback
```

A reached or passed target must not:

- become `active_target` again;
- return to `active_target_exit_zone`;
- produce `missing sell` as though the target is still ahead;
- contribute upcoming-target PPP or urgency;
- sort as remaining actionable upside.

Expected unfilled passed-level context:

```text
lifecycle_state=PASSED
coverage_state=PASSED_UNFILLED or MISSED_ORDER
retest_context=PULLBACK_BELOW_PASSED_LEVEL
is_active_target=false
```

## P1 — Fail closed on incomplete history

When authoritative history is missing, stale, truncated, starts after activation, or omits the selected current-candle authority:

```text
TARGET_LIFECYCLE_UNVERIFIED
```

Do not default to `UPCOMING` merely because no crossing was found in incomplete data.

Expose enough structured evidence to distinguish:

- verified active/upcoming;
- verified reached;
- verified passed;
- history unavailable;
- history stale;
- history begins after activation;
- current/open candle not represented;
- map-level projection stale or scope-mismatched.

## P1 — Open-candle contract

Choose and document one deterministic authority:

1. closed-candle-only lifecycle with an explicit current-candle-unverified state; or
2. a persisted authoritative intraperiod high merged with closed-candle continuation truth.

Reporting must not read browser chart state or call the broker to resolve this.

## P1 — Regression coverage

Add focused tests for:

- crossed target, later pullback, lifecycle remains `PASSED`;
- exact touch becomes `REACHED`;
- qualifying close above becomes `PASSED`;
- open-candle-only crossing follows the selected fail-closed contract;
- crossing before activation does not contaminate the new map cycle;
- history starts after activation and fails closed;
- stale/scope-mismatched map-level rows fail closed;
- passed level leaves active target zone;
- unfilled passed target renders missed/passed context, not missing/upcoming;
- PPP and sorting exclude passed target upside.

## P2 — Read-only production evidence

After implementation, audit IOST plus a small sample of pullback-below-target cards and record map-cycle identity, lifecycle evidence, current target selection, and rendered guidance.

No broker calls or writes.

## Dependencies / blockers

No longer blocked on creating native map-level persistence, materialization, runner, chain integration, or runtime wiring.

Remaining dependencies:

- Profit Plan must consume the canonical projection-selected map and current map-level status rather than reconstruct lifecycle independently;
- history coverage must be demonstrably aligned to the exact map activation boundary;
- the selected open-candle authority contract must be explicit;
- scope identity and freshness must fail closed.

These dependencies are implementation prerequisites, not reasons to leave the forensic audit undefined.

## Boundary

- market-data history truth and reporting consumption only;
- read-only forensic inspection;
- no broker calls;
- no broker writes;
- no order submission;
- no fib target mathematics change;
- no map selection policy change;
- no `selection_engine` change;
- no `decision_gate` change;
- no `execution_planner` change;
- no executor/agent change;
- no reporting shortcut that invents execution intent.

## Non-goals

- repairing or placing orders;
- treating TradingView as runtime authority;
- carrying target evidence across unrelated map cycles;
- solving the regression by changing only the visible label.
