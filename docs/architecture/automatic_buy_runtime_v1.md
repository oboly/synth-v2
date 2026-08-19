# Automatic BUY runtime v1

Issue #399 Phase 4 defines the runtime composition boundary only.

Ownership remains strict:

- market/setup candidate truth: `entry_policy.automatic_buy_candidate_v1`;
- account permission/allocation/protection: `decision_gate`;
- immutable BUY ladder: `execution_planner.automatic_buy_planner_v1`;
- this runtime: deterministic sequencing, evidence loading, locking and append-only audit;
- executor/broker: not used in Phase 4.

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
evidence only and MUST NOT become executor input. Phase 6 must use the typed
in-memory `AutomaticBuyPlanV1` through an explicit shared #206 adapter/handoff
boundary.

The Phase 4 runner is one-cycle only and uses a host-local non-blocking flock.
The ownership registry marks it `PLANNED`; this repository change does not
install or enable a service/timer.
