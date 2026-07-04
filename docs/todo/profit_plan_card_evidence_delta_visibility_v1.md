# TODO — Profit Plan Card Evidence Delta Visibility v1

## Status

done / parked

P0-C implements presentation/card-traceability only. The card now exposes
canonical evidence and deterministic current-vs-previous snapshot deltas without
changing strategy, selection, lifecycle, account, execution, order, broker, or
DB policy.

## Sources

- `src/reporting/manual_short_trader_profit_plan_v1.py`
- `src/reporting/run_manual_short_trader_profit_plan_v1.py`
- `tests/test_manual_short_trader_profit_plan_v1.py`
- `docs/research/profit_plan_card_forensic_replay_contract_v1.md`
- `src/research/run_profit_plan_card_forensic_replay_v1.py`

## Current state / facts

- Card JSON includes `evidence` and `delta` objects.
- HTML exposes matching evidence attributes for selected map identity, lifecycle,
  price timestamp/freshness, and delta status/types.
- Missing provenance is explicit as `DATA_UNAVAILABLE`.
- Delta comparison is deterministic and requires an explicit previous canonical
  Profit Plan JSON snapshot via `--previous-json`.
- No previous snapshot yields `delta_status=NO_PREVIOUS_SNAPSHOT`.
- Changed fields are semantic field paths such as `evidence.map_cycle_id`,
  `target_exit_zone`, and `order_summary.matching_buys`.
- Material delta types are limited to:
  `MAP_CHANGED`, `MAP_LIFECYCLE_CHANGED`, `TARGET_CHANGED`,
  `RELOAD_ZONE_CHANGED`, `INVALIDATION_CHANGED`, `PRICE_MATERIAL_CHANGE`,
  `ORDER_COVERAGE_CHANGED`, `SIGNAL_CONTEXT_CHANGED`,
  `DATA_FRESHNESS_CHANGED`.

## Open tasks by priority

No active P0-C implementation tasks remain.

Parked follow-up, if a later lane owns the missing source fields:

- Add `native_map_id` when the runtime native SHORT context source exposes it
  canonically.
- Add native context publication/generation/update timestamps when those fields
  exist canonically.
- Add order-to-map-cycle lineage only in a dedicated order lineage lane, not in
  P0-C.
- Add native lifecycle/source-status validation only in a dedicated validation
  lane, not in P0-C.

## Blockers / dependencies

- `native_map_id` is not available in the current production
  `NativeShortContextRow`; P0-C reports it as `DATA_UNAVAILABLE`.
- Native context publication/generation timestamps are not available in the
  current production row source; P0-C reports them as `DATA_UNAVAILABLE`.
- Order-map-cycle lineage remains forensic evidence only until a separate order
  lineage lane defines the runtime contract.

## Boundary

- Read-only presentation/card traceability only.
- No live trading.
- No broker calls.
- No broker writes.
- No order submission.
- No selection changes.
- No decision_gate changes.
- No execution_planner changes.
- No executor/agent changes.
- No account, wallet, or DB schema changes.
- No map-selection rank/priority changes.
- No invalidation, target, reload, price-distance, or ladder threshold changes.
- No Breathline, A+, composite scores, or new market signals.

## Non-goals

- Strategy promotion.
- Selection/ranking policy.
- Lifecycle/source-status validation.
- Order-to-map-cycle lineage.
- Execution intent or order mutation.
- Generated dashboard or research artifacts in git.
