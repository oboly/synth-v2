# Profit Plan Live Ladder Architecture Audit V1

## Status

Initial repository audit completed for the active P0 lane:

```text
docs/todo/profit_plan_live_ladder.md
```

This audit identifies reusable foundations and the shortest remaining path to a controlled live `Fix selected ladder` canary.

## Confirmed reusable foundations

### Authenticated web service exists

The repository already contains a production-hardened web-auth service and nginx authorization path.

Confirmed properties:

- application session cookie is HttpOnly, Secure, SameSite=Lax
- profile-scoped account routes are checked server-side
- nginx derives the requested profile from the route rather than trusting a browser header
- cross-profile access is rejected
- POST routes use production Origin validation against `SYNTH_PUBLIC_BASE_URL`
- the service already runs as a local WSGI application behind nginx

Conclusion:

```text
Do not build a second web server.
Extend the existing authenticated web service with narrowly scoped ladder-repair endpoints.
```

The current Origin check is the canonical CSRF baseline. The implementation batch must inspect whether a dedicated per-request CSRF token is also required for mutation endpoints; do not weaken the existing Origin enforcement.

### Profile/account ownership exists

`src/reporting/account_dashboard_profile_access_v1.py` resolves profile to trading account through DB-backed explicit linkage and fails closed when linkage is absent or ambiguous.

For write endpoints, identity must be resolved from the authenticated session/account layer. Reporting helpers may be reused only as read-side references; mutation authorization remains server/account-layer owned.

### Decision-gate audit persistence exists

`src/decision_gate/audit_writer_v1.py` provides append-only `decision_gate_audit_log` persistence with explicit account scope, reason payloads, upstream references, and safety markers.

Current writer supports only:

```text
PAPER
LIVE_DRY_RUN
```

It explicitly rejects `LIVE_ARMED` and `LIVE`.

Conclusion:

- reuse this writer for preview/dry-run audit where its schema fits
- do not silently widen its live-mode contract
- live execution audit may require a separate reviewed version or canonical execution event tables

### Decision-gate preview foundations exist

Existing sell-only decision-gate preview code already reads:

- trading account state
- live-trading flag
- latest position snapshot
- available quantity
- reserved quantity
- reference price
- duplicate intent evidence

It remains deliberately non-executable and sell-only.

Conclusion:

Reuse patterns and account snapshot sources, not the old preview policy as the final ladder-repair gate.

The Profit Plan ladder repair gate must support explicit selected BUY and SELL limit operations, open-order conflicts, asset pause/disable state, snapshot freshness, request caps, and immutable plan preconditions.

### Execution-planner preview exists

`src/execution_planner/contract_preview_v1.py` already contains:

- explicit planner intent validation
- ladder levels
- notional/quantity requirements
- tick-size quantization
- passive/post-only concepts
- deterministic preview behavior

Important existing caveat:

A one-tick spread can make a passive price cross the opposite quote. A live executor requires venue-aware post-only validation or retreat logic.

Conclusion:

Do not create order transport in the planner. Add a dedicated ladder-repair adapter that converts an approved repair into explicit ordered `CANCEL_LIMIT` and `CREATE_LIMIT` intents using canonical planner primitives where compatible.

### Paper executor preview exists

The current executor implementation found during this audit is a sell-only paper executor preview.

It:

- advances database preview states
- does not call the broker
- does not submit orders
- does not mutate positions
- is not a live executor

Conclusion:

```text
There is no verified reusable live order executor yet.
```

This is the main remaining implementation gap.

## Not yet verified — blockers before live writes

The following were not proven by this initial audit and must be inspected in the local repository/runtime before implementation proceeds to live writes:

- canonical Bitvavo private broker client used for order creation
- canonical Bitvavo order-cancellation method and response semantics
- client order ID / idempotency support
- duplicate submission protection across process restart
- cancel confirmation semantics
- handling of partially filled orders during cancellation/replacement
- exchange amount precision and price precision source
- minimum order value source
- canonical current open-order refresh immediately before and after execution
- canonical BUY balance snapshot and reserved-EUR calculation
- canonical account asset pause/disable enforcement for write requests
- existing live execution and broker-write permission readers for an authenticated web request
- canonical execution result/audit tables for broker responses
- partial-failure recovery convention

No live canary may start until these are verified.

## Architecture decision

The shortest safe implementation path is:

```text
existing web-auth WSGI service
-> new authenticated ladder-repair HTTP controller
-> neutral ladder_repair request/plan contracts
-> account snapshot reload
-> ladder-repair decision gate
-> ladder-repair execution planner adapter
-> new idempotent live limit-order executor
-> canonical Bitvavo broker client
-> open-order refresh
```

Not:

```text
static Profit Plan HTML
-> JavaScript broker call
```

and not:

```text
reporting
-> executor
```

## Recommended first implementation batch

### Batch A — audit and contract foundation only

No broker calls, no broker writes, no order submission.

Tasks:

1. Inspect the existing web-auth route/controller architecture and add no endpoint yet.
2. Locate and document canonical broker private-read and write clients.
3. Locate permission readers for:
   - live execution
   - broker writes
   - per-account allowlist
4. Locate canonical open-order, balance, position, reserved-funds, market precision, and minimum-order-value sources.
5. Verify whether current map lifecycle exposes a stable `map_cycle_id`.
6. Define deterministic ladder row identity.
7. Create neutral immutable contracts under a canonical non-reporting package.
8. Add tests proving browser payload cannot authoritatively set account identity or permissions.
9. Update this audit with exact file paths and verified gaps.

Expected safety markers:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
executor=none
```

### Batch B — authenticated preview

Only after Batch A:

- add authenticated same-profile POST preview endpoint to existing WSGI service
- preserve Origin/CSRF enforcement
- reload server-side map/account/order state
- require explicit sizing
- produce immutable expiring preview
- persist LIVE_DRY_RUN decision audit
- no broker writes

### Batch C — planner dry run

Only after Batch B:

- decision gate APPROVED/REJECTED/REVIEW_REQUIRED
- deterministic cancel/create operation order
- input digest and expiry
- idempotency key
- no broker writes

### Batch D — executor and one-market canary

Only after review:

- implement or reuse canonical broker transport
- one allowlisted account
- one allowlisted market
- low cap
- limit orders only
- immediate revalidation
- exact audit and result persistence
- final open-order refresh

## Immediate finding

The project is closer than a greenfield implementation because authentication, account linkage, snapshots, decision auditing, and planner previews already exist.

However, switching the current preview button directly to broker writes would bypass missing live-executor guarantees. The correct acceleration is to reuse the foundations and concentrate implementation on:

```text
stable row/map identity
authenticated preview controller
account-aware ladder decision gate
immutable repair plan
idempotent live limit-order executor
```

Cosmetic Profit Plan work remains behind this path unless it affects selection safety.
