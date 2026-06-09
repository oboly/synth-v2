# TODO — Profit Plan Live Ladder Repair

## Status

Active P0 product lane.

Primary goal:

```text
Profit Plan symbol detail page
-> select MISSING / genuinely STALE ladder rows
-> Fix selected ladder
-> server preview
-> explicit sizing and confirmation
-> decision_gate
-> execution_planner
-> executor
-> Bitvavo limit-order mutation
-> refreshed open-order snapshot
```

This lane is now ahead of non-blocking Profit Plan cosmetics and broader research/dashboard work.

The shortest safe route is **not** to make the reporting renderer trade. The shortest safe route is to reuse the existing Profit Plan ladder rows and proposal-preview foundation, then add the missing authenticated mutation path through the canonical account, decision, planning, and execution layers.

## Sources

Canonical sources:

```text
docs/ops/manual_short_trader_profit_plan_v1.md
src/reporting/manual_short_trader_profit_plan_v1.py
src/reporting/run_manual_short_trader_profit_plan_v1.py
src/reporting/profit_plan_proposal_preview_v1.py
src/reporting/account_dashboard_profile_access_v1.py
docs/todo/manual_ladder_dashboard.md
docs/todo/ui_webview.md
```

Additional source:

```text
Recent chat handoff: safe enabled “Fix selected ladder” flow and Profit Plan scanner/detail TODO consolidation.
```

## Current state / facts

- Profit Plan is account/profile scoped.
- Profile-to-trading-account linkage is DB-backed and fails closed.
- Profit Plan already renders structured ladder rows.
- Current row states include MISSING, ARMED, STALE, HISTORICAL, and DATA_UNAVAILABLE.
- Current proposal preview is reporting-owned, read-only, render-UUID based, and always blocked.
- Current button is offline/disabled.
- Profit Plan HTML/JSON publication is static and atomic.
- Current cockpit rendering does not provide an authenticated write endpoint by itself.
- `broker_writes=0`, `order_submission=0`, `executor=none` remain true until the explicitly reviewed live-canary phase.

## Product decision — shortest path

The compact scanner remains a scanner.

The live repair workflow belongs on the **per-symbol Profit Plan detail page**, where the complete ladder rows and context are visible.

Required user path:

```text
Scanner card
-> Open
-> symbol detail page
-> select actionable rows
-> Fix selected ladder
-> review exact operations and sizing
-> explicit live confirmation
```

Do not put full selection controls back on compact scanner cards.

## Execution order

### P0.0 — Minimum UI and semantic prerequisites

Complete only the Profit Plan work required for a safe repair request:

- per-symbol detail page exists
- scanner links to the correct same-profile symbol detail page
- complete ladder rows remain on the detail page
- only MISSING and genuinely STALE rows are selectable
- ARMED, HISTORICAL, REACHED, PASSED, COMPLETED, and DATA_UNAVAILABLE rows are non-selectable
- far-away orders matching active targets remain ARMED, never stale because of distance alone
- historical/reached targets are not shown as missing requirements
- `local_reaction_price` is not silently promoted to an active required sell target
- current map has a canonical `map_cycle_id`
- actionable rows have stable deterministic identities independent of render UUIDs
- the detail page exposes source/map/order snapshot timestamps

Blocking semantics:

```text
MISSING = active canonical map level has no covering open order
STALE = existing open order matches no active level in the current map, or belongs to an expired/previous map
ARMED = existing open order covers an active current-map level
HISTORICAL = audit context only
```

Non-blocking scanner filtering, timeline sorting, and visual polish must not delay the first canary unless they affect row identity or selection safety.

### P0.1 — Inspect canonical write infrastructure

Before adding mutation code, inspect and document:

- authenticated server/write route, if any
- session identity ownership
- CSRF convention
- account/profile authorization convention
- live execution permission source
- broker-write permission source
- decision_gate contracts
- execution_planner contracts
- executor idempotency and partial-failure behavior
- Bitvavo create/cancel limit-order semantics
- open-order ownership and snapshot freshness
- account balance, position, and reserved-funds snapshots
- audit/event persistence convention

Stop and report rather than improvising when any of these cannot be verified.

If the current application is static-only, the first implementation task is a minimal authenticated server-side action endpoint. Do not add browser-side broker access and do not place credentials in HTML or JavaScript.

### P0.2 — Neutral ladder-repair domain contract

Move mutation-oriented contracts out of reporting into a neutral canonical module, for example:

```text
src/ladder_repair/contracts_v1.py
```

Adapt the path to existing repository conventions after inspection.

Minimum request contract:

```text
request_id
account_profile comparison value
venue
market
map_cycle_id
map_snapshot_ts_utc
price_snapshot_ts_utc
selected_row_ids
requested quantities / EUR notionals
client render reference
```

Server-derived, never browser-authoritative:

```text
authenticated user
requested_by
trading_account_id
profile/account ownership
live permission
broker-write permission
```

