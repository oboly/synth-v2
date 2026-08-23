# Fib Coverage Classification Contract v1

Owner: reporting coverage/provenance classification (Profit Plan).
Related: Issue #489 (defect), Issue #486 (production audit that found it),
`docs/architecture/publication_cohort_membership_terminology_contract_v1.md`.

## Problem

Before this contract, Profit Plan reported a single generic reason —
`FIB_MAP_SYMBOL_MISSING` (`short_context_coverage_status`) /
`ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING` (`short_context_input_status`) —
whenever no Fib authority row existed for a rendered card's symbol. That
status does not say *why* the row is absent: a broken canonical publication
and an account overlay symbol that was never enrolled in the canonical
cohort looked identical to the operator.

The #486 production audit reconciled a real render as:

```text
60 rendered cards
53 canonical 4h publication-cohort/core-sensor markets
  19 resolve native SHORT first
  34 canonical 4h navigation-only
7 account/overlay extension markets with no Fib row
```

The seven no-row cards are not necessarily broken. They may be intentionally
rendered because they are held, have an open order, or are a manual account
asset — while never having been enrolled in the canonical publication
cohort. This contract makes that distinction truthful and explicit, without
changing which markets are selected or enrolled.

## Non-goal

This contract classifies existing truth. It does not enroll assets, does not
change publication cohort or native SHORT scope membership, and does not
touch `selection_engine`, `decision_gate`, `execution_planner`, `executor`,
or account overlay semantics. Absence of a Fib row must never be silently
"fixed" by widening the rendered universe.

## Canonical facts consumed (read-only)

- `is_market_selected` / `is_core_sensor` on `ProfitPlanCard` — already
  resolved from `asset.is_publication_cohort` (via
  `publication_cohort_contract_v1`) and core-sensor enrollment, attached by
  `apply_portfolio_account_evidence()`.
- `is_wallet_held` / `is_portfolio_asset` on `ProfitPlanCard` — already
  resolved from the rendered account's wallet balance and
  `account_asset.is_portfolio_member`, attached by the same function.
- `open_order_count_by_market` — already resolved account-scoped open-order
  presence (`AccountScopedShortDashboardContext`).
- `native_short_scope_state_by_symbol` — `scope_support_state`
  (`SUPPORTED` / `NOT_APPLICABLE`) read from the native SHORT context rows
  CSV, matching
  `src.market_data.native_short_scope_status_v1.NativeShortScopeSupportEventState`.
- `short_context_coverage_status` / `short_context_input_status` — the
  existing canonical-row / native-row lifecycle status already computed by
  `load_zone_contexts()` (`_canonical_fib_row_status()` and the native
  SHORT context bridge).
