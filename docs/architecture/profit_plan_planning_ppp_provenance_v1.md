# Profit Plan Planning PPP Provenance v1 (Issue #457)

## Purpose

Planning PPP is reporting-only reference math: `(target - entry) / entry * 100`
from whatever reload/re-entry level and target level a card currently
displays. Before this contract, a numeric Planning PPP carried no explicit
proof that its entry and target levels came from the same authority. The
Issue #238 partial-native + canonical-4h fallback could silently compose a
target from a transient native row and an entry from a market-only canonical
row without ever surfacing that mix.

This contract adds an explicit, immutable provenance record to every
`ProfitPlanCard` and requires source coherence before Planning PPP renders a
number.

This contract is reporting-only. It does not create market truth, account
permission, execution intent, or orders, and it does not change
`selection_engine`, `decision_gate`, `execution_planner`, or `executor`.

## `PlanningProvenance`

`src/reporting/manual_short_trader_profit_plan_v1.py` defines:

```text
PlanningProvenance:
    reference_source        # derived overall classification
    entry_source             # authority that produced the entry/reload level
    target_source             # authority that produced the target level
    source_map_id             # only when reference_source is a single native class
    source_map_cycle_id       # only when reference_source is a single native class
    source_as_of_ts_utc       # source timestamp when available
    is_coherent                # True only when entry_source == target_source
    is_hybrid_reference_only  # True when entry_source != target_source
```

Source classes:

```text
NATIVE_SHORT_CANONICAL              proven canonical native SHORT map (validated
                                     snapshot root + AVAILABLE + FRESH contract)
NATIVE_SHORT_TRANSIENT_REFERENCE    native row present/AVAILABLE but not yet
                                     proven canonical (unverified snapshot, or
                                     row not FRESH) -- native-shaped, not
                                     native-authoritative
CANONICAL_4H_NAVIGATION             canonical_fib_zone_map_latest_v1 market-only
                                     reference, or the candle-driven post-
                                     completion navigation rebuild -- neither
                                     carries native SHORT map/cycle identity
LEGACY_REFERENCE                    legacy 1d fib-map bridge row
MANUAL_REFERENCE                    operator-supplied manual swing anchor
HYBRID_REFERENCE_ONLY               derived only: entry_source != target_source
DATA_UNAVAILABLE                    derived only: either side missing
```

`make_planning_provenance(entry_source=, target_source=, ...)` derives
`reference_source`/`is_coherent`/`is_hybrid_reference_only` from the two
component sources and never fabricates `source_map_id`/`source_map_cycle_id`
for a hybrid or non-native pairing.

## Attribution: `load_zone_contexts()`

`src/reporting/run_manual_short_trader_profit_plan_v1.py::load_zone_contexts()`
is the only layer that observes which authority produced each of the entry
(`reentry_by_symbol`) and target (`fib_ext_by_symbol`) components per symbol,
across the manual-anchor, native-available, partial-native (+ canonical-4h
fallback), canonical-only, and legacy-1d composition paths. It tracks
component sources per symbol and returns
`ZoneContextLoadResult.planning_provenance_by_symbol`, threaded through
`build_cards()` into `build_profit_plan_card(planning_provenance=...)`.

When a caller does not supply `planning_provenance` explicitly (e.g. a direct
`build_profit_plan_card()` call with both `fib_ext` and `reentry` given),
`build_profit_plan_card()` infers a coherent single-source provenance from the
card's own evidence (`NATIVE_SHORT_CANONICAL` when canonical native map truth
is available, `NATIVE_SHORT_TRANSIENT_REFERENCE` otherwise) rather than
defaulting to unavailable. This keeps ordinary single-source callers working;
only `load_zone_contexts()` can produce a `HYBRID_REFERENCE_ONLY` result,
because only it sees the raw per-authority composition.

## Planning PPP semantics

1. Native-only coherent entry + target: numeric Planning PPP, `reference_source`
   is `NATIVE_SHORT_CANONICAL` or `NATIVE_SHORT_TRANSIENT_REFERENCE`.
2. Canonical-4h-only coherent entry + target: numeric Planning PPP,
   `reference_source = CANONICAL_4H_NAVIGATION` (explicitly navigation/
   reference-only, never native lifecycle authority).
