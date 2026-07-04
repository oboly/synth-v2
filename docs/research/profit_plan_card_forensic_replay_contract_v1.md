# Profit Plan Card Forensic Replay Contract v1

## Purpose

This lane makes Profit Plan card semantics reproducible, testable, and forensically explainable without changing production rendering or map-selection behavior.

The replay runner is research-only and read-only. It evaluates deterministic fixtures through existing pure helpers:

- native SHORT map candidate ranking from `src.market_data.native_short_fib_context_v1`
- Profit Plan card construction, JSON snapshot, HTML rendering, and order-row helpers from `src.reporting.manual_short_trader_profit_plan_v1`

It records invariant violations. It does not fix them.

## Runner

Module:

```bash
python -m src.research.run_profit_plan_card_forensic_replay_v1
```

Default fixture input:

```text
tests/fixtures/profit_plan_card_forensic_replay_v1/profit_plan_card_forensic_fixtures_v1.json
```

Generated output is written only under:

```text
data/research/profit_plan_card_forensic_replay_v1/<run_id>/
```

Required output files:

```text
fixture_results.jsonl
invariant_violations.csv
card_json_snapshots/
card_html_snapshots/
summary.json
manifest.json
```

Safety markers are fixed for every run:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

## Fixture Contract

Each fixture contains:

- `fixture_id`
- `symbol`
- `market`
- `current_price` or `null`
- optional current-price freshness fields
- `expected_selected_map_cycle_id`
- zero or more map-cycle snapshots
- optional synthetic open orders

Map snapshots are deterministic and small. They model native SHORT map identity, lifecycle state, anchor window, target/reload/invalidation levels, source status, and current map status.

Open orders may carry a `map_cycle_id`. The production card helper does not use that lineage today; the forensic audit uses it only to decide whether an order should count as active ladder coverage for the selected map.

## Selection Contract

The replay selects the winning map with the existing native SHORT candidate-rank semantics:

```text
ACTIVE / DEVELOPING > COMPLETED > INVALIDATED
```

Within each group, newer `anchor_end_ts_utc` wins.

The runner does not create a production replacement selection engine. It records the selected map, all candidate ranks, and any mismatch against fixture expectations.

## Invariants

`I000_EXPECTED_SELECTION`

The selected `map_cycle_id` matches the fixture expectation.

`I001_ACTIVE_MAP_SELECTION_PRIORITY`

If any active or developing map exists, completed and invalidated maps must not win.

`I002_COMPLETED_MAP_HAS_NO_ACTIVE_CONTEXT`

A completed map must not expose an active target, active target zone, active ladder requirement, or active actionability state.

`I003_INVALIDATED_MAP_NOT_ACTIVE_CONTEXT`

An invalidated map must not become active native card context.

`I004_CARD_FIELDS_SHARE_SELECTED_MAP_LINEAGE`

Active target, target zone, reload zone, and invalidation fields must come from the selected map lineage.

`I005_STALE_OR_MISSING_PRICE_BLOCKS_ACTION_OUTPUT`

Stale or missing primary price must block distance metrics and action-like entry/ladder guidance.

`I006_ORDER_ROWS_MATCH_ACTIVE_MAP_LINEAGE`

Historical or stale orders from old map cycles must not count as active ladder coverage for the selected map.

`I007_HTML_JSON_PARITY`

HTML data attributes and visible raw semantic fields must match the canonical JSON card output where the renderer exposes machine-readable state.

`I008_LIFECYCLE_SOURCE_STATUS_COMPATIBILITY`

Lifecycle state, source status, current-map status, and action semantics must be compatible.

## Severity

```text
BLOCKER
HIGH
MEDIUM
DIAGNOSTIC
```

`BLOCKER` means the card can present a wrong active/inactive lifecycle. `HIGH` means lineage, status, or action semantics are materially ambiguous. `MEDIUM` means JSON/HTML or display parity is degraded. `DIAGNOSTIC` is reserved for evidence that is useful but not directly unsafe.

## Non-Goals

This lane does not:

- modify production Profit Plan rendering
- modify native-short production map generation or lifecycle code
- modify DB, broker, account, decision, planner, executor, or runtime code
- introduce Breathline, A+ mapping, new signals, composite scores, or thresholds
- read live DB, broker, market files, or runtime outputs
- commit generated research output

Production fixes must be proposed in a later fix PR based on the ranked violations.
