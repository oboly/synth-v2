# TODO — Profit Plan Live Ladder Repair

## Status

```text
active P1 / Synth v2.23
```

The internal `P0.x` labels below are mandatory sequence gates inside this lane. Globally, this lane is P1 behind TODO-board reconciliation.

## Goal

Provide the shortest safe path from canonical Profit Plan ladder truth to a manually initiated, authenticated, reviewed repair flow:

```text
symbol detail page
-> select canonical MISSING / genuinely STALE rows
-> server-side preview with explicit sizing
-> decision_gate approval
-> immutable execution plan
-> executor
-> Bitvavo limit-order mutation
-> refreshed canonical open-order snapshot
```

The reporting renderer must never become a broker client.

## Sources

```text
docs/ops/manual_short_trader_profit_plan_v1.md
src/reporting/manual_short_trader_profit_plan_v1.py
src/reporting/run_manual_short_trader_profit_plan_v1.py
src/reporting/profit_plan_proposal_preview_v1.py
src/reporting/account_dashboard_profile_access_v1.py
docs/todo/profit_plan_dashboard_action_truth_and_breathline_demote_v1.md
docs/todo/native_short_runtime_owner_and_scope_status_v1.md
docs/todo/native_short_map_level_status_v1.md
docs/todo/short_swing_linked_profile_freshness_and_disk_reliability_v1.md
```

## Current state / completed prerequisites

Completed and no longer open in this lane:

- native SHORT cadence, scope-status projection, map-level status persistence/materializer/runner/chain/runtime wiring are merged and accepted;
- canonical current map and map-cycle ownership exists in market-data scope;
- Actionable PPP, map-switch review, fail-closed action truth, current-cycle activation proof, Breathline zero authority, normalized evidence rows, escaping, and numeric formatting are implemented;
- Profit Plan remains static/read-only with `broker_writes=0`, `order_submission=0`, and `executor=none`;
- current proposal preview is reporting-owned and non-authoritative, so it is not yet the mutation contract.

Installed-host activation of repository runtime wiring remains a separate P2 operational concern. Do not conceal missing/stale production inputs by falling back to generated files or reporting inference.

## P0.0 — Canonical read-model prerequisites

Before mutation work, Profit Plan must consume authoritative persisted inputs:

- `native_short_scope_status_v1` for current scope/map selection and freshness;
- `native_short_map_level_status_v1` for current SELL target lifecycle;
- immutable map geometry only through the projection-selected map;
- persisted market-price, wallet/balance, position, and open-order observations;
- absolute source and render timestamps.

Required semantics:

```text
MISSING    = active canonical current-map level has no covering open order
STALE      = existing order belongs to no active current-map level or to a previous/terminal map
ARMED      = current open order covers an active current-map level
REACHED    = lifecycle truth; non-selectable
PASSED     = lifecycle truth; non-selectable
HISTORICAL = audit context; non-selectable
UNVERIFIED = fail closed; non-selectable
```

Reporting must not infer lifecycle from chart appearance or independently join ledgers to recreate current truth.

The IOST lifecycle regression is owned by `profit_plan_target_lifecycle_history_truth_v1.md`; this lane consumes the resolved canonical result.

## P0.1 — Stable map and row identity

Actionable rows require deterministic identity independent of render UUID:

```text
trading account reference
venue
market
current_map_cycle_id
side
canonical map-level role
canonical tick-rounded price
current broker order reference when cancelling
```

Display labels and timestamps are not identity fields.
Any changed map, level, order, price, balance, position, permission, or sizing input invalidates the preview.

## P0.2 — Freshness and account authority

Required absolute observations:

```text
map/projection observed timestamp
map-level rebuild timestamp
market price observed timestamp
wallet/balance observed timestamp
position observed timestamp
open-orders observed timestamp
dashboard generated timestamp
```

Each authority must be `FRESH`, `STALE`, `MISSING`, or `UNAVAILABLE` under one canonical policy.

A stale or missing account authority suppresses account-specific repair claims.
`decision_gate` must consume persisted authority or a pure evaluator over it, never presentation HTML/JSON.

Operational timestamp and stale-page work is owned by `short_swing_linked_profile_freshness_and_disk_reliability_v1.md`; do not duplicate that implementation here.

## P0.3 — Inspect canonical write infrastructure

Before adding mutation code, document and verify:

- authenticated server action route;
- session identity and profile/account ownership;
- CSRF convention;
- live execution and broker-write permission sources;
- allowlist ownership;
- account balance, position, reserved-funds, and open-order freshness;
- `decision_gate` contracts;
- `execution_planner` contracts;
- executor idempotency and partial-failure behavior;
- Bitvavo create/cancel limit-order semantics;
- audit/event persistence;
- final broker-state refresh.

Stop rather than improvise when any owner is absent or ambiguous.

## P0.4 — Neutral ladder-repair contract

Mutation-oriented request and plan types belong in a neutral domain module, not reporting.

