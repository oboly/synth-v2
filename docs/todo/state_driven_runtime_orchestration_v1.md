# State-Driven Runtime Orchestration V1

## GitHub Issue migration

Status: migrated

Operational status/priority is owned by GitHub Issues.

Section ownership:
- repository/git-history mechanism audit and minimal integration-design next step -> Issue #331
- any future schema/runtime/dispatcher/timer implementation -> not authorized by this file; requires evidence-driven follow-up Issues after #331

Unmigrated executable scope:
- none

## Status

Design note only. No runtime behavior, scheduler, writer ownership, database schema,
service activation, broker behavior, decision logic, planning logic, or execution
behavior is changed by this document.

This note captures the current architectural direction discussed around Profit Plan,
Native SHORT freshness, candle freshness, recompute lifecycle, and self-healing runtime
behavior. Before implementation, existing freshness/recompute mechanisms must be
inventoried so useful canonical parts are reused rather than duplicated.

## Problem

Synth currently has multiple good domain-specific freshness and lifecycle mechanisms,
but orchestration is still substantially timer-driven and fragmented across separate
runtime owners.

Examples include:

- public candle freshness for `15m`, `1h`, `4h`, `1d`, and `1w`;
- Native SHORT scope/status materialization over canonical `4h` primary and `1h`
  supporting candles;
- Native SHORT map/lifecycle state and freshness projection;
- `fast_recompute_lifecycle_v1`, which already identifies recompute conditions such as
  `MAP_RECOMPUTE_NEEDED`, `INVALIDATION_TOUCHED`, target completion, and reclaim;
- Profit Plan, which surfaces conditions such as `MARKET_DATA_MISSING`,
  `CONTEXT_INVALID_OR_STALE`, `NO_NATIVE_SHORT_FIB_CONTEXT`, and
  `MAP_RECOMPUTE_NEEDED`.

The weakness is not primarily lack of detection. The weakness is the missing reliable
connection from detected state to the canonical owner that can repair or recompute it.
A failed or late scheduled step can therefore leave a downstream consumer stale until a
later timer happens to rerun the necessary owner.

## Architectural direction

Prefer a state-driven runtime model over a collection of independently timed pipelines.
Timers remain only where clock boundaries or watchdog wakeups are useful.

The intended pattern is:

```text
facts / canonical persisted state
        |
        v
owner evaluates its own domain health
        |
        +--> healthy
        |
        +--> repairable requirement
                  |
                  v
          persisted runtime requirement
                  |
                  v
             dispatcher
                  |
                  v
        canonical owner runner
                  |
                  v
          new canonical facts/state
```

Modules must not directly bypass ownership boundaries by invoking arbitrary downstream
or upstream implementation modules. They may publish declarative requirements. A small
runtime dispatcher resolves requirement type to the canonical owner runner.

## Ownership rule

Each domain owner should own three things:

1. its canonical state;
2. its health/freshness evaluation;
3. declarative repair/recompute requirements when that state is repairable.

The dispatcher owns retries and invocation, not domain logic.

Examples:

| Detecting owner | Detected condition | Declarative requirement | Repair owner |
|---|---|---|---|
| candle freshness | expected candle missing | `CANDLE_HEAD_REQUIRED` | public candle freshness writer |
| Native SHORT materializer | primary/supporting candle stale or missing | `CANDLE_HEAD_REQUIRED` or `CANDLE_HISTORY_REQUIRED` | public candle freshness writer |
| Native SHORT materializer | map invalidated or no valid current map | `NATIVE_SHORT_REEVALUATION_REQUIRED` / `MAP_REEVALUATION_REQUIRED` | Native SHORT owner |
| feature owner | candle history incomplete | `CANDLE_HISTORY_REQUIRED` | public candle freshness writer |
| selection owner | required market feature stale/missing | `FEATURE_REFRESH_REQUIRED` | feature owner |
| Profit Plan / reporting health | upstream defect visible but no active repair request exists | same canonical requirement as safety net | canonical upstream owner |

Profit Plan remains a reporting consumer. It must not fetch Bitvavo data, generate Fib
maps, write market truth, or perform strategy recomputation. It may act as an additional
sensor by publishing a declarative requirement when it can prove an upstream input is
missing or stale and no equivalent active requirement already exists.

## Native SHORT specific flow

The Native SHORT materializer/status projection already has sufficient domain context to
identify many repair conditions. It reads persisted primary `4h` and supporting `1h`
market inputs and records current status in `native_short_scope_status_v1`.

Desired behavior:

```text
Native SHORT evaluates scope
        |
        +--> inputs current, map valid
        |       -> normal state
        |
        +--> expected 4h/1h candle missing
        |       -> persist stale/missing status
        |       -> publish candle requirement
        |
        +--> map invalidated / expired / missing
                -> persist lifecycle state
                -> publish Native SHORT reevaluation/map requirement
```

The materializer should not recursively launch repair subprocesses itself. This would
risk duplicate writers, recursion, ownership bypass, and uncontrolled retry loops.
Instead it publishes the requirement and lets the dispatcher invoke the canonical owner
under its normal lock and authorization boundary.

## Bitvavo 4h boundary signaler

A lightweight Bitvavo head checker is a promising replacement for blind timing around
4h candle closes.

Concept:

```text
4h UTC boundary
      |
      v
small Bitvavo head checker
      |
      +--> expected new closed 4h candle not visible
      |       -> bounded retry/backoff
      |
      +--> expected closed 4h candle visible
              -> publish `BITVAVO_4H_BOUNDARY_AVAILABLE`
              -> wake candle freshness owner
```

