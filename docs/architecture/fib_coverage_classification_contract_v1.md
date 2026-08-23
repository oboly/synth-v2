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

No enrollment truth is recomputed or duplicated in reporting; this module
(`src/reporting/fib_coverage_classification_v1.py`) only combines
already-resolved facts into one explicit classification.

## Classification structure

`FibCoverageClassification` (frozen, one instance per rendered card):

| Field | Values |
|---|---|
| `canonical_fib_scope_state` | `ENROLLED` \| `NOT_ENROLLED` |
| `canonical_fib_row_state` | `AVAILABLE` \| `STALE` \| `UNAVAILABLE` \| `ABSENT` \| `NOT_APPLICABLE` |
| `native_short_scope_state` | `SUPPORTED` \| `NOT_APPLICABLE` \| `UNKNOWN` |
| `native_short_row_state` | `AVAILABLE` \| `PARTIAL` \| `ABSENT` |
| `rendered_scope_origin` | `GLOBAL_PUBLICATION_COHORT` \| `ACCOUNT_POSITION_HELD` \| `ACCOUNT_OPEN_ORDER` \| `ACCOUNT_ASSET_CONFIG` \| `UNKNOWN` |
| `fib_coverage_reason` | see below |

`fib_coverage_reason` (final, mutually exclusive, precedence order):

1. `FIB_MAP_AVAILABLE` — canonical or native authority is usable.
2. `FIB_MAP_STALE` / `FIB_MAP_UNAVAILABLE` — canonical row exists but is not
   usable (pre-existing, already-truthful reasons; unchanged by this
   contract).
3. `FIB_MAP_EXPECTED_BUT_MISSING` — canonical publication cohort or
   core-sensor enrolled, but no row exists.
4. `ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE` — not enrolled; rendered only via an
   account overlay (held asset, open order, or manual asset config).
5. `FIB_MAP_NOT_ENROLLED` — not enrolled and no known overlay origin
   (fallback; expected to be rare given the account-scoped market universe).
6. `NOT_APPLICABLE` — native SHORT or legacy 1d context already supplies
   authority; canonical-row absence is not the operative reason for this
   card.

Native SHORT unsupported/not-enrolled (`native_short_scope_state ==
NOT_APPLICABLE`) is tracked independently of `fib_coverage_reason` and never
overrides a valid canonical 4h navigation row — see items E/F below.

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