The browser payload is untrusted.

Backend reloads current:

- map and active levels
- market/price snapshot
- open orders
- balance/position/reserved funds
- profile/account ownership
- asset enabled/tradeable/paused state
- permissions

Reject when any selected row is no longer actionable or any identity/snapshot/map precondition changed.

### P0.3 — Deterministic row identity

Do not use render-only UUIDs as the sole row identity.

Canonical deterministic identity must include normalized equivalents of:

```text
trading account reference
venue
market
map_cycle_id
side
canonical map-level role
canonical tick-rounded price
current order reference when cancelling
```

Display labels and current timestamps must not be identity inputs.

`map_cycle_id` must come from the canonical market-only map lifecycle, not from reporting.

### P0.4 — Enabled server preview and sizing

Replace:

```text
Fix selected (offline)
```

with:

```text
Fix selected ladder
```

The first click never trades.

Enable only when:

- at least one MISSING or genuinely STALE row is selected
- detail quality is PASS
- current map is active
- `map_cycle_id` exists
- profile/account link is valid
- required machine metadata exists

Server preview shows exact:

- rows selected
- orders to cancel
- orders to create
- cancel/create replacement relationships
- tick-rounded prices
- quantities
- estimated EUR values
- map and snapshot ages
- warnings and rejection reasons

Sizing is mandatory and fail-closed:

- BUY: explicit EUR notional per row, or explicit total budget with visible deterministic split
- SELL: explicit asset quantity per row, or explicit percentage of verified available position with visible calculated quantity
- blank defaults unless a canonical account allocation policy already exists

No broker writes in this phase.

### P0.5 — Decision gate and dry-run execution plan

The account-aware permission layer validates:

- authenticated profile/account ownership
- live permission
- broker-write permission
- asset enabled/tradeable/not paused
- fresh balances, positions, reserved funds, open orders, map, and price
- available EUR for buys
- available free asset quantity for sells
- duplicate/overlapping order coverage
- minimum order value
- exchange amount/price precision
- maximum request notional
- maximum operation count
- plan expiry

Decision output:

```text
APPROVED
REJECTED
REVIEW_REQUIRED
```

Every non-approval has explicit codes.

The execution planner converts an approved repair into immutable deterministic intents only:

```text
CANCEL_LIMIT
CREATE_LIMIT
```

A user-facing REPLACE relationship becomes:

```text
cancel existing order
-> verify successful cancellation
-> create dependent replacement order
```

Do not assume broker-native atomic replace.

Dry-run returns the complete ordered plan and writes only canonical audit state. It performs no broker write and no order submission.

### P0.6 — Immutable confirmed plan

The preview/approved plan contains:

```text
plan_id
request_id
idempotency_key
account identity
market
map_cycle_id
ordered operations
operation dependencies
expected preconditions
input digest
expiry timestamp
safety markers
```

The digest covers account, map, selected rows, active levels, open-order references, sizing, timestamps, and ordered operations.

Any changed input invalidates the plan and requires a fresh preview.

### P0.7 — One-account live canary

Begin only after P0.0–P0.6 pass review.

Canary limits:

- authenticated endpoint
- CSRF protection
- one explicitly allowlisted account
- one explicitly selected market
- limit orders only
- low configurable request-notional cap
- low configurable operation-count cap
- explicit preview confirmation
- expiring plan
- idempotent/double-click safe
- immediate pre-write revalidation
- no automatic periodic repair

Exact runtime path:

```text
HTTP action handler
-> decision_gate
-> execution_planner
-> executor
-> broker client
```

Reporting/UI never imports or calls the broker client.

After execution, refresh canonical open-order state and render the exact result.

Required terminal result states:

```text
COMPLETED
PARTIALLY_COMPLETED
FAILED_BEFORE_WRITES
FAILED_AFTER_WRITES
```

Do not claim the ladder is repaired after partial failure.

### P0.8 — Expand after canary

Only after idempotency, audit, revalidation, and refreshed broker state are proven:

- enable additional markets for the same account
- enable additional linked accounts through explicit allowlists and permissions
- increase caps carefully
- retain manual user initiation

Do not implement automatic repair in this lane.

## Required tests before live

### Unit

- deterministic row identity
- symbol/path normalization
- active far target remains ARMED
- historical rows excluded from action
- genuinely unmatched current order becomes STALE
- active uncovered level becomes MISSING
- stale map rejection
- changed map-cycle rejection
- duplicate coverage rejection
- sizing required
- balance/position rejection
- tick and amount rounding
- permission rejection
- expired plan rejection
- input-digest mismatch rejection
- idempotency

### Integration

- preview makes zero broker writes
- account A cannot mutate account B
- map change between preview and confirm aborts
- new covering order after preview prevents duplicate creation
- reduced free balance after preview aborts
- double submission executes once
- cancel succeeds before dependent create
- failed cancel blocks dependent create
- partial failure is persisted and visible
- final open-order refresh confirms broker state

