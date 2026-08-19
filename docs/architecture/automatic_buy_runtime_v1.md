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

At evaluation time the repository additionally loads the immutable #279
strategy-bucket configuration history, obtains the canonical #318 protection
evaluation for `ACTION_BUY`, and loads public venue execution constraints.
These exact identities are included in the idempotency evidence before the
candidate/gate/planner path runs.

The resulting audit row is append-only. `immutable_plan_json` is replay/audit
evidence only and MUST NOT become executor input. Phase 6 uses the typed
in-memory `AutomaticBuyPlanV1` through the explicit shared #206
adapter/handoff boundary.

## LIVE-capable versus LIVE-enabled

Phase 7 readiness is deliberately split from operational activation.

Phase 7A makes `decision_gate` LIVE-capable. A BUY candidate with
`account_mode="live"` may only be approved when all normal BUY permission,
allocation and protection checks pass, `live_trading_enabled=True` is supplied
as consistent account evidence, and an exact account/timestamp-bound typed
BUY LIVE permission evaluation is `GRANTED`. The permission contract is
append-only and revocable. Missing, malformed, stale, conflicting, denied, or
wrong-account evidence fails closed.

This is a software contract, not a production mutation. Repository readiness
MUST NOT set production `trading_account.live_trading_enabled`, create a real
TRADE_EXECUTION credential, grant executor LIVE authority, mutate the global
kill switch, enable broker writes, start a LIVE service/timer, or submit an
order. Production may remain `live_trading_enabled=false` throughout 7A/7B/7C.

Decision-gate LIVE permission is also insufficient for an order by design.
Downstream executor credential scope, finite LIVE authority, kill-switch state,
handoff-bound identity, submission state and reconciliation remain separate
executor-owned gates.

The one-cycle policy runtime remains separate from the shared executor runtime.
No runtime/service/timer activation is performed by this readiness change.
