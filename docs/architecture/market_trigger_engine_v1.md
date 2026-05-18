# Market Trigger Engine V1

## Purpose

Design a reusable public market-data trigger engine that watches dynamic ticker, trade, or candle inputs and emits threshold and zone events.

This is not a planner. `execution_planner` keeps its separate responsibility for turning an already-authorized decision into an execution intent. The trigger engine is a market event layer that can later feed paper advice lifecycle state, dashboard refreshes, alerts, and future execution-agent / order-monitor components.

V1 is a design document only. It does not add a service, database migration, private broker call, order path, or runtime permission.

## Source Model

Initial sources:

- Bitvavo public ticker stream.
- Bitvavo public trade stream.
- Bitvavo public candle stream or bounded candle polling fallback.

Boundary:

- no private broker calls
- no broker writes
- no orders
- no account, balance, or position access
- no decision, execution, or strategy mutation

The engine should subscribe only to a small dynamic symbol set in V1. Streaming every market is unnecessary for the first operational use case.

## Core Components

`ticker_subscription_manager`:

- builds the active symbol set
- opens public market-data subscriptions
- reconnects with backoff
- rebuilds subscriptions when watch definitions change

`market_trigger_engine`:

- evaluates price ticks, trade prints, and candle updates against active watches
- emits threshold and zone events
- updates current trigger state
- never creates orders or execution intents

`watch_definition_repository`:

- reads enabled watch definitions
- exposes active watches by symbol / venue
- supports future DB-backed definitions

`market_trigger_event_repository`:

- records immutable trigger events
- supports audit, replay, and consumers that were offline

`market_trigger_state_repository`:

- stores current watch state
- tracks latest price, latest event, event counts, and recompute flags

`consumer interface`:

- receives trigger events after persistence
- consumers are isolated from watch evaluation internals
- consumer failures must not create market actions

## Watch Definitions

Watch definitions should be generic threshold or zone watches:

```text
watch_id
symbol
venue
source_context_type
source_context_id
watch_type
threshold_low
threshold_high
direction
expires_at
enabled
```

Examples:

- HYPE invalidation above `40.317`
- HYPE downside entry zone `34.713` to `34.762`
- BTC breakout threshold
- future active order cancel threshold
- future virtual paper fill threshold

`source_context_type` and `source_context_id` link events back to the upstream object that created the watch, for example a `paper_advice_observation` row or a future authorized execution plan. The trigger engine must not infer strategy meaning beyond the watch definition.

## Event Types

Supported event names should start with a small explicit set:

- `PRICE_TICK`
- `THRESHOLD_CROSSED_UP`
- `THRESHOLD_CROSSED_DOWN`
- `ZONE_ENTERED`
- `ZONE_EXITED_UP`
- `ZONE_EXITED_DOWN`
- `INVALIDATION_TOUCHED`
- `ENTRY_ZONE_TOUCHED`
- `TARGET_ZONE_TOUCHED`
- `RECOMPUTE_NEEDED`

Event names are market-state facts, not trading instructions.

## State Model

Current trigger state should include:

```text
watch_id
symbol
venue
current_price
latest_price_ts_utc
last_event_type
last_event_ts_utc
active
last_touched_ts_utc
event_count
recompute_needed
source_context_type
source_context_id
```

The state row is a convenience view for fast consumers. The event log remains the audit trail.

## Consumers

Initial and future consumers:

- `paper_advice_lifecycle_consumer`
- `dashboard_refresh_consumer`
- `alert_consumer`
- future `execution_order_monitor_consumer`

Consumer boundary:

- consumers may react to trigger events within their own permission scope
- consumers may not bypass `decision_gate`
- consumers may not create order intents unless the upstream component already owns that permission
- consumer output must be auditable

## Execution Boundary

Executor remains a low-level order adapter:

- place order
- cancel order
- read order status
- record result

A future execution agent or order monitor may consume market trigger events only for already-authorized execution plans or already-existing orders.

No trigger event may:

- bypass `decision_gate`
- create order intent
- create orders
- cancel orders directly
- reserve capital
- change strategy or policy

Trigger events can inform an authorized execution component, but they are never authorization by themselves.

## Paper Advice Boundary

Paper advice lifecycle may use trigger events to mark display context:

- `INVALIDATED`
- `RECOMPUTE_NEEDED`
- `ENTRY_ZONE_TOUCHED`
- `POST_ENTRY_BOUNCE`
- `REACTION_RETEST_AFTER_ENTRY`

It may not recompute zones inside the dashboard or trigger engine. Zone recomputation belongs upstream in the paper advice / `execution_zone_context` pipeline.

If an invalidation watch is touched, the dashboard should keep old zones visible as expired context and show that recomputation is needed. It must not silently replace zones.

## Storage Recommendation

Options:

- RAM only: fastest, but loses events on restart and is weak for audit.
- JSON state file: simple, but awkward for concurrent consumers and replay.
- DB event log + current state: auditable, replayable, and consistent across services.

Recommendation:

Use a DB event log plus current state as the source of truth, with optional in-memory cache for speed.

Schema proposal only, no migration in this lane:

`market_trigger_watch`:

```text
watch_id
symbol
venue
source_context_type
source_context_id
watch_type
threshold_low
threshold_high
direction
expires_at
enabled
created_at_utc
updated_at_utc
```

`market_trigger_event`:

```text
event_id
watch_id
symbol
venue
event_type
price
event_ts_utc
source_payload_json
created_at_utc
```

`market_trigger_state`:

```text
watch_id
symbol
venue
current_price
latest_price_ts_utc
last_event_type
last_event_ts_utc
active
last_touched_ts_utc
event_count
recompute_needed
updated_at_utc
```

## Runtime Model

Future Odroid service candidate:

```text
synth-market-trigger-engine.service
```

Expected behavior:

- load enabled watches
- connect to public market-data streams
- reconnect with backoff
- rebuild dynamic subscriptions when latest paper advice snapshot changes
- fail closed when source data or DB persistence is unavailable
- write explicit safety markers
- log to systemd journal or configured logs directory
- require no private broker credentials

Safety markers:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```

## Dynamic Subscription Model

Initial symbol set:

- build active symbols from the latest `paper_advice_observation` top N rows
- include only rows with active display watches
- rebuild when a newer paper advice snapshot appears
- unsubscribe symbols with no enabled watches

V1 should avoid streaming all markets. The first useful target is a bounded list of symbols that already have zones or thresholds needing fast lifecycle observation.

## Downstream Path

Current path:

```text
4h paper_advice_observation
-> fast lifecycle candle refresh runner
-> static dashboard lifecycle state
```

Future path:

```text
4h paper_advice_observation
-> market_trigger_watch definitions
-> market_trigger_engine public stream
-> market_trigger_event / market_trigger_state
-> dashboard, alerts, paper lifecycle consumers
-> future execution order monitor only after explicit permission exists
```

No runtime promotion is implied by this design.
