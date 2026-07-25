# Manual Execution Ladder — Future Readiness Backlog V1

Status: backlog only. No implementation performed by this document.

Source audit: `docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md`.
Finding IDs (`F1`–`F17`) refer to that document's §3.

Ordering: P0 safety blockers, P1 correctness and reconciliation, P2
multi-account/multi-venue readiness, P3 usability and profile flexibility.
Within a priority tier, items are listed in the order they should be tackled
(later items in a tier often depend on earlier ones in the same tier).

This backlog does not authorize implementation. Each item still requires the
normal orchestration contract (advisor/implementer roles, effort level,
minimal tests, safety markers) per `docs/ops/agent_orchestration_contract_v1.md`
before work begins.

## P0 — Safety blockers

Block real money movement or produce silently wrong prices/quantities if
wired to a live path today.

**Status (2026-07-25): all six items below implemented and tested** (73 new
tests; full existing suite re-run clean — 3688 passed, 41 skipped, one
pre-existing unrelated failure). See
`docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md`'s
"P0 implementation update" section and each finding's inline P0 status note
for exact file/module evidence. Not implemented as part of this pass: the
migration was written but **not applied to any database** (schema-only
change requiring separate, explicit DB-write authorization); item 4's
min-notional/min-qty check is not yet wired into `contract_preview_v1`'s
dataclass pipeline (available as a composable post-processing step via
`canonical_rounding_v1.round_leg_for_side()` instead). No A+ ladder was
calculated or submitted as part of this work, per the task's explicit
instruction.

1. **[DONE 2026-07-25] Fix SELL price rounding direction (F3).**
   Replace the side-unaware `ROUND_DOWN` quantizers in
   `src/execution_planner/contract_preview_v1.py` and
   `src/execution/limit_sell_ladder_v1.py` with calls into
   `src/market_rules/price_tick_normalization_v1.normalize_price_to_tick`
   (`PRICE_ROLE_TARGET_SELL` → `ROUND_UP`, `PRICE_ROLE_REENTRY_BUY` →
   `ROUND_DOWN`). This is the single most concrete correctness bug found and
   should land before any of the other P0 items, since several of them touch
   the same call sites.

2. **[DONE 2026-07-25] Implement a canonical `FREE_BASE_QUANTITY` resolver (F1).**
   One function in `decision_gate`,
   `resolve_free_base_quantity(wallet_total_base, reserved_open_sell_base) ->
   Decimal`, as the only permitted producer of this sizing variable.
   Required before any real sell-ladder sizing can be trusted.

3. **[DONE 2026-07-25] Add a canonical SELL-side reservation record (F9).**
   Extend `capital_reservation` or add a parallel base-quantity reservation
   table, written at plan-creation time, released at fill/cancel time —
   matching the pattern already used for BUY-side EUR. Depends on (2)
   existing first, since the reservation and the free-quantity resolver need
   to agree on what "reserved" means.

4. **[DONE 2026-07-25, not yet wired into contract_preview_v1] Add minimum-order-quantity and minimum-notional enforcement (F4).**
   Add `min_notional_quote` to `venue_market`; populate `min_order_qty` and
   `min_notional_quote` for markets in active use; add a deterministic
   rejection reason checked per ladder leg in the designated authoritative
   planner path (see item 5).

5. **[DONE 2026-07-25, for the 8 A+ Week-1 markets] Complete tick-size and quantity-step metadata (F5).**
   Sync `price_precision`, `qty_precision`, `min_order_qty` for all actively
   traded markets from Bitvavo's public `/v2/markets` endpoint (read-only,
   no credentials); add `qty_step_from_precision()` and
   `resolve_qty_step_rule()` alongside the existing tick-size functions.

6. **[DONE 2026-07-25] Designate one authoritative ladder-building path (F2, partial).**
   Not a full merge of the three implementations (that's a P1 item below),
   but a documented decision now: which of
   `contract_preview_v1.EXIT_LADDER`, `execution_ladder.resolver`, or
   `execution.limit_sell_ladder_v1` is authoritative for new
   manual-execution-request work, so items 1–5 are fixed in one place first
   and not silently only in the others. Recommendation in the audit:
   `contract_preview_v1`'s `EXIT_LADDER` path (already base-quantity-sized
   and side-validated).

## P1 — Correctness and reconciliation

Needed before the manual execution tray can be trusted for repeated,
unattended, or concurrent use — not immediately money-losing on a single
careful manual run, but wrong under repetition or concurrency.

7. **Implement `manual_execution_request` and its plan-snapshot table (F12).**
   The four-table foundation (`execution_sizing_variable_ref`,
   `execution_sizing_rule`, `execution_ladder_profile`,
   `execution_ladder_leg`) already exists per
   `db/migrations/20260628_execution_ladder_profiles_v1.sql`. The request
   and plan-snapshot tables specified in
   `docs/todo/manual_execution_ladder_profiles_v1.md` do not yet exist. This
   is the P0 item of that pre-existing design spec and should be treated as
   the anchor for the rest of this backlog's P1 tier.

