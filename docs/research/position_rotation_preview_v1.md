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

These do not replace `rotation_state`. They clarify how to read it.

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