- `canonical_fallback_usable` — whether `load_zone_contexts()`'s
  Planning-PPP fallback (Issue #238) actually backfilled usable canonical
  4h levels underneath a partial native row. `apply_fib_coverage_classification()`
  derives this from `card.planning_provenance.entry_source` /
  `target_source == PLANNING_SOURCE_CANONICAL_4H_NAVIGATION` — **not** from
  `short_context_coverage_status`/`short_context_input_status`, which stay
  pinned to native SHORT's own lifecycle status and do not change when the
  fallback fires underneath them. Reconstructing fallback usability from
  those strings alone would wrongly report a real canonical fallback as
  `NATIVE_SHORT_CONTEXT_PARTIAL`/`NATIVE_SHORT_EXPECTED_BUT_MISSING`.

No enrollment truth is recomputed or duplicated in reporting; this module
(`src/reporting/fib_coverage_classification_v1.py`) only combines
already-resolved facts into one explicit classification.

## Classification structure

`FibCoverageClassification` (frozen, one instance per rendered card):

| Field | Values |
|---|---|
| `canonical_fib_scope_state` | `ENROLLED` \| `NOT_ENROLLED` |
| `canonical_fib_row_state` | `AVAILABLE` \| `STALE` \| `UNAVAILABLE` \| `ABSENT` \| `SOURCE_UNAVAILABLE` \| `NOT_APPLICABLE` |
| `native_short_scope_state` | `SUPPORTED` \| `NOT_APPLICABLE` \| `UNKNOWN` |
| `native_short_row_state` | `AVAILABLE` \| `PARTIAL` \| `ABSENT` |
| `rendered_scope_origin` | `GLOBAL_PUBLICATION_COHORT` \| `ACCOUNT_POSITION_HELD` \| `ACCOUNT_OPEN_ORDER` \| `ACCOUNT_ASSET_CONFIG` \| `UNKNOWN` |
| `fib_coverage_reason` | see below |

`fib_coverage_reason` (final, mutually exclusive, precedence order):

1. `FIB_MAP_AVAILABLE` — canonical or native authority is usable. This
   includes the case where the canonical row itself is `AVAILABLE`, the
   native row itself is `AVAILABLE`, **and** the case where neither row
   status string says so but `canonical_fallback_usable` (see below) proves
   canonical 4h data actually filled in usable levels underneath a partial
   native row via the Planning-PPP fallback (Issue #238). This always takes
   precedence — even over a `SUPPORTED`+`PARTIAL`/`ABSENT` native gap (rule
   6).
2. `FIB_MAP_STALE` / `FIB_MAP_UNAVAILABLE` — canonical row exists but is not
   usable (pre-existing, already-truthful reasons; unchanged by this
   contract).
3. `FIB_MAP_EXPECTED_BUT_MISSING` — canonical publication cohort or
   core-sensor enrolled, but no row exists.
4. `ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE` — not enrolled; rendered only via an
   account overlay (held asset, open order, or manual asset config).
5. `FIB_MAP_NOT_ENROLLED` — not enrolled and no known overlay origin
   (fallback; expected to be rare given the account-scoped market universe).
6. `NATIVE_SHORT_EXPECTED_BUT_MISSING` / `NATIVE_SHORT_CONTEXT_PARTIAL` —
   canonical 4h has no usable authority for this card (canonical row state
   is `NOT_APPLICABLE` **and** `canonical_fallback_usable` is false — see
   below), and `native_short_scope_state == SUPPORTED` with
   `native_short_row_state` of `ABSENT` (missing) or `PARTIAL` respectively.
   **Never** collapsed into `NOT_APPLICABLE` — that would silently suppress
   a real supported-native coverage gap. When a usable canonical 4h row (or
   fallback) *does* exist, the overall reason stays `FIB_MAP_AVAILABLE`
   instead (rule 1 takes precedence); the native gap remains visible only
   through `native_short_scope_state` / `native_short_row_state`, which are
   always populated independently of `fib_coverage_reason`.
7. `NOT_APPLICABLE` — native SHORT is not expected to support this symbol
   (`native_short_scope_state` is `NOT_APPLICABLE` or `UNKNOWN`) or legacy
   1d context already supplies authority; canonical-row absence is not the
   operative reason for this card.
8. `FIB_MAP_SOURCE_UNAVAILABLE` — the whole canonical Fib source
   (`short_context_coverage_status == FIB_MAP_SOURCE_MISSING`) failed to
   load. **Never** classified as `FIB_MAP_EXPECTED_BUT_MISSING`,
   `ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE`, or `FIB_MAP_NOT_ENROLLED` — a source
   outage is not per-symbol evidence for or against enrollment, so no
   per-symbol enrollment-relative conclusion is drawn. This applies
   regardless of the symbol's own enrollment/overlay facts (enrolled or
   not, held/order/manual or none): while the source cannot be read,
   coverage for *every* symbol is `FIB_MAP_SOURCE_UNAVAILABLE`, distinct
   from the per-row `ABSENT` state used once the source is confirmed
   readable and simply lacks this symbol's row (`FIB_MAP_SYMBOL_MISSING`).

Native SHORT unsupported/not-enrolled (`native_short_scope_state ==
NOT_APPLICABLE`) is tracked independently of `fib_coverage_reason` and never
overrides a valid canonical 4h navigation row — see items E/F below. Native
SHORT *supported*-but-missing/partial (`native_short_scope_state ==
SUPPORTED`) is the opposite failure mode guarded by rule 6 above: it must
never be silently absorbed into `NOT_APPLICABLE` just because canonical 4h
also has no usable row.

## Wiring

- `classify_fib_coverage()` — pure function, one symbol at a time.
- `apply_fib_coverage_classification(cards, ...)` — read-only post-processing
  step (same `dataclasses.replace` pattern as
  `apply_portfolio_account_evidence`), run immediately after
  `apply_portfolio_account_evidence()` so the overlay flags are populated.
  Sets `ProfitPlanCard.fib_coverage` and, when the classification identifies
  a coverage gap, appends the matching human-readable reason to
  `card.reasons` — the single source both HTML (`<ul class='reasons'>`) and
  JSON (`symbols[].reasons`) render, so they can never diverge.
- JSON: `symbols[].fib_coverage_classification` (per-card) and
  `fib_coverage_summary` (per-reason counts across the render) in
  `build_json_snapshot()`. `summarize_fib_coverage_reasons()` sums to exactly
  the classified card count — no double-counting a card across reasons.

## Existing behavior preserved

`short_context_coverage_status` / `short_context_input_status` (the legacy
generic statuses, e.g. `FIB_MAP_SYMBOL_MISSING`) are **not** changed by this
contract — they continue to drive existing scenario/action derivation and
`summarize_short_context_coverage()` exactly as before. This classification
is additive: a new, independently-computed field that answers *why*, without
touching the blast radius of the pre-existing generic status.