8. **Idempotency for repeated Process actions (F8/F13, request-side).**
   Depends on (7). Add a deterministic request-dedupe key
   (e.g., hash of account + asset + side + profile + amount + a
   caller-supplied nonce) so a duplicate "Process" click or retried API call
   cannot create two competing plans.

9. **Merge the three ladder-building implementations onto one contract (F2, full).**
   Once (6) has designated an authoritative path and P0 fixes are proven
   there, migrate the other two callers (or retire them) so there is exactly
   one leg-allocation/rounding/validation implementation in the repository.

10. **Add a centrally computed snapshot-freshness check (F11).**
    One `is_snapshot_fresh(snapshot_ts_utc, max_age_seconds)` function with a
    named default threshold, consumed by `sell_intent_policy_v1` and any
    future manual-execution-request gate evaluation, replacing today's
    caller-supplied `source_freshness_ok` boolean.

11. **Add fee modeling (F16).**
    Add `fee_bps` to `ExecutionPlannerConfig`; apply as a haircut to
    available quantity/notional before leg allocation, for both BUY and
    SELL.

12. **Design ladder-aware partial-fill representation (F15).**
    Before any live executor is built (P2/future), design the multi-leg
    fill-state model (per-leg `OPEN`/`PARTIALLY_FILLED`/`FILLED`/`CANCELLED`
    plus an aggregate ladder-level status) so it does not need to be
    retrofitted onto the current single-order paper executor.

## P2 — Multi-account / multi-venue readiness

Not blocking the single existing account today; become hard blockers the
moment a second trading account or venue is provisioned.

13. **Resolve the `account_id` vs `trading_account_id` fragmentation (F6).**
    Minimum viable fix: an explicit, uniquely-constrained
    `account_id -> trading_account_id` mapping table, with every
    `decision_gate`/`execution_planner` repository call that currently
    accepts a bare `account_id` required to resolve it through that table.
    Longer-term (separate, larger effort, not scoped here): migrate
    `portfolio_sleeve` and its dependents onto `trading_account_id` directly.

14. **Formalize the venue-adapter interface (F10).**
    When a second venue is actually planned (not yet), introduce a
    `VenuePrecisionSource`-style protocol with one implementation per venue,
    replacing the inline `if venue == "bitvavo"` branch in
    `src/market_rules/price_tick_normalization_v1.py`. Explicitly
    `NOT_REQUIRED_FOR_V1` until a second venue is in scope — listed here so
    it is not forgotten when that happens.

15. **Single-writer / duplicate-execution protection for a future live
    executor (F14).**
    When a live executor is built and deployed to a specific host, add an
    explicit lock (DB advisory lock or systemd-enforced singleton) rather
    than relying on documentation-only host-ownership conventions.

## P3 — Usability and profile flexibility

Improve the ladder profile model's expressiveness; not required for a
correct, safe, single-account preview-only lane, and each carries its own
governance question that should be resolved deliberately rather than as a
side effect of an unrelated task.

16. **Add a reviewed external-research anchor type (F7).**
    Add `anchor_type = EXTERNAL_RESEARCH_TARGET_V1` (illustrative name) to
    `execution_ladder_profile`/`ALLOWED_ANCHOR_TYPES`, with mandatory
    `source_provenance_json`, `override_scope`, and `promoted` fields (see
    item 17 — these two should land together). Requires explicit review per
    `AGENTS.md`'s external-note governance rule before merging; this is a
    deliberate v1 restriction being lifted, not an oversight being patched.

17. **Add provenance/override fields to the execution-request artifact (F17).**
    **[Groundwork done 2026-07-25]** The standalone
    `execution_research_provenance` table and
    `src/decision_gate/research_provenance_v1.py` already implement exactly
    these fields (source classification/path/sha256/timestamp, ingestion
    status, zero-enforced selection/decision weight, override scope,
    approving user/timestamp, allowed assets/side, preview/live permission,
    expiry/single-use). What remains: wiring item 7's
    `manual_execution_request` (once built) to actually create and check one
    of these records, instead of recording provenance in an out-of-band
    markdown report as happened in today's A+ dry-run.

18. **Add a base-quantity allocation basis to the ladder-leg model (F8).**
    Add `allocation_basis` (`QUOTE_NOTIONAL_BPS` | `BASE_QUANTITY_BPS`) to
    `execution_ladder_leg`, defaulting to today's quote-notional behavior,
    so a sell ladder can be sized directly as "X% of free base quantity per
    leg" without an intermediate notional/price round-trip.

19. **Design the cancel/replace workflow (F13).**
    Not urgent (nothing has been submitted yet to cancel). When a live
    executor is designed (P0/P1 work above must land first), design
    cancel/replace as an explicit, separate intent type in
    `execution_planner` from the start.

## Explicitly not included in this backlog

- Anything requiring live broker writes, order submission, or executor
  activation — out of scope for this audit and this backlog per the current
  live-trading permission state (`NOT_GRANTED`).
- The full `portfolio_sleeve` → `trading_account_id` migration referenced in
  item 13's "longer-term" note — flagged but not scoped here; it is a
  larger, separate migration effort.
- Any change to `selection_engine`, Breathline, or FibNavigationMap
  calculation logic — untouched by this audit, per the design spec's
  explicit non-goals.
