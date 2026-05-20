# Cockpit Semantic State Precedence Cleanup v1

This change is dashboard/reporting only. It does not change market logic, selection behavior, decision gate permissions, execution planning, executor behavior, broker calls, or order handling.

## Display Precedence

Cockpit pages now use a display-only precedence helper for entry labels:

1. `TARGET_REACHED` / `DOWNSIDE_TARGET_REACHED`
2. `ENTRY_WINDOW_PASSED`
3. `POST_ENTRY_PROGRESS`
4. `IN_ENTRY_ZONE` / `IN_REACTION_ZONE`
5. `ENTRY_ZONE_NEAR` / `REACTION_ZONE_NEAR`
6. `ENTRY_ZONE_PENDING` / `REACTION_ZONE_PENDING`
7. `UNKNOWN`

The raw entry state is still available in muted text where useful. This avoids showing `ENTRY_ZONE_NEAR` as the primary state when price progress already says the entry window has passed or post-entry movement is underway.

## Target And Extension Context

When a row is generic `CONTEXT_ONLY_WAIT_FOR_MARKET_SETUP` but lifecycle or intrabar context shows target touch, stale target, overshot target, or extension, dashboards prefer more specific display labels:

- `TARGET_REACHED_WAIT_FOR_REMAP`
- `EXTENSION_REVIEW_NO_CHASE`
- `NO_CHASE_WITHOUT_NEW_ZONE`

These are labels only. They do not create buy/sell permission and do not alter paper advice rows.

## Policy Block Versus Market Context

Policy/action labels and next-zone previews are intentionally separate. A row may show:

- policy/action: `DO_NOT_ADD`, `BLOCKED`, or `WATCH_ONLY`
- market context: `RECLAIM_NEXT_ZONE_PREVIEW`

Dashboards include the note: "Market context, not permission." Next-zone preview remains market context only.

## Entry Distance

Rotation dashboard entry distance is now displayed with leg-aware words instead of a bare signed percentage:

- BUY/up context above entry: `above entry +x%` as warning
- BUY/up context inside entry: `inside entry`
- BUY/up context below entry: `below entry -x%` as muted/wait
- DOWN/reaction context uses reaction-zone wording

The underlying price and zone values are not changed.

## Boundary

This task changes display semantics only:

- no broker calls
- no broker writes
- no order submission
- no live orders
- no decision gate changes
- no execution planner changes
- no executor changes
- no selection engine behavior changes
