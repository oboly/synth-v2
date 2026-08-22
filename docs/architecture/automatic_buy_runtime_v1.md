# Automatic BUY runtime v1

Issue #399 defines the automatic BUY composition path with strict ownership:

- market/setup candidate truth: `entry_policy.automatic_buy_candidate_v1`;
- account permission/allocation/protection and decision-gate LIVE permission: `decision_gate`;
- immutable BUY ladder: `execution_planner.automatic_buy_planner_v1`;
- runtime: deterministic sequencing, evidence loading, locking and append-only audit;
- shared executor handoff: existing side-neutral #206 substrate only;
- broker/order handling: executor-owned and never decision-gate-owned.

The runtime consumes immutable `automatic_buy_runtime_input_v1` snapshots. A
snapshot binds market setup evidence and the account-fact snapshot needed by
the gate, but does not itself make a permission decision. `evaluation_ts_utc`
is persisted inside the input snapshot and is reused on every replay.

Issue #474: the snapshot's own account-owned columns (`account_enabled`,
`account_mode`, `live_trading_enabled`, `automatic_buy_execution_enabled`,
`free_quote_balance_eur`, `proposed_position_amount_eur`,
`current_bucket_amount_eur`, `current_open_positions`,
`current_asset_exposure_pct`) are never trusted as persisted. At composition
time `build_runtime_item_v1` replaces them with a freshly-loaded, canonical
`AutomaticBuyAccountAllocationEvidenceV1` (see
`docs/architecture/automatic_buy_account_allocation_evidence_v1.md`) before
the gate ever sees them, so no writer of this table -- including a future
acceptance/DRY_RUN producer -- can influence account permission/allocation
outcomes by writing to those columns.

At evaluation time the repository additionally loads the immutable #279
strategy-bucket configuration history, obtains the canonical #318 protection
evaluation for `ACTION_BUY`, and loads public venue execution constraints.
These exact identities are included in the idempotency evidence before the
candidate/gate/planner path runs.

The resulting audit row is append-only. `immutable_plan_json` is replay/audit
evidence only and MUST NOT become executor input. The shared handoff uses the
typed in-memory `AutomaticBuyPlanV1` produced by the same runtime cycle.

## LIVE-capable versus LIVE-enabled

Phase 7 readiness is deliberately split from operational activation.

Phase 7A makes `decision_gate` LIVE-capable. A BUY candidate with
`account_mode="live"` may only be approved when all normal BUY permission,
allocation and protection checks pass, `live_trading_enabled=True` is supplied
as consistent account evidence, and an exact account/timestamp-bound typed
BUY LIVE permission evaluation is `GRANTED`. The permission contract is
append-only and revocable. Missing, malformed, stale, conflicting, denied, or
wrong-account evidence fails closed.

Phase 7B makes runtime composition LIVE-capable without activating it. Runtime
input contract v1 remains the frozen PAPER-era contract and retains its exact
idempotency evidence shape. A LIVE-mode input must use contract v2. V2 binds
`live_trading_enabled` and the typed BUY LIVE permission evaluation fingerprint
explicitly into idempotency evidence, in addition to the pre-existing account
protection, strategy-bucket, setup and venue-constraint evidence. Replays of an
old v1 PAPER snapshot therefore remain unchanged by the software upgrade.

The canonical runtime core remains executor-free. The only deliberate crossing
to the shared #206 executor boundary is
`automatic_buy_live_handoff_composition_v1` ->
`automatic_buy_execution_handoff_application_v1`. That seam forwards only the
exact staged in-memory plan. It never reconstructs a plan from append-only audit
JSON.

Normal executor mode is derived from account mode (`paper -> PAPER`,
`live -> LIVE`). The only explicit override is `DRY_RUN`. A LIVE plan routes
only through the existing shared `intake_live_authorized` method, so the BUY
lane cannot bypass executor credential scope, finite LIVE authority or global
kill-switch checks. Phase-5 `PAPER_DRY_RUN` preview evidence is explicitly
forbidden from reaching LIVE intake.

This is still a software contract, not a production mutation. Repository
readiness MUST NOT set production `trading_account.live_trading_enabled`, create
a real TRADE_EXECUTION credential, grant executor LIVE authority, mutate the
global kill switch, enable broker writes, start a LIVE service/timer, or submit
an order. Production may remain `live_trading_enabled=false` throughout
7A/7B/7C.

The one-cycle policy runtime remains separate from the shared executor runtime.
Phase 7B adds no LIVE CLI, service or timer. No runtime/service/timer activation
is performed by this readiness change.
