# Position Rotation Preview V1

## Purpose

`run_position_rotation_preview_v1.py` is a read-only, account-aware review tool for existing positions.

Its output is for position management context only. It is not new-buy permission, not decision-gate behavior, and not order logic.

## HOLD Versus Add Semantics

Important distinction:

- `rotation_state=HOLD` means keep the existing position or no current reduce pressure
- it does **not** mean permission to buy or add

This matters because a symbol can still be blocked for new adds while an existing position remains a hold/review case.

Examples of add/new-buy blockers:

- `DO_NOT_ADD`
- `AVOID_NO_NEW_BUY`
- `WATCH_ONLY`
- `WAIT`
- `APLUS_AVOID`
- `selection_state = AVOID`
- `setup_filter_state = FAIL`
- `RECLAIM_CONFIRMED` requiring recompute/review first

TP distance can still be positive while new buy remains blocked.

## Derived Read-Only Fields

The preview now includes additive semantics fields:

- `position_management_state`
- `add_permission_state`
- `add_block_reason`
- `hold_context_label`
- `entry_alignment_label`
- `entry_fib_distance_pct`
- `tp_alignment_label`
- `tp_fib_distance_pct`
- `entry_is_fib_band`
- `tp_is_fib_extension_band`

These do not replace `rotation_state`. They clarify how to read it.

## Dashboard UI Wording

The static dashboard now applies UI-only display wording on top of the raw
read-only fields. Raw values remain unchanged in Python row objects and JSON
outputs.

Display groups:

- `HOLD`
- `WAIT`
- `MANUAL CHECK`
- `INCREASE CANDIDATES`
- `EXIT CANDIDATES`

Primary dashboard labels:

- `REDUCE_CANDIDATE` -> `HOLD_DEFENSIVE` by default for existing holdings.
- `REDUCE_CANDIDATE` -> `MANUAL_REDUCE_CHECK` only when explicit reduce context
  exists.
- `EXIT_CANDIDATE` -> `HOLD_DEFENSIVE` by default for existing holdings.
- `EXIT_CANDIDATE` -> `MANUAL_EXIT_CHECK` only when explicit exit context
  exists.
- `RECLAIM_CONFIRMED_REVIEW` -> `WAIT_RECOMPUTE`
- `DO_NOT_ADD` -> `NO_INCREASE`
- `ADD_REVIEW_AFTER_RECOMPUTE` -> `WAIT_RECOMPUTE_FOR_INCREASE`
- `HOLD_WITH_REACTION_TARGET_PENDING` -> `HOLD_MONITOR_TARGET`

Interpretation rule:

- `MANUAL_*` labels mean user decision is required.
- `HOLD_*` and `WAIT_*` labels do not imply manual trade action.
- Sell or increase still requires downstream permission.

### Mapping

- `rotation_state = HOLD` -> `position_management_state = HOLD_EXISTING`
- `advice_action in {BUY_READY, ACCUMULATE, BUY}` and `setup_filter_state = PASS` and `selection_state != AVOID`
  -> `add_permission_state = ADD_REVIEW`
- `advice_action in {DO_NOT_ADD, AVOID_NO_NEW_BUY, WATCH_ONLY, WAIT}` -> `add_permission_state = DO_NOT_ADD`
- `setup_filter_state = FAIL` -> `add_permission_state = DO_NOT_ADD`
- `selection_state = AVOID` -> `add_permission_state = DO_NOT_ADD`
- `APLUS_AVOID` -> `add_permission_state = DO_NOT_ADD`
- `RECLAIM_CONFIRMED` -> `add_permission_state = ADD_REVIEW_AFTER_RECOMPUTE`
- `TARGET_PENDING` with remaining TP room -> `hold_context_label = HOLD_WITH_REACTION_TARGET_PENDING`
- `TARGET_REACHED` -> `hold_context_label = TARGET_REACHED_REVIEW`

## Zone/Fib Context

The preview now adds read-only zone/fib context directly from DB sources:

- `execution_zone_context`
- `fib_observation_v2` when available, otherwise `fib_observation`
- `asset`

It does not read ignored research CSV outputs.

These fields are descriptive only. They do not change `rotation_state`, `position_management_state`, or `add_permission_state`.

### Entry Labels

- `ENTRY_FIB_PRIMARY_0500_0618`
- `ENTRY_FIB_DEEP_0618_0786`
- `ENTRY_SR_ONLY`
- `ENTRY_UNKNOWN`

### TP Labels

- `TP_FIB_EXTENSION_1272_1618`
- `TP_NEAR_FIB_EXTENSION`
- `TP_SR_ONLY`
- `TP_UNKNOWN`

## Zone Wording

Dashboard wording treats below-price zones on existing long holdings as support
or retest context, not TP.

- below current price -> `SUPPORT_BELOW` or `RETEST_ZONE_BELOW`
- above current price -> `UPSIDE_REACTION_TARGET`
- reclaimed/invalidated old map -> `WAIT_RECOMPUTE`

Helper rule:

```text
below-price support/retest context, not TP
```

## Boundary

- read-only preview only
- no broker writes
- no order submission
- no `selection_engine` changes
- no `decision_gate` changes
- no `execution_planner` changes
- no `executor` changes
- no exit behavior change

## Interpretation Rule

Use:

```text
rotation_state -> existing-position pressure
add_permission_state -> whether add/new-buy review is even allowed
```

Not:

```text
rotation_state = HOLD -> safe to add
```