### UI

- zero selection disables button
- valid MISSING/STALE selection enables button
- ARMED/HISTORICAL rows cannot be selected
- quantities/notionals are required
- exact operations are visible
- explicit live confirmation is required
- errors remain visible
- successful execution refreshes ladder state

## Architecture boundary

```text
selection_engine = unchanged, market-only
reporting = display and untrusted selection submission only
account layer = profile/account ownership and fresh account snapshots
decision_gate = account-aware permission and validation
execution_planner = immutable execution intent only
executor = idempotent order handling only
broker client = exchange transport only
```

Forbidden:

- reporting-to-broker calls
- browser-held API credentials
- browser-authoritative account identity or permissions
- decision_gate bypass
- execution_planner bypass
- direct executor calls from reporting
- market orders
- silent capital allocation
- automatic periodic repair

## Stop conditions

Stop and report instead of improvising when:

- no authenticated write path exists
- account ownership cannot be verified
- CSRF/auth conventions are absent or ambiguous
- no canonical quantity/allocation policy exists and UI does not request explicit sizing
- executor idempotency is absent
- broker cancel/create semantics are ambiguous
- permissions can be enabled by request payload
- fresh balances/open orders cannot be verified
- map lifecycle cannot produce stable `map_cycle_id`

## P1 — Profit Plan scanner correctness after the live-path prerequisites

These remain important but must not unnecessarily block the canary:

- structured field filtering; exact symbol/market match must beat reason-text matches
- `NEAR` matches NEAR/NEAR-EUR, not every state containing `NEAR`
- separate symbol, event, action, quality, lifecycle, and relevance filters
- explicit deterministic category ordering:
  - ACTION_REQUIRED
  - LIVE_ZONE
  - TARGET_APPROACHING
  - REBOUND_OR_BREAKOUT
  - WATCH
  - RECENT_EVENT
  - MINIMAL_CONTEXT
- Upcoming sorts by nearest actionable distance
- Recent sorts by latest passed-event timestamp
- stable source-order tie-breaker
- relevance diagnostics and source snapshot metadata
- investigate cards disappearing/reappearing as market-state change versus render/snapshot flapping

Action semantics:

- `FIX_LADDER` when actionable ladder repair exists
- `ROTATE_LADDER` only after target hit/passed when a new ladder is required
- `ROTATE_MAP` only for completed/expired/invalid maps
- `REVIEW_CONTEXT` only for genuinely missing/stale/invalid context
- no generic WAIT/NO_ACTION when a specific action exists

## P2 — Profit Plan cosmetics after live ladder repair

Do only after the live repair path is safe and usable:

- rename `Invalidation / risk zone near` to `Invalidation zone near`
- replace three horizontal card dividers with whitespace
- increase logical-section vertical spacing by about 40%
- slightly increase card/background and state-label contrast
- keep styling calm; no heavy borders or excessive color
- remove duplicate body rows for Quality, Market, and Horizon
- keep a single prominent PASS/WARN/FAIL badge
- align wallet styling with cockpit
- complete real mobile visual review

## P3 — Trade Path lane

Separate later lane:

- 5m Trade Path chart
- default 3 hours
- extend backward to relevant touch/entry/leg start
- maximum 24 hours
- overlay zones, current orders, entries, targets, and invalidation
- no browser candle API fetch

Historical path semantics:

```text
REBUY_ZONE_NEVER_REACHED
REBUY_ZONE_ACTIVE_NOW
REBUY_ZONE_TOUCHED_AND_LEFT_UPWARD
REBUY_ZONE_TOUCHED_AND_LEFT_DOWNWARD
```

Include touch/exit timestamps, rebound confirmation, and highest/lowest price since activation.

T0 intermediate reaction target remains blocked until supplied by a canonical market-only resistance/reaction source. Reporting must never invent T0.

## P4 — Separate non-trading product/ops lanes

Keep separate from live ladder delivery:

- already-used verification-token UX
- email deliverability: SPF/DKIM/DMARC, sender identity, message content
- broader wallet/cockpit styling
- live mobile review

## Immediate next implementation batch

```text
1. Audit authenticated write path, permission gates, decision_gate, execution_planner, executor, and broker cancel/create semantics.
2. Finalize canonical map_cycle_id and deterministic actionable row identity.
3. Move ladder-repair contracts out of reporting.
4. Build authenticated server preview with explicit sizing; no writes.
5. Build decision-gate approval and execution-planner dry run.
6. Review.
7. Run one-account, one-market, low-cap limit-order canary.
```

## Safety progression

Before live canary:

```text
broker_writes=0
order_submission=0
executor=none
```

Live canary acceptance:

```text
only allowlisted account
only selected market
only selected operations
limit orders only
idempotency proven
audit persisted
fresh open-order snapshot confirms final state
```