3. Mixed native/canonical (or any two different source classes): Planning PPP
   is **unavailable**. `_planning_ppp_unavailable_reason()` states the two
   differing sources explicitly rather than falling through to a generic
   "no reference level" message.
4. Missing provenance (`DATA_UNAVAILABLE`): Planning PPP unavailable with a
   precise reason, same as before this contract.
5. Legacy/manual paths retain reference behavior only when their own
   provenance is coherent (`LEGACY_REFERENCE`/`MANUAL_REFERENCE`); they never
   imply native lifecycle authority.

Planning PPP remains reporting-only under all five cases: it never gates
actionability, ranking, permission, or execution (see
`docs/architecture/profit_plan_held_coverage_invariant_v1.md`).

## Actionable PPP hardening

`_actionable_ppp_eligible()` in `manual_short_trader_profit_plan_v1.py` now
explicitly requires, in addition to its existing checks (price freshness,
`actionability_state == ACTIVE`, map cycle available, no unverified rollover,
entry activation proof, an available highest active target):

- `_canonical_native_map_truth_available(card.evidence)` -- canonical native
  map identity, not merely a present `map_cycle_id`;
- `card.evidence.selected_map_tier == "CURRENT_ACTIVE_MAP"` -- a confirmed
  current selection, not a stale/non-current tier;
- `not _map_lifecycle_blocks_action(card)`, where `_map_lifecycle_blocks_action()`
  now also fails closed when `card.evidence.lifecycle_state` is
  `DATA_UNAVAILABLE`/`NONE`/`NULL`/empty -- unavailable lifecycle authority
  blocks, it does not pass by omission.

This closes the exact production regression shape observed on MOG
(2026-08-23, Issue #457): `native_map_status=AVAILABLE`, `native_map_id` and
`map_cycle_id` present, `selected_map_tier` unavailable/non-current,
`lifecycle_state=DATA_UNAVAILABLE`, entry activation proof present, otherwise
eligible. Actionable PPP is now unavailable in that shape; Planning PPP may
still be numeric if its own entry/target provenance is independently coherent
(Planning PPP does not require native lifecycle authority — see above).

Because `lifecycle_state` in the current production runner
(`_evidence_from_native_row()`) is not yet plumbed with a real per-cycle
lifecycle value and is always `DATA_UNAVAILABLE`, this hardening makes
Actionable PPP unavailable fleet-wide in production until a future change
supplies real lifecycle authority. This is the intended fail-closed behavior,
not a regression: Actionable PPP must never be numeric on absent evidence.

## UI / JSON

Operator-facing evidence labels were renamed for clarity (values/keys/JSON
schema unchanged):

```text
"Selected Fibonacci map"   -> "Selected native SHORT map"
"Fibonacci map lifecycle"  -> "Native SHORT map lifecycle"
```

The card HTML, detail/sidebar section, and JSON snapshot all read the same
`ProfitPlanCard.planning_provenance` field:

- HTML: a "Planning PPP source" metric block beside the Planning PPP value,
  plus `data-planning-reference-source`, `data-planning-entry-source`,
  `data-planning-target-source`, and `data-planning-hybrid-reference-only`
  attributes on the card.
- JSON: `symbols[].planning_provenance` (all `PlanningProvenance` fields).

## Ranking

Sort/ranking (`data-sort-ppp`, `sort_cards_action_priority`,
`sort_cards_two_timeline`) reads Actionable PPP only. Planning PPP and its
provenance never influence card ordering, including a hybrid or high-value
Planning PPP with no Actionable PPP.

## Tests

`tests/test_profit_plan_provenance_v1.py` covers native-only, canonical-4h-only,
both directions of mixed-source hybrid composition, missing provenance,
`selected_map_tier` unavailable/non-current, `lifecycle_state` unavailable and
explicitly blocking, a valid current-map/current-lifecycle actionable case,
the exact former-production (MOG) shape, ranking isolation, and HTML/JSON
field parity. `tests/test_manual_short_trader_profit_plan_v1.py` and
`tests/test_profit_plan_portfolio_composition_v1.py` were updated where they
previously assumed any populated entry+target zone pair produced a numeric
Planning PPP regardless of source.
