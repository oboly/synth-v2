# TODO — Invalidation confirmation backtest v1

## GitHub Issue migration

Status: migrated

Operational status/priority is owned by GitHub Issues.

Section ownership:
- Entire file (graded invalidation-confirmation backtest) -> Issue #291

Unmigrated executable scope:
- none

## Status

Queued research task.

Do not implement yet.

## Purpose

Backtest invalidation confirmation as a graded state machine instead of a binary touch/invalid rule.

Core question:

Which invalidation regime gives the best balance between:

- avoiding bad setups early
- not throwing away winners after short liquidity sweeps
- limiting drawdown
- preserving target-hit probability after recovery

## Architecture boundary

Belongs in:

- research / market-only

Forbidden:

- account data
- broker data
- decision_gate imports
- execution_planner imports
- executor imports
- live behavior changes
- reporting changes

## Research states

- VALID
- INVALIDATION_TOUCHED
- SOFT_INVALIDATION_ZONE
- RECOVERY_ALLOWED
- CONFIRM_PENDING
- SOFT_BREACH_RECOVERED
- HARD_INVALIDATED
- FALSE_INVALIDATION
- TRUE_INVALIDATION

## Rule families to test later

- binary touch/close rules
- soft-zone buffer rules
- recovery-window rules
- combined confirmation regimes
- exception rules:
  - liquidity sweep
  - shallow breach
  - fast reclaim
  - wick-only
  - higher timeframe
  - structure-held

## Expected future outputs

- data/research/invalidation_backtest_v1/events.csv
- data/research/invalidation_backtest_v1/rule_comparison.csv
- data/research/invalidation_backtest_v1/soft_zone_comparison.csv
- data/research/invalidation_backtest_v1/example_soft_recoveries.csv
- data/research/invalidation_backtest_v1/example_true_invalidations.csv
- data/research/invalidation_backtest_v1/manifest.json
- docs/research/invalidation_confirmation_backtest_v1.md

## Important

Do not choose a final live rule unless results are overwhelmingly clear.

Do not change live invalidation behavior yet.

Do not change Profit Plan reporting yet.

Do not continue this before the current production pipeline stability work is clean.
