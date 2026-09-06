# Fib-Map-Bound Trade First-Fill Binding Adapter V1 (Issue #753 Phase B7)

## Purpose

Closes recommended next slice 4 of
`docs/status/issue_753_paper_acceptance_blocker_v1.md`: a decision_gate-owned
adapter that constructs and persists one immutable `FibMapBoundTradeV1` (B1,
`src/decision_gate/fib_map_bound_trade_v1.py`) at the first strategy-owned
BUY fill, from real B4/B5 ownership/fill lineage plus caller-supplied
canonical Fib map evidence, persisted through the existing B6 repository
(`src/decision_gate/fib_map_bound_trade_repository_v1.py`).

`src/decision_gate/fib_map_bound_trade_first_fill_binding_adapter_v1.py` is
the new module.

## Scope (what B7 is)

- `CanonicalFibMapEvidenceV1` -- a narrow, explicit dataclass carrying
  already-selected canonical ShortTF Fib map fields (identity, anchors,
  breakout/invalidation prices, full target ladder). Field names/units mirror
  the existing canonical native-map fields already in
  `src/market_data/native_short_fib_context_v1.py` and
  `native_short_fib_context_snapshot_v1.py`'s `PROVENANCE_FIELDS` -- this is a
  data carrier for evidence the caller already resolved, not a parallel
  geometry definition, and this module never selects or recomputes a map.
- `build_fib_map_bound_trade_v1_from_first_fill(...)` -- pure construction,
  no I/O, no repository, no execution intent.
- `bind_fib_map_bound_trade_on_first_fill_v1(...)` -- construct then persist
  through the unchanged B6 `FibMapBoundTradeRepositoryV1`.
- `derive_fib_map_bound_trade_binding_id_v1(...)` -- deterministic
  `binding_id` (sha256 over the exact fill lineage + source fill + map
  identity); identical inputs always derive the same id.

## Input contract (smallest explicit shape)

- `fill_event: StrategyOwnedInventoryEventV1` (#752/#753 B5) -- the real BUY
  fill establishing ownership and lineage. Every identity field on the
  binding (`trading_account_id`, `venue`, `market`, `strategy_bucket_id`,
  `strategy_id`, `strategy_version`, `trade_id`, `source_execution_plan_id`,
  `source_buy_fill_id`) is copied verbatim from this event -- never
  re-derived, never separately supplied, so there is no code path that could
  disagree with the real fill lineage about its own identity.
- `map_evidence: CanonicalFibMapEvidenceV1` -- the canonical map evidence
  (see above). `venue`/`market` are cross-checked against the fill event's
  own `venue`/`market`.
- `bound_ts_utc` is always `fill_event.occurred_ts_utc` -- never wall clock.
  This keeps construction a pure, deterministic function of its inputs and
  gives "no future data relative to first fill" one unambiguous reference
  point: every map evidence timestamp (`map_asof_ts_utc`,
  `map_published_at_utc`, `anchor_start_ts_utc`, `anchor_end_ts_utc`) must be
  `<= bound_ts_utc`, and `map_asof_ts_utc` must be no older than
  `max_map_evidence_age_seconds` (default: `DEFAULT_PRIMARY_STALE_HOURS`
  from `native_short_fib_context_v1.py`, i.e. the same 12h freshness bar
  market_data already applies to the primary 4h authority). Callers may
  tighten this boundary, but may never relax it beyond the canonical limit.
- No `StrategyOwnedInventoryPositionV1` or prior-events history is required.
  "Owned position" and "fill lineage" identity are the same source here (the
  fill event itself); B6's existing unique keys (lineage, source fill,
  binding_id), not a second position lookup in this module, are what enforce
  first-fill/no-rebind semantics (see below).

## First-fill / no-rebind semantics

This module does not re-implement "is this really the first fill" as a
separate history-scanning check. Enforcement is entirely the B6 repository's
existing unique keys, which this adapter relies on unchanged:

- Replaying the identical fill + identical map evidence is idempotent --
  `record_fib_map_bound_trade_v1` returns the already-persisted row, no
  second insert.
- Calling this adapter again for the same lineage with materially different
  map evidence (e.g. a rolled-over map cycle) fails closed with
  `FibMapBoundTradeConflictError("FIB_MAP_BOUND_TRADE_LINEAGE_CONFLICT")`.
- Calling it for a different lineage that happens to reuse the same source
  fill fails closed the same way (`..._SOURCE_FILL_CONFLICT`).

## Target-ladder immutability

`map_evidence.target_levels` is frozen into the binding verbatim, in full.
This adapter never filters to "currently active" or "not yet reached"
targets -- that is exit-decision progression state, owned by B2
(`fib_map_bound_exit_decision_v1.py`) and its caller, and must never leak
into what gets bound at B7 time. Binding a partial ladder here would silently
change the contract's meaning after earlier targets were already consumed by
B2, which this adapter must not do.

## Validation layering

- Structural geometry/identity (non-empty ids, aware timestamps, anchor
  ordering, finite positive prices, non-empty ascending target ladder) is
  owned entirely by B1's `validate_fib_map_bound_trade_v1` and is not
  duplicated here -- this adapter builds the full candidate binding, then
  calls B1's validator once.
- This adapter owns only what B1 cannot see from a bare `FibMapBoundTradeV1`:
  fill-lineage shape (`_validate_fill_event_for_binding`), that the fill is
  actually a BUY (`SOURCE_FILL_NOT_BUY_SIDE`), fill/map identity cross-check
  (`FIB_MAP_EVIDENCE_IDENTITY_MISMATCH`), and map-evidence freshness
  (`FIB_MAP_EVIDENCE_FROM_THE_FUTURE`, `FIB_MAP_EVIDENCE_STALE`).

## Layer boundaries respected

```text
market_data / research  -> owns map selection/geometry; this module only
                            consumes an already-selected CanonicalFibMapEvidenceV1
decision_gate            -> owns this construct+persist adapter (new) and the
                            unchanged B6 persistence it calls
execution_planner        -> untouched
executor                 -> untouched
```

## What B7 does not do

- Does not select or recompute a canonical Fib map.
- Does not infer ownership from wallet balance -- lineage comes only from a
  real, caller-supplied `StrategyOwnedInventoryEventV1`.
- Does not create execution intent, does not import `execution_planner` or
  `executor` (enforced by a static-import test).
- Does not build or wire the exact-path PAPER acceptance harness (B8) -- see
  `docs/status/issue_753_paper_acceptance_blocker_v1.md` for why B8 remains
  blocked independently of B7.

## Safety markers

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=extended (new construct+persist adapter, reuses B6 persistence)
execution_planner=none
executor=none
production_runtime_activation=0
```

## Next slice

`#753 B8` -- the exact-path PAPER acceptance harness -- remains blocked. B7
gives it a real (not fabricated) construct+persist path from a
`StrategyOwnedInventoryEventV1` to a `FibMapBoundTradeV1`, but B8 still needs
a real automatic-BUY PAPER fill to reach `FILLED` end-to-end, and no code
path produces that yet: B5.5's PAPER order-placement adapter is explicitly
submission-time-only and never returns `FILLED` -- there is still no
`ACTIVE -> FILLED` PAPER reconciliation for a resting automatic-BUY order.
See `docs/status/issue_753_paper_acceptance_blocker_v1.md` for the full
detail; B7 does not change that blocker.
