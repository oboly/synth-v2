# Explicit Policy Block Reasons v1

## Purpose

The cockpit previously surfaced broad labels such as `BLOCK_24H`, `BLOCK_FOR_24H`, `BLOCKED_NO_NEW_BUY`, `NO_NEW_BUY`, and `DO_NOT_ADD` as the primary visible state. Those labels are useful raw policy states, but they hide the operational reason a row is blocked.

This display layer keeps the raw value and adds an explicit readable classification:

- `raw_policy_state`
- `block_primary_reason`
- `block_reason_codes`
- `block_ttl_label`
- `unblock_condition_label`
- `display_policy_label`
- `display_policy_severity`

Example display:

`Raw policy: BLOCK_24H`

`Cause: RECOMPUTE_PENDING`

`Unblock: after fresh zone/advice recompute or cooldown clears`

## Display Model

`src/reporting/policy_block_reason_display_v1.py` classifies existing dashboard row fields only. It does not read broker state, mutate state, or change advice generation. The classifier is intentionally a reporting helper so dashboards can explain current states without changing selection, decision, planning, or execution behavior.

Primary mappings:

- `MARKET_DAMAGE_RISK` or `MARKET_DAMAGE_CAUTION` -> `BLOCK_MARKET_DAMAGE`
- setup filter non-pass states -> `BLOCK_SETUP_FILTER_FAIL`
- selection ineligible states -> `BLOCK_SELECTION_NOT_ELIGIBLE`
- map lifecycle and recompute triggers -> `BLOCK_RECOMPUTE_PENDING`
- target reached, overshot, post-entry progress, or no-chase context -> `BLOCK_CHASE_RISK`
- insufficient market/sample data -> `BLOCK_INSUFFICIENT_SAMPLE`
- stale or very-stale A+ avoid -> `LEGACY_CONTEXT_ONLY`
- fresh/aging A+ avoid context -> `READ_ONLY_APLUS_AVOID_CONTEXT`
- unmatched blocked rows -> `BLOCK_POLICY_UNCLASSIFIED`

## Severity Mapping

Dashboard severity is display-only:

- critical/red: true invalidation, recomputed-but-still-triggering, critical missing market data
- warn/yellow: recompute pending, market damage caution, chase risk, setup fail
- muted/grey: not selected, no-new-buy context, stale A+ context, insufficient sample when non-critical

Generic no-new-buy states should not be colored as hard red unless the primary reason is critical.

## Raw State vs Display State

The raw policy state remains visible as muted context. The explicit display label becomes the primary visible pill when a block cause can be derived.

This preserves auditability while making rows easier to read. For example, `BLOCK_24H` can be shown as `BLOCK_RECOMPUTE_PENDING`, `BLOCK_SETUP_FILTER_FAIL`, or `BLOCK_CHASE_RISK` depending on the row's existing reason fields.

## A+ Legacy Handling

A+ Table 1/2 labels are legacy external symbolic context. Stale or very-stale `APLUS_AVOID` must not become a hard current veto by itself in cockpit display. It is shown as `STALE_APLUS_CONTEXT` / `LEGACY_CONTEXT_ONLY` unless other current market or policy reasons explain the block.

Fresh or aging A+ avoid remains read-only context and does not grant or remove live permission.

## Safety Boundary

This is reporting and policy display only.

- no live trading enabled
- no broker calls
- no broker writes
- no order submission
- no live orders
- no executor activation
- no decision gate permission changes
- no execution planner changes
- no selection engine behavior changes

## Changed Pages

- paper advice dashboard
- entry candidates dashboard
- position rotation dashboard

Each page now shows explicit cause/unblock text for blocked/no-new-buy style rows where enough row context exists.

## Follow-Up

The current `block_ttl_label` remains a display abstraction. A later task should replace fixed 24h-style wording with reason-driven unblock conditions after validating the operational cadence for each cause.
