# TODO — News Catalyst Monitor

> **Migration pointer — PARTIAL migration only.** GitHub Issue
> [#228 — Design external catalyst monitor schema and dry runner](https://github.com/oboly/synth-v2/issues/228)
> owns **only** the "P0 design task" section below (DB schema/migration
> draft proposal and a read-only/dry-run ingestion skeleton for
> `external_catalyst_monitor_v1`). Current status, priority, blockers,
> acceptance criteria, next action, and closure for that scope belong to
> Issue #228.
>
> Production selection/dashboard consumption of catalyst context (see
> "Dashboard integration" and "Relationship to idiosyncratic catalyst
> override" below) remains **unmigrated** — no Issue owns it. Do not
> represent that scope as Issue-owned, filed, or in progress.
>
> This file must not become a parallel status board for the migrated scope.
> The design content above and below (core idea, schema proposals, event
> types, impact model) is preserved as historical/design context.
>
> See `docs/development/github_issues_workflow.md`,
> `docs/todo/MIGRATION_FREEZE.md`, and
> `docs/development/github_issues_batch_2b_migration_v1.md`.

## Status

Research / read-only ingestion lane.

This document captures the idea of running a scheduled news/catalyst monitor that stores important market-moving items in the database and exposes event windows / impact flags to dashboards.

## Core idea

Run a scheduled monitor, for example every 12 hours, that:

```text
collects relevant news
normalizes catalyst events
links events to assets / themes / regimes
stores raw + normalized records in DB
flags when an event is active, upcoming, stale, or invalidated
exposes context to dashboards
```

This is not a trading agent.

Correct path:

```text
news source
-> raw_news_event
-> normalized_catalyst_event
-> asset/theme/regime links
-> dashboard/research flags
-> later validation
```

Not:

```text
news source
-> direct BUY_READY
news source
-> decision_gate permission
news source
-> execution_planner
news source
-> order
```

## Proposed module name

```text
external_catalyst_monitor_v1
```

Alternative names:

```text
news_catalyst_monitor_v1
external_event_monitor_v1
catalyst_event_registry_v1
```

## Schedule

Initial cadence:

```text
every 12 hours
```

Rationale:

```text
slow enough to avoid noisy overreaction
fast enough to catch institutional announcements, macro shocks, token unlocks, regulatory events, and catalyst windows
```

A higher-frequency lane can be designed later for time-critical events, but not in v1.

## Inputs

Potential v1 sources:

```text
official project/company announcements
official regulator / exchange / infrastructure announcements
trusted external PRO/RV/Martee notes
major crypto / finance news sources
macro calendar items
known future event windows from prior research notes
```

Important:

```text
prefer official/primary sources where possible
store external narrative notes separately from verified official announcements
```

## Suggested raw DB table

```text
external_raw_news_event
```

Suggested fields:

```text
raw_event_id
source_name
source_url
source_type
published_ts_utc
fetched_ts_utc
title
summary_text
raw_text_hash
language
source_reliability_prior
ingestion_run_id
```

## Suggested normalized DB table

```text
external_catalyst_event
```

Suggested fields:

```text
catalyst_event_id
raw_event_id
normalized_event_code
event_type
primary_asset_symbol
related_asset_symbols
theme_codes
macro_regime_relevance
event_date_utc
active_from_ts_utc
active_until_ts_utc
next_event_window_start
next_event_window_end
source_confidence
impact_prior
impact_direction
impact_horizon
requires_confirmation
invalidates_if
notes
created_at_utc
```

## Suggested asset link table

```text
external_catalyst_asset_link
```

Suggested fields:

```text
catalyst_event_id
asset_symbol
link_role
expected_impact_channel
relative_strength_required
volume_confirmation_required
liquidity_check_required
status
```

## Event types

Initial enum candidates:

```text
INSTITUTIONAL_RAILS
TOKENIZATION_RWA
REGULATORY_CLARITY
ETF_FLOW_OR_APPROVAL
EXCHANGE_LISTING
UNLOCK_SUPPLY_PRESSURE
PROTOCOL_UPGRADE
PARTNERSHIP_INTEGRATION
MACRO_SHOCK
GEOPOLITICAL_RISK
SECURITY_INCIDENT
NARRATIVE_REPRICING
```

## Output labels

Dashboard/research labels only:

```text
CATALYST_ACTIVE
CATALYST_UPCOMING
CATALYST_EXPIRED
IDIOSYNCRATIC_CATALYST_OUTPERFORMANCE
DIRTY_SQUEEZE_ACTIVE
THEME_ROTATION_ACTIVE
WAIT_FOR_RETEST
TP_REVIEW_IF_POSITIONED
DO_NOT_FLIP_GLOBAL_REGIME
LOW_CONFIDENCE_NEWS_ONLY
OFFICIAL_SOURCE_CONFIRMED
```

## Impact model

A catalyst should not immediately become a signal. V1 should separate:

```text
catalyst exists
market reacted
volume confirmed
relative strength confirmed
price is near target/resistance
entry quality after spike
```

Example logic:

```text
macro caution active
+ official asset-specific catalyst
+ asset return 24h/72h materially above BTC
+ volume expansion
= catalyst outperformance flag
```

But still:

```text
no global regime flip
no automatic buy
no execution bypass
```

## Dashboard integration

Manual Ladder Dashboard can later show:

```text
active catalyst label
source name
published date
next event window
impact horizon
asset/theme affected
confirmation required
entry quality after spike
WAIT_FOR_RETEST / TP_REVIEW_IF_POSITIONED context
```

This should appear as contextual interpretation, not as a primary order instruction.

## Relationship to idiosyncratic catalyst override

This lane feeds:

```text
idiosyncratic_catalyst_override_v1
```

Example:

```text
XLM + DTCC/STELLAR_PUBLIC_CHAIN_TOKENIZATION
-> official catalyst stored
-> XLM relative strength spike detected
-> DIRTY_SQUEEZE_ACTIVE
-> DO_NOT_FLIP_GLOBAL_REGIME
```

## Boundaries

```text
Research-only initially
Read-only news/external source calls
DB writes only to external research/catalyst tables
No selection_engine changes until validated
No decision_gate bypass
No execution_planner changes
No executor changes
No orders
No broker private calls
No broker writes
No live trading
```

## Validation questions

Before any downstream promotion, answer:

```text
Do official institutional catalysts predict sustained relative strength?
Which catalyst types create dirty squeezes versus clean continuation?
Does waiting for retest improve entry quality after catalyst spikes?
Which themes propagate to related assets and which remain single-asset events?
How often does an idiosyncratic catalyst falsely look like a global regime change?
```

## P0 design task

Design a DB schema and dry runner for:

```text
external_catalyst_monitor_v1
```

Minimum v1 deliverables:

```text
schema proposal only or migration draft
read-only/dry-run source ingestion skeleton
manual seed option for known events
summary output table
safety markers
research doc
```

Initial seed events can include:

```text
XLM / DTCC_STELLAR_PUBLIC_CHAIN_TOKENIZATION / 2026-05-27 / 2027-H1 next window
LINK / DTCC_COLLATERAL_APPCHAIN_CCIP / institutional rails theme
CC / DTCC_CANTON_INSTITUTIONAL_RAILS / institutional rails theme
ONDO / TOKENIZED_SECURITIES_REGULATORY_CLARITY / RWA theme
PLUME / RWA_PLUMBING_EXTERNAL_LIST_ADDITION / RWA theme
```
