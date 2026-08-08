# Multi Horizon Fib Dashboard Backlog

## GitHub Issue migration

Status: migrated

Operational status/priority is owned by GitHub Issues.

Section ownership:
- Entire file (planned read-only dashboard surfaces) -> Issue #295 (explicitly blocked/gated until the `multi_horizon_fib_backtest_v1` foundation lands)

Unmigrated executable scope:
- none

## Status

Parked behind research foundation maturity.

## Dependency

This dashboard lane depends on `multi_horizon_fib_backtest_v1` producing stable:

- swing events
- active swing rows
- fib level outcomes
- per-coin / per-horizon stats
- coverage / skip reasons

## Planned Read-Only Surfaces

- horizon coverage panel
- symbol x horizon active swing review
- fib reaction scorecards by canonical level
- context-aware bucket summaries
- checkpoint freshness and rebuild/version mismatch warnings
- 1w coverage gaps and interval availability audit

## Hard Boundaries

- dashboard only
- no broker calls
- no orders
- no decision gate
- no execution planner
- no executor
- no strategy promotion from dashboard impressions alone
