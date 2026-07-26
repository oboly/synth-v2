# Manual Execution Ladder — Future Readiness Audit V1

```text
HOST: devlap
MODEL: claude-sonnet-5
EFFORT: high
ROLE: auditor
THREAD: CLEAR
repo: /home/gurk/projects/synth-v2
branch: agent/canonical-agent-orchestration-contract-v1
base_sha: HEAD at audit time (working tree, no commits made by this audit)
deployment_permission: NOT_GRANTED
runtime_mutation_permission: NOT_GRANTED
db_write_permission: NOT_GRANTED
broker_private_api_permission: NOT_GRANTED
```

```text
broker_private_calls=0  broker_writes=0  order_submission=0  live_orders=0
decision_gate=none  execution_planner=none  executor=none  db_writes=0
account_config_changes=0
```

This is a read-only architecture audit. No code was modified. No orders were
submitted. No DB writes occurred. No account configuration changed.

## Scope and method

Static inspection of the manual execution ladder lane: manual execution
requests, `decision_gate`, `execution_planner`, `executor`/broker agents,
reconciliation, the ladder profile model, exchange market metadata, and
multi-account/multi-venue readiness. Method: read every source file in the
relevant packages in full (not excerpts), read the DB migrations that define
the schema, read the existing target-state design spec
(`docs/todo/manual_execution_ladder_profiles_v1.md`) and the prior live-ladder
architecture audit (`docs/status/profit_plan_live_ladder_architecture_audit_v1.md`),
and compare actual code against both. No tests were executed and no runtime
commands were issued; this is a code/schema-level review only.

## P0 implementation update (2026-07-25)

All six P0 safety-blocker backlog items (F1, F2/F3, F4/F5, F6, F9, F7/F17
partial) were implemented and tested in a follow-up session. Summary; see
`docs/todo/manual_execution_ladder_future_readiness_backlog_v1.md` for the
per-item status and exact remediation.

```text
HOST: devlap
MODEL: claude-sonnet-5
EFFORT: high
ROLE: implementer
THREAD: CONTINUE (same branch/worktree as this audit)
db_write_permission: NOT_GRANTED — migration file created, not applied
broker_private_api_permission: NOT_GRANTED — no private calls made
live_trading: NOT_GRANTED — no live execution intents generated
```

New canonical modules: `src/decision_gate/free_base_quantity_v1.py` (F1),
`src/decision_gate/sell_reservation_v1.py` (F9),
`src/decision_gate/research_provenance_v1.py` (F17),
`src/execution_planner/canonical_rounding_v1.py` (F3),
`src/market_rules/venue_execution_constraints_v1.py` (F4/F5),
`src/market_rules/bitvavo_venue_adapter_v1.py` (F5). New migration:
`db/migrations/20260725_manual_execution_ladder_p0_safety_v1.sql` (not yet
applied to any database — schema only, requires a separate,
explicitly-authorized DB-write step). 73 new tests added; full existing
suite re-run clean (3688 passed, 41 skipped, one pre-existing unrelated
failure in `tests/test_breathline_v2_canonical_campaign_archive_v1.py`
about a missing archive `run.log` file, confirmed unrelated to this work).

Notable discovery during implementation: Bitvavo's public `/v2/markets`
endpoint no longer populates `pricePrecision` (returns null). The static
fallback table this audit's F5 finding referenced
(`_BITVAVO_EUR_STATIC_PRECISION` in `price_tick_normalization_v1.py`) was
built from that now-deprecated field and is confirmed stale for at least
BTC-EUR (it implies a 0.1 EUR tick; the exchange's current explicit
`tickSize` field is "1.00", a 1 EUR tick — a 10x discrepancy). The new
venue-execution-constraints contract uses the current explicit fields
(`tickSize`, `quantityDecimals`, `minOrderInBaseAsset`,
`minOrderInQuoteAsset`) instead and does not depend on the deprecated field.
Fresh values for all 8 A+ Week-1 markets were fetched live (public endpoint,
no credentials) at 2026-07-25T19:43:17Z and seeded into the migration.

Sleeve-dependency decision (backlog item 6, F6 partial resolution): proven
that manual SELL-side base-quantity execution does not need
`portfolio_sleeve`/`sleeve_code`/legacy `account_id` at all — a SELL
reservation is about base-asset quantity tied to `trading_account_id` +
asset + venue, not about sleeve-scoped EUR capital budgeting (sleeves exist
in this codebase purely as a BUY-side EUR-allocation concept:
`portfolio_sleeve.allocated_equity_eur`/`reserved_equity_eur`). Both new P0
tables (`execution_sell_reservation`, `venue_execution_constraint`) and
both new decision_gate modules key exclusively on `trading_account_id` and
never reference `account_id`, `sleeve_code`, or `portfolio_sleeve`. This
resolves the dependency question for this new code path by removing the
dependency at the correct boundary, per the task's explicit instruction not
to invent a fallback sleeve or infer ownership by ID matching. It does
**not** resolve the broader F6 finding for the pre-existing
`execution_plan`/`portfolio_sleeve` code path (`decision_gate/repository.py`,
`execution_planner/repository.py`), which remains P2 backlog and unchanged.

This audit is a companion to, and does not duplicate,
`docs/research/aplus_week1_manual_sell_ladder_validation_20260725.md` (today's
worked dry-run against real market data for the 8 A+ Week-1 assets). That
report is the concrete instance; this document is the general-purpose
architecture assessment. The two share several conclusions by construction —
they inspect the same code — but this document classifies every finding
against the five architecture rules and produces a backlog, which the dry-run
report does not.

## Executive summary

```text
READY:                   8
PARTIAL:                 9
BLOCKED:                 9
ARCHITECTURAL_VIOLATION: 3
NOT_REQUIRED_FOR_V1:     2
```