Minimum untrusted request fields:

```text
request_id
profile comparison value
venue / market
current_map_cycle_id
map and price snapshot timestamps
selected deterministic row ids
explicit EUR notionals or asset quantities
client render reference
```

Server-derived fields:

```text
authenticated user
requested_by
trading_account_id
profile/account ownership
live permission
broker-write permission
current canonical map/levels
fresh account and market observations
```

The browser is never authoritative for identity, permission, balance, position, open orders, or actionability.

## P0.5 — Server preview with explicit sizing

The first click performs no broker write.

Enable preview only when all selected rows remain canonical/actionable and every required authority is fresh.
Preview shows exact:

- cancellations;
- creations;
- dependency relationships;
- tick-rounded prices;
- quantities and EUR notionals;
- source ages;
- warnings and rejection reason codes.

Sizing is mandatory and blank by default unless an already-approved canonical allocation policy exists.

## P0.6 — Decision gate and dry-run plan

`decision_gate` owns account-aware approval and validates ownership, permissions, freshness, funds/position, duplicates, exchange minimums/precision, caps, operation count, and expiry.

Allowed result:

```text
APPROVED
REJECTED
REVIEW_REQUIRED
```

`execution_planner` converts only an approved repair into immutable deterministic intents:

```text
CANCEL_LIMIT
CREATE_LIMIT
```

A replacement is an ordered dependency:

```text
cancel existing order
-> verify cancellation
-> create dependent replacement
```

No assumption of broker-native atomic replace.
Dry-run performs no broker write or order submission.

## P0.7 — Immutable confirmation

The confirmed plan includes:

```text
plan_id
request_id
idempotency_key
account identity
market
current_map_cycle_id
ordered operations and dependencies
expected preconditions
input digest
expiry timestamp
safety markers
```

Changed input requires a new preview and confirmation.

## P0.8 — One-account live canary

Begin only after P0.0–P0.7 pass review and the user explicitly authorizes live execution.

Canary constraints:

- one authenticated user/profile;
- one allowlisted account;
- one selected market;
- limit orders only;
- low request-notional and operation caps;
- expiring immutable plan;
- immediate pre-write revalidation;
- idempotent/double-click safe execution;
- no periodic automatic repair.

Exact path:

```text
HTTP action handler
-> decision_gate
-> execution_planner
-> executor
-> broker client
```

Reporting/UI cannot import or call the broker client.

Terminal result states:

```text
COMPLETED
PARTIALLY_COMPLETED
FAILED_BEFORE_WRITES
FAILED_AFTER_WRITES
```

After execution, refresh canonical open orders and display the exact outcome. Never claim full repair after partial failure.

## Required tests before live

### Unit

- deterministic row identity;
- current/previous map separation;
- active/reached/passed/historical selection rules;
- stale/missing authority rejection;
- changed map-cycle and input-digest rejection;
- duplicate coverage rejection;
- explicit sizing;
- funds/position/precision/cap validation;
- plan expiry and idempotency.

### Integration

- preview performs zero broker writes;
- account A cannot mutate account B;
- changed map/order/balance after preview aborts;
- double submission executes once;
- cancel dependency gates create;
- partial failure is persisted and visible;
- final open-order refresh confirms broker state.

### UI

- only canonical MISSING/STALE rows selectable;
- zero selection disables preview;
- exact operations and sizing visible;
- explicit live confirmation required;
- errors persist visibly;
- completed execution refreshes ladder truth.

## Architecture boundary

```text
selection_engine  = unchanged, market-only
reporting         = display and untrusted selection submission only
account layer     = ownership and persisted account observations
decision_gate     = account-aware permission and validation
execution_planner = immutable execution intent only
executor          = idempotent order handling only
broker client     = exchange transport only
```

Forbidden:

- reporting-to-broker calls;
- browser-held credentials;
- browser-authoritative identity, permission, or account truth;
- `decision_gate` or planner bypass;
- direct executor calls from reporting;
- market orders;
- silent capital allocation;
- automatic periodic repair.

## Stop conditions

Stop and report when:

- authenticated write/CSRF convention is absent;
- ownership or permission cannot be verified;
- canonical account snapshots are unavailable;
- executor idempotency is absent;
- cancel/create semantics are ambiguous;
- stable map-cycle/row identity is unavailable;
- target lifecycle remains unverified;
- fresh final broker state cannot be confirmed.

## Later non-blocking work

Scanner filtering, visual polish, wallet styling, mobile review, and 5m Trade Path are later lanes. They do not block the first safe preview/canary unless they affect identity, freshness, or selection safety.

## Immediate next implementation slice

Do not start with executor or broker mutation.

Start with one reviewed prerequisites slice:

```text
canonical Profit Plan consumer of scope-status + map-level status
+ deterministic actionable row identity
+ absolute freshness/status evidence
+ read-only tests
```

No new feature branch should mix that consumer slice with live execution implementation.