The checker should not perform full-universe ETL. It only establishes that the exchange
has crossed the new closed-candle boundary. A liquid reference market such as BTC-EUR
may be sufficient for the exchange-level signal, but this must not be confused with
per-symbol availability: the candle freshness owner must still validate and repair each
required market individually.

This produces a layered model:

```text
1. exchange boundary available
2. per-symbol candle freshness complete
3. Native SHORT scope inputs complete
4. Native SHORT lifecycle/map current
5. downstream features/selection/reporting current
```

## Retry and external failure behavior

Requirements must be stateful so an exchange delay or outage does not produce an
unbounded fix loop.

Suggested lifecycle:

```text
PENDING
RUNNING
RETRY_WAIT
SATISFIED
BLOCKED_EXTERNAL
FAILED_PERMANENT
```

Useful metadata includes:

```text
attempt_count
first_detected_at_utc
last_detected_at_utc
last_attempt_at_utc
next_attempt_at_utc
last_error_code
last_error_detail
claimed_by
claimed_at_utc
satisfied_at_utc
```

Requirements must deduplicate by semantic identity. For example there may be only one
active request for:

```text
CANDLE_HEAD_REQUIRED / bitvavo / CC-EUR / 4h / expected_close=2026-08-07T16:00:00Z
```

Multiple detectors may observe the same deficiency, but they must converge onto the
same active requirement rather than create duplicate work.

Backoff must distinguish likely exchange latency from persistent external failure. A
Bitvavo 5xx/outage or universe-wide delayed candle publication should move requests
into a bounded retry/external-blocked state rather than continuously rerunning the
writer.

## Timer direction

Do not remove all timers blindly. Replace business orchestration timers with state
transitions where possible.

Keep timers for:

- natural exchange/time boundaries where no event source exists;
- a lightweight dispatcher/watchdog heartbeat;
- recovery of abandoned `RUNNING` work;
- overdue requirement inspection;
- low-frequency safety-net reconciliation.

Avoid a runtime that depends primarily on fixed offsets such as:

```text
:02 candle writer
:12 Native SHORT
:20 snapshot importer
5-minute reporting render
```

A failed `:02` candle run should not force Native SHORT to wait until the next 4h cycle
if the missing candle becomes available at `:17`.

Desired behavior is instead:

```text
4h boundary available
    -> candle requirement
    -> candle owner succeeds
    -> Native SHORT reevaluation requirement
    -> Native SHORT owner succeeds
    -> dependent state becomes current
```

## Possible coordination table

Before creating new schema, inventory existing runtime/freshness/recompute tables and
reuse a suitable canonical owner if one exists. If no generic coordination primitive
exists, a minimal persisted table such as `runtime_requirement_v1` is a candidate.

Conceptual fields only:

```text
requirement_id
requirement_type
entity/scope key
requested_by_owner
reason_code
status
priority
first_detected_at_utc
last_detected_at_utc
next_attempt_at_utc
attempt_count
claimed_by
claimed_at_utc
last_error_code
last_error_detail
satisfied_at_utc
```

The table must contain orchestration state only. It must not become a second source of
market truth, strategy state, account state, decision state, or execution state.

## Existing mechanisms to inventory before implementation

At minimum inspect and classify:

- `public_candle_freshness` and its stale/per-symbol behavior;
- `src/reporting/run_fast_recompute_lifecycle_v1.py`;
- `src/reporting/fast_lifecycle_recompute_v1.py`;
- Native SHORT scope/status materializer and `native_short_scope_status_v1`;
- any older freshness lifecycle updater;
- any stale-token/market worklist runner;
- held-market enrollment mechanisms;
- Profit Plan missing/stale/recompute classifications;
- current writer capability ownership and locks;
- current timers and historical scheduler implementations.

For each existing mechanism determine:

1. whether it is canonical, legacy, research-only, or obsolete;
2. what exact state it detects;
3. whether it writes canonical state or only renders a worklist;
4. whether it already supports bounded per-symbol repair;
5. whether it can be adapted to the requirement/dispatcher model;
6. whether an existing timer can subsequently be retired.

## Universe scope

Do not prematurely reduce the market universe merely to make orchestration easier.
Steady-state candle and lightweight market processing over the full Bitvavo universe is
expected to be manageable; historical backfill and expensive analysis should be
bounded and demand-driven.

Preferred distinction:

```text
full Bitvavo universe
    -> prices / candles / lightweight freshness

selection universe
    -> market-only ranking and selection

active/deep analysis universe
    -> richer map/lifecycle work when justified

account-relevant universe
    -> held assets / open orders / account plans
```

Benchmark before constraining Native SHORT or other deeper processing to an arbitrary
portfolio-only universe.

## Hard architecture boundaries

This direction must preserve:

```text
selection_engine   = market-only, account-agnostic
decision_gate      = account-aware permission layer
execution_planner  = execution intent only
executor / agents  = order handling
reporting          = read-only presentation/consumer of canonical truth
```

A runtime requirement may request a canonical owner to run, but must never be used as a
shortcut around these layers.

## Next step

Perform a repository and git-history audit of all existing freshness, stale-market,
lifecycle, recompute, and retry mechanisms before designing schema or code.

Deliver:

- current mechanisms and owners;
- canonical vs legacy classification;
- duplicate/obsolete mechanisms;
- missing state transitions;
- which timers can be replaced by state-driven dispatch;
- minimal integration design reusing existing runners;
- only then propose implementation issues/PR sequence.