Original classification at time of audit (2026-07-25, before P0
remediation). As of the P0 implementation update above, F1, F3, F4, F5, and
F9 are REMEDIATED (see each finding's inline status note below); F6 is
PARTIALLY REMEDIATED (resolved by non-dependency for new P0 code; unchanged
for the pre-existing `execution_plan`/`portfolio_sleeve` path); F7/F17 have
a canonical provenance record now available (`execution_research_provenance`)
but are not yet wired into an actual manual-execution-request flow, since
that flow itself (P1 backlog item 7) is still not built. The counts above
are left as originally recorded to preserve the point-in-time audit
snapshot; do not treat them as current without reading each finding's P0
status line.

Top-line conclusion: the **preview/contract layer is more mature than the
account/reservation layer underneath it**. `contract_preview_v1.py` can build
a syntactically correct, side-validated, arbitrary-leg-count SELL ladder with
absolute per-leg prices right now. But every number that ladder would need in
production — free base quantity, a single sell-side reservation record, a
minimum-order rule, a tick rule for most A+ assets, an idempotency key, a fee
reserve — either does not exist or is computed by more than one disagreeing
code path. The single most load-bearing gap is **F1: `FREE_BASE_QUANTITY` is a
whitelisted variable name with no function that computes it.**

The single most concrete safety bug found is **F3: two of the three ladder
price-rounding paths round SELL prices down (`ROUND_DOWN`) instead of up**,
which is the wrong direction per the venue's own documented side-aware rule
and would silently under-price a live sell order by up to one tick.

## 1. Architecture-rule validation

### 1.1 `selection_engine` — market-only, account-agnostic

Not deeply re-audited in this pass (out of the stated ladder-lane scope
beyond a boundary check). An existing repository test,
`tests/test_account_asset_management_v1.py::test_no_decision_gate_execution_planner_executor_imports`,
enforces at import-graph level that `decision_gate`/`execution_planner`/
`executor` are not imported by market-only modules. **READY**, on the basis of
that enforced test, not a fresh line-by-line re-derivation.

### 1.2 `decision_gate` — account-aware permission layer

**PARTIAL.** What exists and is genuinely solid:

- `src/decision_gate/sell_intent_policy_v1.py` — a pure, deterministic policy
  function (`evaluate_sell_intent_policy_v1`) that blocks on disabled
  account, live-trading-enabled, broker-write-permission-granted, hard-safety
  nonzero, source duplicates/negative-quantity/missing-price/staleness, no
  position, no available quantity, requested-exceeds-available, and
  reserved/open-order mismatch. This is a well-built **consistency check**.
- `src/decision_gate/audit_writer_v1.py` — append-only audit log, correctly
  restricted to writing only `PAPER`/`LIVE_DRY_RUN`, hard-rejects
  `LIVE_ARMED`/`LIVE` at the Python layer (`WRITABLE_EXECUTION_MODES_V1`).

What is missing (see F1, F19 below):

- Nothing in `decision_gate` (or anywhere else) **computes**
  `FREE_BASE_QUANTITY` from wallet total minus reserved. The policy module
  only *compares* two numbers it is handed by the caller
  (`reserved_quantity_base` vs `open_sell_order_remaining_base`); it does not
  derive either from a wallet snapshot.
- No kill-switch check exists as a named concept anywhere in
  `src/decision_gate/`; `account_live_trading_enabled` is the closest
  equivalent and is checked, but there is no separate global/account
  kill-switch field.
- The buy-side gate (`decision_gate_v1.py`) and the sell-side policy
  (`sell_intent_policy_v1.py`) are two separate, non-unified code paths with
  different input shapes; there is no single `evaluate_decision` entrypoint
  a manual-execution-request caller could call regardless of side.

### 1.3 `execution_planner` — execution intent → immutable order intents

**PARTIAL, with one confirmed correctness bug (F3).**

`contract_preview_v1.py` is the most complete lane: it validates ladder-level
ascending/descending price order per side, requires fractions to sum to
exactly 1, supports arbitrary leg counts, and for `EXIT_LADDER` correctly
sizes each leg as a fraction of **base quantity** (not notional) — this is
the correct sizing basis for a sell ladder. However:

- Its tick quantizer (`_quantize_to_tick`, line 145-150) always rounds
  `ROUND_DOWN` regardless of side. For a SELL leg this rounds the limit price
  *down*, which is the wrong direction — `src/market_rules/price_tick_normalization_v1.py`
  documents and implements the correct rule (`TARGET_SELL` → `ROUND_UP`) but
  `contract_preview_v1.py` does not import or use that module at all. It has
  its own, side-unaware quantizer.
- No minimum-notional or minimum-quantity check exists anywhere in this
  package (`ExecutionPlannerConfig` in `models.py` has no such field).
- It does not fetch private broker data directly — correct, confirmed by
  reading `contract_preview_v1.py` and its runner in full; all inputs are
  passed in as explicit dataclass fields.

The separate DB-writing planner (`execution_planner_v1.py` +
`execution_planner/repository.py`) is a different, older lane that predates
the ladder work: `build_execution_plan()` handles `PREPARE_PLAN` and
`PLACE_PASSIVE_LIMIT` only — it has no ladder concept at all. Its repository
(`create_plan_with_reservation`) reserves EUR against `portfolio_sleeve`
keyed by legacy `account_id` (see F6).

### 1.4 `executor` / agents — order handling only

**PARTIAL, but the parts that exist are safely built.**

- `src/executor/` (`executor_v1.py`, `paper_contract_v1.py`) is 100% paper —
  `validate_canonical_paper_contract` explicitly raises
  `LiveExecutionPrerequisitesUnavailable` the instant `execution_mode ==
  "LIVE"`, before any symbol/price lookup. It has no ladder awareness at all
  — it only fills single-order `SPREAD_CAPTURE_PASSIVE` and
  `CLOSE_POSITION_MARKET_PAPER` plans, never a multi-leg ladder.
- `src/execution/limit_sell_ladder_v1.py`'s `place_limit_sell_ladder_orders`
  **unconditionally raises `PermissionError`** regardless of
  `confirm_real_orders` — "Direct limit sell ladder broker placement is
  disabled. Live execution prerequisites are unavailable." This is a
  deliberate, hardcoded, correctly fail-closed block. **READY** as a safety
  property.
- `src/execution/bitvavo_client.py` correctly gates every private call behind
  two independent env-var checks (`SYNTH_BROKER_PRIVATE_READ_PERMISSION`,
  `SYNTH_BROKER_WRITE_PERMISSION`) plus explicit non-empty credential
  presence, and a `private_read` auth context can never call
  `place_order`/`cancel_order` even with both permissions granted
  (`_require_private_write_permission` explicitly rejects
  `auth_context == "private_read"`). **READY.**
- No canonical **live** order executor exists anywhere in the repository —
  confirmed consistent with `docs/status/profit_plan_live_ladder_architecture_audit_v1.md`'s
  own conclusion ("There is no verified reusable live order executor yet").
- Broker identifier capture / response normalization: `bitvavo_client.py`
  returns raw Bitvavo JSON from `place_order`/`get_order`; no normalization
  layer exists yet because there is no live executor to normalize for.

### 1.5 Reconciliation

**PARTIAL.** `src/operations/run_broker_reserved_reconciliation_report_v1.py`
is a solid read-only comparator: it reconciles the latest broker balance
snapshot's `reserved_amount` against the latest broker order snapshot's
summed `remaining_quantity_base` for open SELL LIMIT orders, per symbol, and
classifies `MATCH`/`MISMATCH`/`RESERVED_WITHOUT_OPEN_ORDER`/
`OPEN_ORDER_WITHOUT_RESERVED`. It also hard-fails (non-zero exit) if broker
write permission is granted or if any "hard safety" row
(`execution_sell_plan.broker_submission_enabled`, `live_trading_enabled`,
`execution_sell_intent.execution_enabled`) is non-zero — a good belt-and-
braces pattern.

What it does not do (because nothing upstream produces the concepts yet):

- No comparison of **intended vs submitted** (there is no "intended" record
  — no `manual_execution_request` or per-leg intent table exists).
- No idempotency-key or client-order-ID tracking anywhere in the codebase —
  grepped and confirmed absent.
- No restart-recovery logic — nothing persists "this process already
  attempted to submit leg N" across a process restart, because nothing
  submits yet.
- No partially-filled-leg reconciliation for a multi-leg ladder specifically
  (only a snapshot-vs-snapshot balance/order comparison, not an order-by-
  order fill-state machine).

## 2. Checklist findings (one line each; see §3 for full detail on non-READY items)

| # | Question | Classification | Detail |
|---|---|---|---|
| 1 | SELL ladders support explicit absolute target prices? | PARTIAL | `contract_preview_v1` yes (absolute `price:fraction` pairs); `execution_ladder` profile model no (anchor-relative `price_offset_bps` only, by deliberate v1 design). The two lanes disagree — see F7. |
| 2 | Arbitrary leg counts supported deterministically? | READY | Both lanes: N legs driven by however many are supplied/active; only a sum-to-100%/10000bps constraint, no hardcoded count. |
| 3 | Allocation base-quantity or quote-notional? | PARTIAL | `contract_preview_v1` EXIT_LADDER = base-quantity fraction (correct for sells). `execution_ladder` profile model = quote-notional only (`allocation_bps`), base qty always derived, never the direct basis. See F8. |
| 4 | Open SELL reservations represented once and only once? | ARCHITECTURAL_VIOLATION | No canonical SELL reservation record exists (unlike `capital_reservation` for BUY EUR). `sell_intent_policy_v1` compares two independently-sourced numbers rather than owning one. See F9. |
| 5 | Free base quantity has one canonical definition? | BLOCKED | F1 — no function computes it anywhere. |
| 6 | Account/portfolio/sleeve/credential mappings explicit and future-safe? | ARCHITECTURAL_VIOLATION | Credential layer (`trading_account_credential`) is genuinely well-built and future-safe. Portfolio/sleeve layer is not — see F6. |
| 7 | Multiple trading accounts can use the same strategy output without cross-account coupling? | PARTIAL | Ladder profiles/sizing rules are correctly per-`trading_account_id`. `decision_gate`/`execution_planner` still key sleeve state off legacy `account_id`. `PlannedExecution` carries both IDs simultaneously with no enforced equivalence — see F6. |
| 8 | Bitvavo-specific precision logic isolated behind a venue adapter? | PARTIAL | Broker HTTP calls are isolated (`bitvavo_client.py`). The static precision fallback table is a hardcoded `if venue == "bitvavo"` string check inside a venue-agnostically-named module, not a formal adapter interface. See F10. |
| 9 | Market metadata has tick size / step size / min qty / min notional / order types / TIF / freshness / provenance? | BLOCKED | Tick size: yes. Step size, min notional, order-type/TIF-per-market: no column, no logic. Min qty: column exists, unused. Freshness: generic `updated_ts`, no staleness check anywhere. Provenance: good for price (`TickRule.source`), absent elsewhere. See F5, F14. |
| 10 | Metadata absence fails closed? | PARTIAL | For price ticks: yes, genuinely well done (`MISSING_TICK_RULE` surfaced, never guessed). For qty-step/min-notional: nothing to fail closed on — they're not checked at all, so absence is invisible rather than surfaced. |
| 11 | Price/quantity rounding side-aware and safe? | ARCHITECTURAL_VIOLATION | The correct side-aware module exists and is unused by both code paths that actually build SELL ladder prices. See F3. |
| 12 | Fees reserved for BUY and SELL? | BLOCKED | No fee field, no fee-reserve calculation, anywhere. See F16. |
| 13 | Repeated Process actions idempotent? | BLOCKED | No `manual_execution_request` table or idempotency key exists yet. See F8/F12. |
| 14 | Stale wallet/open-order snapshots rejected? | PARTIAL | `sell_intent_policy_v1` has a hard `source_freshness_ok` gate — good design — but nothing centrally computes it with a named staleness threshold; every caller must supply it itself. See F11. |
| 15 | Execution requests and plans immutable and auditable? | PARTIAL | `decision_gate_audit_log` is append-only (good). `execution_plan` rows are mutated in place via `update_plan()`, not versioned. No `manual_execution_request` table exists yet (the one artifact the design spec requires to be immutable). |
| 16 | Historical ladder profile revisions remain reproducible? | READY | `execution_ladder_leg` is versioned (`profile_version`, unique per `(profile, version, leg_number)`); design doc mandates new-version-not-mutation and code matches. |
| 17 | Profile config can reference external research targets without promoting into selection/decision weights? | BLOCKED | Not supported today; `ALLOWED_ANCHOR_TYPES` is a one-member frozenset. See F7. |
| 18 | Research provenance + explicit user override attachable to an execution request? | BLOCKED | No schema field anywhere carries this. Today's A+ override had to be recorded in a standalone markdown report, not the system. See F17. |
| 19 | Live execution requires explicit authorization boundary separate from preview? | READY | Strongly enforced in multiple independent places (F-none; this is a strength, see §4). |
| 20 | Paper preview and live submission use the same planner contract? | NOT_REQUIRED_FOR_V1 | No live submission path exists yet, by deliberate staged design (`profit_plan_live_ladder_architecture_audit_v1.md` Batches A–D). Nothing to compare yet. |
| 21 | Partial failures across ladder legs represented and reconciled? | BLOCKED | No ladder-aware executor (paper or live) exists at all — only single-order paper fills. See F18. |
| 22 | Cancel/replace a separate explicit workflow? | BLOCKED | `action_type` enum includes `CANCEL_ORDER` but no builder or repository method ever produces or acts on one tied to a specific broker order. See F13. |
| 23 | Runtime host assumptions documented and enforced? | PARTIAL | Documented in `AGENTS.md` and prior reports; fail-closed via missing master key on devlap. No explicit in-code host-identity check. See F14 (shared with metadata-provenance numbering above — this is the host-ops instance). |

## 3. Detailed non-READY findings

Each finding lists: file/module/table, current behavior, future risk,
correct owning layer, minimal remediation, whether it blocks the current A+
manual sell ladder, whether it blocks future multi-account usage.

### F1 — `FREE_BASE_QUANTITY` has no canonical resolver

**P0 status (2026-07-25): REMEDIATED.** `src/decision_gate/free_base_quantity_v1.py`
implements `resolve_free_base_quantity()` exactly as recommended below,
plus the double-subtraction guard the follow-up task additionally required:
it subtracts only `APPROVED_NOT_SUBMITTED` local reservations (see F9) and
fails closed with `REASON_RECONCILIATION_PENDING` if any reservation is in
the ambiguous `SUBMITTED_AWAITING_RECONCILIATION` state, rather than
guessing whether the broker's own `available` figure already reflects it.
Tested in `tests/test_free_base_quantity_v1.py` and end to end in
`tests/test_manual_execution_p0_integration_v1.py`.

- File/module: `src/execution_ladder/resolver.py` (`ALLOWED_VARIABLE_KEYS`
  whitelists `FREE_BASE_QUANTITY` but `resolve_sizing_suggestion` only
  handles `MANUAL_ONLY`/`FIXED_QUOTE`/`PCT_OF_VARIABLE` via a caller-supplied
  `variable_values` dict); `src/decision_gate/sell_intent_policy_v1.py`
  (`available_quantity_base`/`reserved_quantity_base` are policy *inputs*,
  not derived outputs).
- Current behavior: nothing in the repository computes
  `wallet_total_base_quantity - reserved_in_open_sell_orders`. Every consumer
  of `FREE_BASE_QUANTITY` must supply it externally with no shared formula.
- Future risk: two callers (e.g., a dashboard preview and a real gate
  evaluation) can compute "free base quantity" differently — one from the
  exchange's own `available` balance field, another from
  `wallet_total - DB reserved row` — and silently diverge, leading to an
  oversized sell request that the exchange rejects, or worse, one that
  succeeds against stale data.
- Correct owning layer: `decision_gate` (this is account-aware permission
  data, not planner or ladder-profile logic).
- Minimal remediation: add one function,
  `resolve_free_base_quantity(wallet_total_base, reserved_open_sell_base) ->
  Decimal`, in `src/decision_gate/`, and make it the only permitted producer
  of the `FREE_BASE_QUANTITY` sizing variable.
- Blocks current A+ manual sell ladder: **YES** — this is literally the
  value the task's `FREE_BASE_QUANTITY` requirement needs.
- Blocks future multi-account usage: **YES** — without a single formula,
  each new account risks a bespoke, silently-different computation.

### F2 — Three parallel ladder-building implementations with inconsistent invariants

- Files: `src/execution_planner/contract_preview_v1.py`
  (`_build_ladder_legs`, fractions sum to exactly `1`);
  `src/execution_ladder/resolver.py` (`resolve_ladder_preview`,
  `allocation_bps` sum to exactly `10000`); `src/execution/limit_sell_ladder_v1.py`
  (`validate_limit_sell_ladder_levels`, `quantity_pct` sum only required
  `<= 100`, not `== 100`).
- Current behavior: three independent code paths build a "ladder" with three
  different validation rules, three different anchor concepts (absolute
  price / anchor+bps offset / absolute price+offset-pct again), and three
  different rounding behaviors.
- Future risk: a fix applied to one path (e.g., correcting the tick-rounding
  direction, see F3) will not propagate to the others; a future maintainer
  extending "the ladder logic" may edit the wrong one, or all three
  divergently.
- Correct owning layer: `execution_planner` should be the single owner of
  leg allocation, price/quantity rounding, and validation (per the stated
  rule 3). `execution_ladder` should supply profile/anchor data into it, not
  re-implement leg-building; `execution/limit_sell_ladder_v1.py`'s CSV-driven
  builder should either be retired or explicitly reduced to a thin adapter
  that calls the planner.
- Minimal remediation: do not merge all three in one pass (that is a
  broader refactor than this audit's scope). Minimal first step: make all
  three call `src/market_rules/price_tick_normalization_v1.normalize_price_to_tick`
  for price rounding instead of each having its own quantizer, and document
  which of the three is authoritative for new manual-execution-request work
  (recommendation: `contract_preview_v1`'s `EXIT_LADDER` path, since it is
  already the only one with base-quantity-fraction sizing and side-validated
  ascending/descending price checks).
- Blocks current A+ manual sell ladder: **YES** — using the wrong one of the
  three (or the CSV script) silently changes which invariants are enforced.
- Blocks future multi-account usage: **PARTIAL** — this is a correctness
  risk for any single account too, but the risk compounds as more callers
  are added across accounts.

### F3 — SELL ladder price rounding is not side-aware in two of three ladder-building paths

**P0 status (2026-07-25): REMEDIATED.** `src/execution_planner/canonical_rounding_v1.py`
is now the single rounding service (`round_price_for_side`,
`round_quantity_down`, `round_leg_for_side`). Both named files were
redirected to it: `contract_preview_v1._quantize_to_tick` now delegates and
is side-aware for both the single-leg passive-price path (a second, related
instance of the same bug, also fixed) and the ladder-leg path;
`limit_sell_ladder_v1.quantize_decimal` also delegates. The existing
`limit_sell_ladder_v1` golden test's literal price assertion was updated
from the old (incorrect) `"0.452"` to the corrected `"0.453"`, and a direct
regression test (`test_build_limit_sell_ladder_orders_never_rounds_price_down`)
was added. `execution_ladder/resolver.py` gained a new
`round_ladder_preview()` composition function using the same service
(its existing raw `resolve_leg_limit_price`/`resolve_ladder_preview`
functions are unchanged, to avoid breaking their existing 489-line test
suite — callers that intend a real leg must additionally call
`round_ladder_preview()`). A static AST-based regression test
(`tests/test_canonical_rounding_v1.py::TestNoSellPathStillUsesIncorrectRoundDown`)
proves neither file contains a local `to_integral_value(rounding=ROUND_DOWN)`
price quantizer anymore.

- Files: `src/execution_planner/contract_preview_v1.py:145-150,298`
  (`_quantize_to_tick` always `ROUND_DOWN`, applied unconditionally to every
  leg including SELL legs at line 298); `src/execution/limit_sell_ladder_v1.py:48-51`
  (`quantize_decimal` always `ROUND_DOWN` for both price and amount,
  regardless of side).
- Current behavior: both paths round a SELL limit price *down* to the
  nearest tick. `src/market_rules/price_tick_normalization_v1.py` documents
  and correctly implements the opposite rule: `TARGET_SELL` must round
  `ROUND_UP` — "Sell limit orders must never be placed below the analytical
  target." Neither ladder-building path imports or uses this module.
- Future risk: this is a live-money-relevant bug the moment either path is
  wired to a real order submission — it would place sell orders up to one
  tick below the intended price, systematically giving away value on every
  fill, and it is silent (no error, no warning) because both paths currently
  treat `ROUND_DOWN` as simply "the rounding mode," not as a side-unsafe
  choice.
- Correct owning layer: `execution_planner` (rounding direction is
  explicitly assigned to this layer by rule 3).
- Minimal remediation: replace the local quantizers in both files with a
  call into `market_rules.normalize_price_to_tick(price, tick_rule,
  price_role=PRICE_ROLE_TARGET_SELL)` for SELL legs (and
  `PRICE_ROLE_REENTRY_BUY` for BUY legs), so there is exactly one rounding
  rule implementation in the repository.
- Blocks current A+ manual sell ladder: **YES.**
- Blocks future multi-account usage: **PARTIAL** — the bug affects any
  account, but is not itself account-count-dependent.

### F4 — No minimum-order-quantity or minimum-notional enforcement anywhere

**P0 status (2026-07-25): REMEDIATED.** `venue_execution_constraint`
(migration `db/migrations/20260725_manual_execution_ladder_p0_safety_v1.sql`)
adds `min_base_quantity` and `min_quote_notional` columns; the migration
also seeds real, freshly-fetched values for all 8 A+ Week-1 markets (see F5
below for provenance). `canonical_rounding_v1.round_leg_for_side()` checks
both, strictly after rounding as required, and returns deterministic
rejection reasons (`BELOW_MIN_BASE_QUANTITY`, `BELOW_MIN_QUOTE_NOTIONAL`).
Not yet wired into `contract_preview_v1`'s dataclass pipeline directly
(that would require a broader signature change to
`ExecutionMarketContextPreview`, deferred — see the backlog's note); today
it is available as a composable post-processing step any caller can apply
to a preview's legs.

- Files: `db/migrations/20260603_multi_account_asset_foundation_v1.sql`
  (`venue_market.min_order_qty` column exists, `DECIMAL(20,10)`, nullable, no
  min-notional column at all); `src/execution_planner/models.py`
  (`ExecutionPlannerConfig` has no min-qty/min-notional field);
  `src/execution_ladder/resolver.py`, `src/execution/limit_sell_ladder_v1.py`
  (neither reads `venue_market.min_order_qty` or any notional floor).
- Current behavior: a ladder leg can be built and would pass every existing
  validation with a quantity or notional value below what Bitvavo would
  actually accept.
- Future risk: silent broker rejection at submission time (best case) or, if
  a future minimum-notional column is added but not read everywhere, dust
  orders that succeed but are economically meaningless.
- Correct owning layer: `execution_planner` (explicitly named in rule 3:
  "owns... minimum quantity, minimum notional").
- Minimal remediation: (1) add a `min_notional_quote` column to
  `venue_market`; (2) populate `min_order_qty`/`min_notional_quote` for at
  least the markets currently in active use; (3) add a deterministic
  `MIN_QTY_UNDERSIZED`/`MIN_NOTIONAL_UNDERSIZED` rejection reason, checked
  per leg, in whichever path is designated authoritative per F2.
- Blocks current A+ manual sell ladder: **YES** — already the single largest
  blocker identified in today's dry-run report, affecting all 8 assets.
- Blocks future multi-account usage: **YES** — this is asset/venue-scoped,
  so every account trading the same asset inherits the same gap, and the
  risk surface grows with account count.

### F5 — Tick size and quantity step-size metadata incomplete

**P0 status (2026-07-25): REMEDIATED for the 8 A+ Week-1 markets.**
`src/market_rules/venue_execution_constraints_v1.py` is the new canonical,
fail-closed (MISSING/STALE/FRESH) contract; `src/market_rules/bitvavo_venue_adapter_v1.py`
isolates Bitvavo-specific parsing behind it. Tick size, quantity step size,
min base quantity, and min quote notional for DEEP-EUR, RED-EUR, NEAR-EUR,
NOT-EUR, TAO-EUR, POL-EUR, LDO-EUR, and BTC-EUR were fetched live from
Bitvavo's public `/v2/markets` endpoint (no credentials required) at
2026-07-25T19:43:17Z and seeded into the new migration — all 8 returned
`status=trading`. This fetch also revealed that Bitvavo's `pricePrecision`
field (which the old static fallback table was built from) is now
deprecated and returns null; the new contract uses the current explicit
`tickSize`/`quantityDecimals`/`minOrderInBaseAsset`/`minOrderInQuoteAsset`
fields instead and does not depend on the deprecated one. The old
`_BITVAVO_EUR_STATIC_PRECISION` table in `price_tick_normalization_v1.py`
was left unmodified (out of scope for this pass; it is superseded by the
new contract for any new callers, not deleted).

- File: `src/market_rules/price_tick_normalization_v1.py`
  (`_BITVAVO_EUR_STATIC_PRECISION` has 3 of the 8 A+ Week-1 assets: RED,
  LDO, BTC; DEEP/NEAR/NOT/TAO/POL have neither a DB row nor a static
  fallback entry). Separately: `venue_market.qty_precision` exists in
  schema but no function analogous to `tick_size_from_precision` converts it
  to a usable step-size Decimal anywhere in the codebase — grepped and
  confirmed absent.
- Current behavior: for 5 of 8 A+ assets, any price-rounding call returns
  `MISSING_TICK_RULE` (correctly surfaced, not silently guessed). For
  quantity step-size, there is no equivalent concept implemented at all —
  base-quantity values are never rounded to an exchange-valid step anywhere
  in the ladder-building paths.
- Future risk: unsafe submission (rejected or, worse, silently truncated by
  the exchange in a way this codebase never explicitly validated) for any
  quantity that isn't already step-aligned by coincidence.
- Correct owning layer: market metadata / venue adapter, feeding
  `execution_planner`.
- Minimal remediation: sync `price_precision`, `qty_precision`, and
  `min_order_qty` for the 8 A+ assets from Bitvavo's public `/v2/markets`
  endpoint (no credentials required) into `venue_market`; add a
  `qty_step_from_precision()` counterpart to `tick_size_from_precision()` and
  a `resolve_qty_step_rule()` counterpart to `resolve_tick_rule()`.
- Blocks current A+ manual sell ladder: **YES.**
- Blocks future multi-account usage: **NOT_REQUIRED_FOR_V1** as a
  multi-account-specific concern (it's asset/venue-scoped, not
  account-scoped) but remains a blocker regardless of account count.

### F6 — `account_id` vs `trading_account_id` ID-space fragmentation, no join table

**P0 status (2026-07-25): PARTIALLY REMEDIATED, by non-dependency.** See the
"P0 implementation update" section above for the full reasoning. Both new
P0 tables (`execution_sell_reservation`, `venue_execution_constraint`) and
both new decision_gate modules (`free_base_quantity_v1.py`,
`sell_reservation_v1.py`) key exclusively on `trading_account_id` and never
reference `account_id`, `sleeve_code`, or `portfolio_sleeve` — proven by
`tests/test_manual_execution_p0_architecture_boundaries_v1.py`'s import and
schema checks. This removes the dependency for new SELL-reservation/
free-quantity code entirely rather than inventing a fallback mapping. The
underlying fragmentation in the pre-existing `execution_plan`/
`portfolio_sleeve` code path (`decision_gate/repository.py`,
`execution_planner/repository.py`) is unchanged and remains P2 backlog item
13.

- Files: `src/decision_gate/repository.py` (`fetch_sleeve_state`,
  `fetch_duplicate_state`, `fetch_open_order_flag` all keyed by `account_id`);
  `src/execution_planner/repository.py` (`create_plan_with_reservation` reads
  and writes `portfolio_sleeve` by `account_id`, while
  `_validate_plan_contract` simultaneously requires a positive
  `trading_account_id` on the same `PlannedExecution` row); versus
  `src/account_provisioning/*`, `src/account/private_read_credential_resolver_v1.py`,
  `db/migrations/20260603_multi_account_asset_foundation_v1.sql`,
  `db/migrations/20260628_execution_ladder_profiles_v1.sql` — all
  consistently keyed by `trading_account_id`. No `CREATE TABLE` for
  `portfolio_sleeve` or `exchange_account` exists anywhere under
  `db/migrations/` — both predate migration tracking. Confirmed in today's
  dry-run report that only `exchange_account.account_id = 1` has ever
  existed.
- Current behavior: `PlannedExecution` and `execution_plan` rows carry
  **both** `account_id` and `trading_account_id` simultaneously with no
  enforced relationship between them; `docs/architecture/execution_plan_fail_closed_prerequisite_v1.md`
  explicitly states "Legacy `account_id` values do not satisfy
  `trading_account_id`" but no code anywhere verifies the two actually refer
  to the same real-world account for a given row.
- Future risk: this "works" today by convention (there is exactly one row in
  each space, and they happen to correspond). The moment a second trading
  account is provisioned, `decision_gate`/`execution_planner`'s
  `portfolio_sleeve` reads have no deterministic way to know which
  `account_id` corresponds to the new `trading_account_id` — a hardcoded
  guess or an accidental cross-account read/write becomes possible.
- Correct owning layer: `account`/`account_provisioning` (identity
  foundation beneath `decision_gate`).
- Minimal remediation: add an explicit `account_id -> trading_account_id`
  mapping table with a `UNIQUE` constraint on both columns, and require
  every `decision_gate`/`execution_planner` repository call that currently
  takes a bare `account_id` to resolve it through that table rather than
  accepting it as an unchecked caller-supplied value. (Longer-term:
  migrate `portfolio_sleeve` itself onto `trading_account_id`, but that is a
  larger migration outside this audit's minimal-remediation scope.)
- Blocks current A+ manual sell ladder: **PARTIAL** — works by accident for
  the single existing account; this audit flags it as unverified rather than
  safe-by-inspection.
- Blocks future multi-account usage: **YES** — hard blocker for onboarding a
  second trading account through this lane.

### F7 — Ladder anchor is anchor-relative only; no reviewed path for absolute externally-supplied targets

- Files: `src/execution_ladder/models.py`
  (`ALLOWED_ANCHOR_TYPES = frozenset({"NATIVE_SHORT_ANCHOR_HIGH"})`);
  `src/execution_ladder/resolver.py` (`resolve_anchor_price` only handles
  that one anchor type; `resolve_leg_limit_price` only computes
  `anchor_price * (1 + offset_bps/10000)`); `docs/todo/manual_execution_ladder_profiles_v1.md`
  (explicitly: "Do not add `ENTRY_PRICE`, `PPP_PRICE`,
  `ACTIVE_SELL_TARGET_PRICE`, manual anchors, or other anchor sources until a
  separate requirement exists" — this is a deliberate v1 restriction, not an
  oversight).
- Current behavior: the DB-backed profile model (the lane the manual
  execution tray is designed around) structurally cannot represent an
  externally-supplied absolute target price such as an A+ Week-1
  expected-rise/spike level. The separate preview-only lane
  (`contract_preview_v1`'s `--ladder-levels`) *can* take arbitrary absolute
  prices, but that lane has no profile/versioning/provenance model at all —
  it is a raw CLI argument.
- Future risk: using the preview CLI as a stand-in "real" path for
  externally-sourced targets sidesteps the profile model's deliberate
  governance without a reviewed extension, and produces no persisted,
  versioned, or provenance-tagged record of what target was used or where it
  came from.
- Correct owning layer: `execution_ladder` (profile model) — this is a
  governance decision requiring review, not a mechanical code change.
- Minimal remediation: do not repurpose `contract_preview_v1`'s CLI
  ladder-levels for anything other than one-off preview demonstrations. If
  external research targets are to be supported, add a reviewed
  `anchor_type = EXTERNAL_RESEARCH_TARGET_V1` (name illustrative) with
  mandatory `source_provenance_json`, `override_scope`, and `promoted`
  fields, following the external-note governance path already defined in
  `AGENTS.md` ("external note -> normalized research label -> validation
  report -> optional feature/candidate").
- Blocks current A+ manual sell ladder: **YES** — this is precisely the
  governance gap today's dry-run report's "explicit override, this instance
  only" flow had to work around out-of-band.
- Blocks future multi-account usage: **NOT_REQUIRED_FOR_V1** — orthogonal to
  account count.

### F8 — Ladder-profile allocation basis is quote-notional only; no base-quantity-basis option

- File: `src/execution_ladder/models.py` (`LadderLeg.allocation_bps` —
  "Quote-notional share of final trade amount"); `resolver.py`
  (`resolve_ladder_preview` always computes `allocated = quote_amount *
  allocation_bps / 10000`, then derives base quantity from that notional and
  the leg's limit price — base quantity is always a *derived* value, never
  the direct sizing basis).
- Current behavior: for a sell ladder sized directly off "70% of free base
  quantity" (the A+ task's actual requirement), the DB-backed profile model
  has no way to express "this leg gets X% of my *base quantity*" — it can
  only express "this leg gets X% of a *quote amount*," which then has to be
  divided by a resolved price to get back to base quantity. `contract_preview_v1`'s
  `EXIT_LADDER` path does support base-quantity-fraction sizing directly and
  correctly.
- Future risk: for volatile assets, computing quote-notional-per-leg first
  and dividing by price second, versus taking a direct percentage of owned
  base quantity, produces materially different results if computed at
  different times/prices — a subtle sizing-basis bug risk for the exact use
  case this ladder lane targets.
- Correct owning layer: `execution_ladder` (profile model) /
  `execution_planner` (final resolution).
- Minimal remediation: add an `allocation_basis` field to
  `execution_ladder_leg` (`QUOTE_NOTIONAL_BPS` | `BASE_QUANTITY_BPS`),
  defaulting to today's behavior, and have the resolver branch on it.
- Blocks current A+ manual sell ladder: **PARTIAL** — `contract_preview_v1`'s
  lane already does this correctly; only the DB-backed profile lane is
  missing it.
- Blocks future multi-account usage: **NOT_REQUIRED_FOR_V1** — orthogonal to
  account count.

### F9 — No canonical, single-owner SELL-side reservation record

**P0 status (2026-07-25): REMEDIATED.** `execution_sell_reservation`
(migration) plus `src/decision_gate/sell_reservation_v1.py` implement the
full state machine (`APPROVED_NOT_SUBMITTED` ->
`SUBMITTED_AWAITING_RECONCILIATION` -> `OPEN` -> `PARTIALLY_FILLED` ->
terminal), idempotent creation keyed on a caller-supplied
`idempotency_key` (DB-unique), and a single `reconcile_reservation_state()`
entrypoint that is the only permitted state-transition path and that fails
closed (`AmbiguousBrokerStateError`) unless the caller confirms exactly one
matching broker row. `tests/test_manual_execution_p0_architecture_boundaries_v1.py::TestNoParallelReservationPath`
statically confirms no other module writes this table's `reservation_state`.

- Files: `src/execution_planner/repository.py`
  (`create_plan_with_reservation` writes `capital_reservation` — EUR-only,
  BUY-oriented); `src/decision_gate/sell_intent_policy_v1.py`
  (`evaluate_sell_intent_policy_v1` only *compares*
  `reserved_quantity_base` against `open_sell_order_remaining_base`, both
  supplied by the caller — neither is written or owned by this module).
- Current behavior: for BUY-side EUR, there is exactly one authoritative
  reservation table (`capital_reservation`) with a clear writer
  (`create_plan_with_reservation`). For SELL-side base quantity, there is no
  equivalent — no table records "N units of asset X are reserved by pending
  sell plan Y." The only signal is a real-time comparison against the
  broker's own open-order snapshot, which is a **consistency check**, not a
  **reservation**.
- Future risk: two concurrent sell-ladder requests (or a request plus a
  stale/duplicate retry) have no shared ledger to prevent double-reserving
  the same base quantity before either one reaches the broker — the mismatch
  would only be caught after the fact, if a snapshot happens to be refreshed
  in between.
- Correct owning layer: `decision_gate` (reservation bookkeeping is
  account-aware permission state, matching the pattern already used for
  BUY-side EUR).
- Minimal remediation: extend `capital_reservation` (or add a parallel
  `base_quantity_reservation` table) to record SELL-side base-quantity
  reservations the same way BUY-side EUR reservations are recorded today,
  written at plan-creation time and released at fill/cancel time.
- Blocks current A+ manual sell ladder: **YES.**
- Blocks future multi-account usage: **YES** — the race gets worse with more
  concurrent account activity.

### F10 — Bitvavo-specific precision fallback is not behind a formal venue-adapter interface

- File: `src/market_rules/price_tick_normalization_v1.py`
  (`resolve_tick_rule_from_static`: `if venue == "bitvavo": ...` — a hardcoded
  string check inside a module named venue-agnostically).
- Current behavior: broker HTTP calls are correctly isolated in
  `bitvavo_client.py`. The static precision table is not: it is a
  module-level dict gated by a plain `if` on the venue string, with no
  `VenueAdapter` protocol/interface a second venue could implement.
- Future risk: adding a second venue means adding more `if venue ==
  "..."` branches throughout `market_rules` rather than swapping an adapter
  implementation — a maintainability/multi-venue-readiness gap, not a
  correctness bug today (Synth currently only trades on Bitvavo).
- Correct owning layer: market metadata / venue adapter layer.
- Minimal remediation: not urgent given single-venue scope; when a second
  venue is actually planned, introduce a `VenuePrecisionSource` protocol with
  one implementation per venue, resolved by a registry keyed on `venue`,
  rather than branching inline.
- Blocks current A+ manual sell ladder: **NO** — single-venue (Bitvavo)
  today.
- Blocks future multi-account usage: **NOT_REQUIRED_FOR_V1** — this is a
  multi-*venue* concern, not multi-*account*; classified `NOT_REQUIRED_FOR_V1`
  until a second venue is actually in scope.

### F11 — No centrally computed staleness/freshness check

- File: `src/decision_gate/sell_intent_policy_v1.py`
  (`SellIntentPolicyInput.source_freshness_ok: bool` — a hard gate, correctly
  blocking with `SOURCE_STALE` when false).
- Current behavior: the *gate* is well-designed, but the field is a caller-
  supplied boolean; no shared function in the repository computes "is this
  wallet/open-order snapshot fresh enough" against a named threshold. Each
  caller (dashboard, CLI preview, future manual-execution-request handler)
  would have to invent its own staleness computation.
- Future risk: inconsistent staleness thresholds across callers — one caller
  might consider a 10-minute-old snapshot fresh, another might not, with no
  single source of truth for what "fresh" means for this lane.
- Correct owning layer: `decision_gate` (or a shared snapshot-freshness
  utility it depends on).
- Minimal remediation: add one function,
  `is_snapshot_fresh(snapshot_ts_utc, max_age_seconds) -> bool`, with a named
  default threshold, and require every caller of
  `evaluate_sell_intent_policy_v1` to derive `source_freshness_ok` from it
  rather than computing its own.
- Blocks current A+ manual sell ladder: **NO** (today's dry-run never
  reached this check — it was blocked earlier by missing credentials).
- Blocks future multi-account usage: **NOT_REQUIRED_FOR_V1** — orthogonal to
  account count, but worth fixing before any live wiring regardless.

### F12 — `manual_execution_request` (the tray's core artifact) does not exist yet

**P0 status (2026-07-26): PARTIALLY REMEDIATED.** The P0 safety remediation
commit reviewed on 2026-07-25
(`docs/reviews/manual_execution_ladder_p0_implementation_review_20260725.md`)
was BLOCK/REJECT: it built `free_base_quantity_v1`, `sell_reservation_v1`,
`venue_execution_constraints_v1`, and `canonical_rounding_v1` as
disconnected primitives with no request parent to bind them to (finding
B1). `src.manual_execution.manual_execution_request_v1` now implements the
canonical immutable request contract this finding names, and
`src.manual_execution.manual_execution_service_v1.process()` is the one
call graph from a persisted request through
`src.decision_gate.manual_execution_gate_v1` (the trusted FREE_BASE_QUANTITY
producer B2 found missing) to a decision_gate-approved
`contract_preview_v1.build_execution_plan_preview()` call — see
`docs/reviews/manual_execution_ladder_p0_remediation_implementation_20260726.md`
for the exact call graph, tests, and remaining gaps. Still open: atomic
SELL reservation creation, reconciliation, provenance binding, the
plan-snapshot table, and the ladder-profile/anchor fields from
`docs/todo/manual_execution_ladder_profiles_v1.md`'s full design spec —
none of those are implemented by this change.

- Reference: `docs/todo/manual_execution_ladder_profiles_v1.md` — a complete,
  already-reviewed P0 design spec for exactly this table, its lifecycle
  states, and its immutability requirement. No corresponding migration,
  model, or repository exists anywhere in `src/` or `db/migrations/`.
- Current behavior: there is no persisted record of a user's manual
  sell/buy request prior to planning — "Process" cannot be idempotent (F13)
  and provenance/override (F17) cannot be attached, because there is no row
  to attach either property to.
- Future risk: without this table, every property the design spec assigns to
  it (immutability, idempotency, lifecycle status, provenance) has to be
  reinvented ad hoc per caller, exactly as happened in today's A+ dry-run
  (the override had to be recorded in a standalone markdown file).
- Correct owning layer: a new table/module, upstream of `decision_gate`, per
  the existing design spec.
- Minimal remediation: implement the four tables already specified in
  `docs/todo/manual_execution_ladder_profiles_v1.md` (`execution_sizing_variable_ref`
  and `execution_sizing_rule` already exist per `db/migrations/20260628_execution_ladder_profiles_v1.sql`;
  `manual_execution_request` and its plan-snapshot table do not).
- Blocks current A+ manual sell ladder: **YES** — this is the P0 backlog
  item the whole lane is waiting on.
- Blocks future multi-account usage: **YES** — the design spec already scopes
  it per-account; without it, no account has an idempotent, auditable manual
  request path.

### F13 — Cancel/replace is not implemented as a workflow

- Files: `src/execution_planner/models.py` (`ExecutionPlannerConfig.action_type`
  enum includes `CANCEL_ORDER`, but no function in `execution_planner_v1.py`
  or `repository.py` ever constructs or acts on a `CANCEL_ORDER` plan);
  `src/execution_planner/repository.py` (`cancel_stale_preplan` only cancels
  a **plan row** in `IDLE`/`PREPARE_PLAN` state — it never touches a broker
  order); `src/execution/bitvavo_client.py` (`cancel_order` exists at the
  broker-client level but nothing above it calls it).
- Current behavior: "cancel" exists at exactly one layer (broker client) and
  at exactly one other, unrelated layer (stale internal plan cleanup) — there
  is no path connecting an approved cancel-and-replace decision to an actual
  broker cancel call.
- Future risk: any future repair/reprice flow ("cancel this ladder leg and
  resubmit at a new price") has nothing to build on yet; a hasty
  implementation might call `bitvavo_client.cancel_order` directly from a
  UI/reporting handler, bypassing `decision_gate`/`execution_planner`
  entirely (exactly the forbidden shortcut named in `AGENTS.md`).
- Correct owning layer: `execution_planner` decides *that* a cancel/replace
  is needed and produces the intent; `executor` performs the actual broker
  cancel call.
- Minimal remediation: not urgent until live submission exists at all (no
  order has ever been placed by this system, so nothing needs cancelling
  yet). When Batch D (live executor) is implemented, cancel/replace should be
  designed as an explicit, separate intent type from the start rather than
  retrofitted.
- Blocks current A+ manual sell ladder: **NO** (out of scope — the task is
  prepare-but-do-not-submit; nothing exists yet to cancel).
- Blocks future multi-account usage: **NOT_REQUIRED_FOR_V1.**

### F14 — Runtime host assumptions are documented but not enforced in code

- Reference: `AGENTS.md` ("Odroid is the lightweight runtime host... DB host
  owns MariaDB... identify host ownership... avoid duplicate writers");
  `src/account_provisioning/credential_crypto_v1.py`
  (`load_master_key_from_env` fail-closes when the master key is absent —
  confirmed today on devlap).
- Current behavior: host ownership is a documentation/process convention,
  correctly fail-closed for the one case that matters most (credential
  material only decrypts where the master key is present). There is no
  in-code assertion of "this process must be running on host X" for other
  runtime concerns (e.g., duplicate-writer prevention for a future live
  executor).
- Future risk: low today (no live writer exists to duplicate). Becomes
  relevant once a live executor is deployed to a specific host — nothing
  would currently stop it from being accidentally started twice, on two
  hosts, against the same account.
- Correct owning layer: deployment/runtime ops, not application code, for
  most of this; the credential fail-closed behavior already covers the
  highest-risk case.
- Minimal remediation: when a live executor is built, add an explicit
  single-writer lock (e.g., a DB advisory lock or a `systemd`-enforced
  singleton) rather than relying on documentation alone.
- Blocks current A+ manual sell ladder: **NO.**
- Blocks future multi-account usage: **NOT_REQUIRED_FOR_V1** — this is a
  live-deployment concern, not a multi-account data-model concern.

### F15 — No per-leg partial-fill representation for a ladder (no ladder-aware executor, paper or live)

- Files: `src/executor/executor_v1.py` (`execute_plan_paper` handles exactly
  two single-order desired actions: `SPREAD_CAPTURE_PASSIVE`,
  `CLOSE_POSITION_MARKET_PAPER` — neither is a ladder); no
  `execute_ladder_paper` or equivalent exists anywhere.
- Current behavior: even in PAPER mode, there is no way to represent "leg 1
  of 3 filled, leg 2 open, leg 3 not yet placed" — the entire executor
  concept is single-order.
- Future risk: when a ladder-aware executor is eventually built (paper or
  live), partial-fill state machines and reconciliation need to be designed
  for multi-leg ladders from the start; retrofitting onto the current
  single-order model would be a larger rewrite than building it correctly
  now.
- Correct owning layer: `executor` (fill/partial-fill state) +
  reconciliation (cross-checking against broker open-order snapshots).
- Minimal remediation: not urgent for a prepare-but-do-not-submit task; flag
  for the executor design phase (see backlog P1/P2).
- Blocks current A+ manual sell ladder: **NO** (task is preview-only).
- Blocks future multi-account usage: **NOT_REQUIRED_FOR_V1.**

### F16 — Fees are not reserved or modeled anywhere

- Files: `src/execution_planner/models.py` (`ExecutionPlannerConfig` — no
  `fee_bps`/`fee_reserve` field); `src/execution_ladder/resolver.py`,
  `src/execution/limit_sell_ladder_v1.py` — neither subtracts a fee estimate
  from notional/quantity anywhere; grepped the repository for
  `fee` in execution-related modules and found no fee-reserve calculation.
- Current behavior: a computed sell quantity/notional assumes 100% of the
  traded value is realized, with no Bitvavo maker/taker fee headroom; a
  computed buy notional assumes the full requested amount is available with
  no fee buffer.
- Future risk: at the margin (e.g., right at a minimum-notional boundary),
  ignoring fees could make an order that "passes" planner validation
  actually fail exchange-side, or leave a small unaccounted EUR/asset
  shortfall after fills.
- Correct owning layer: `execution_planner` (fee reserve is explicitly named
  in the task's inspection list and belongs alongside tick/step/min-notional
  logic).
- Minimal remediation: add a configurable `fee_bps` to
  `ExecutionPlannerConfig` and apply it as a haircut to available
  quantity/notional before leg allocation.
- Blocks current A+ manual sell ladder: **NO** for a preview-only exercise,
  but should be fixed before any live wiring.
- Blocks future multi-account usage: **NOT_REQUIRED_FOR_V1.**

### F17 — No schema field anywhere carries research provenance / override scope for an execution request

**P0 status (2026-07-25): PARTIALLY REMEDIATED.** `execution_research_provenance`
(migration) plus `src/decision_gate/research_provenance_v1.py` implement
exactly the fields specified: source classification/path/sha256/timestamp,
ingestion status, `selection_weight`/`decision_weight` (DB-CHECK-enforced to
0), override scope, approving user/timestamp, allowed assets/side,
preview/live permission (`live_permission` DB-CHECK-enforced to 0), and
expiry/single-use/consumed tracking. `build_research_provenance_record()`
and `validate_override_for_use()` are pure, fully tested
(`tests/test_research_provenance_v1.py`) functions; a `ResearchProvenanceRepository`
persists/consumes records. Still open: this record is a standalone "child"
artifact with no parent to attach to yet, since `manual_execution_request`
(P1 backlog item 7) does not exist — wiring a real manual execution flow to
create and check one of these records is future work, not done here.

- Files: none — grepped for `provenance`, `override_scope`, `promoted`
  across `src/execution*`, `src/decision_gate/`, and found no such field in
  any dataclass or table.
- Current behavior: exactly as observed operationally today — when an A+
  Week-1 research target needed to be used for a ladder price, the
  provenance and explicit one-time-override justification had to be written
  into a standalone markdown report by hand, because no system field exists
  to carry it alongside the actual execution artifact.
- Future risk: without a structured field, provenance/override information
  is easy to lose or omit under time pressure in a future, less-careful
  invocation — exactly the failure mode `AGENTS.md`'s external-note
  governance rule exists to prevent.
- Correct owning layer: whatever table implements F12
  (`manual_execution_request`) plus the ladder-profile anchor extension in
  F7.
- Minimal remediation: when F12/F7 are implemented, include
  `source_provenance_json`, `override_scope`, and `promoted` as first-class
  columns from the start, not retrofitted later.
- Blocks current A+ manual sell ladder: **YES** — same governance gap as F7,
  different angle (this one is about the request/audit trail, F7 is about
  the anchor-type restriction).
- Blocks future multi-account usage: **NOT_REQUIRED_FOR_V1.**

## 4. What is already correct (do not re-litigate these)

- **Live execution requires an explicit authorization boundary, enforced in
  at least four independent places**: `LiveExecutionPrerequisitesUnavailable`
  raised before any PAPER-path price/credential work;
  `place_limit_sell_ladder_orders` hardcoded `PermissionError` regardless of
  caller-supplied flags; `BitvavoClient._require_private_write_permission`
  rejecting `private_read` auth context outright; `decision_gate_audit_writer_v1`
  refusing to write `LIVE_ARMED`/`LIVE` execution modes at the Python layer.
  This is a genuine, multi-layered strength — no single bypass point exists.
- **Tick-size resolution fails closed correctly**: `MISSING_TICK_RULE` is
  surfaced as an explicit status, never silently guessed from price
  magnitude, and the module's own docstring states this invariant plainly.
- **Historical ladder-profile revisions are correctly immutable and
  reproducible**: `profile_version` + `leg_number` uniqueness, explicit "new
  version, not mutation" rule in both the design spec and the schema.
- **Credential-to-account binding is genuinely future-safe**:
  `trading_account_credential` is uniformly keyed to `trading_account_id`,
  enforces exactly-one-ACTIVE-credential-per-(account, venue, scope),
  explicitly forbids withdrawal-capable credentials, and separates
  read-only from order-write permission scope at the binding-validation
  layer, independent of any single caller's discipline.
- **Arbitrary ladder leg counts are already supported deterministically** in
  both ladder-building lanes — the corrected 3-leg A+ instruction (down from
  an earlier assumed 4) required no code change to accommodate.

## 5. Cross-reference

Today's worked example against real market data for the 8 A+ Week-1 assets
(`docs/research/aplus_week1_manual_sell_ladder_validation_20260725.md`) hit
F1, F3 (as a latent bug, not yet triggered because it never reached
execution), F4, F5, and F6 in practice, blocking all 8 assets. That report is
the concrete instance of the same conclusions reached here by a different
route (execution against real data vs. static code/schema reading). See the
companion backlog for prioritized remediation:
`docs/todo/manual_execution_ladder_future_readiness_backlog_v1.md`.
