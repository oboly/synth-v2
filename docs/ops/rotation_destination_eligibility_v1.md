# Rotation Destination Eligibility v1

## Purpose

Rotation dashboard market review references and rotation destinations serve different jobs.

Market review refs are broad comparison assets. They can include symbols with strong market-only ranking, useful watch context, or relative-score information even when the current setup is not practical for a long/add rotation now.

Rotation destinations are stricter actionable-review candidates. They are still not trade advice, not order intent, and not execution permission.

## Eligibility Rules

A candidate is excluded from rotation destinations when any strict destination rule fails:

- `setup_filter_state` is not `PASS`, or setup context contains `SETUP_FILTER_FAIL`.
- Selection state is not eligible, neutral, or watch/buy-like.
- Active leg is `DOWN`, because the relevant target is downside/reaction context rather than a long/add destination.
- Relevant target distance is negative for a long/add destination.
- Action or display state says `NO_CHASE_WITHOUT_NEW_ZONE`.
- Policy display label says `BLOCK_SETUP_FILTER_FAIL`.
- Policy display label says `BLOCK_RECOMPUTE_PENDING` while the post-refresh state is not clean.
- Target state is `TARGET_REACHED` / `TARGET_OVERSHOT` without fresh continuation or retest context.
- Critical data/display context is missing, unknown, or structurally invalid.
- Invalidation or recomputed-still-triggering context is present.

## Exclusion Reasons

The dashboard uses compact reason labels for destination exclusions:

- `EXCLUDED_SETUP_FAIL`
- `EXCLUDED_SELECTION_NOT_ELIGIBLE`
- `EXCLUDED_DOWN_LEG_TARGET`
- `EXCLUDED_NEGATIVE_TARGET_DISTANCE`
- `EXCLUDED_NO_CHASE`
- `EXCLUDED_RECOMPUTE_PENDING`
- `EXCLUDED_TARGET_ALREADY_REACHED`
- `EXCLUDED_CRITICAL_CONTEXT`

## Display Contract

The dashboard keeps market review refs broad and displays them as comparison context.

The rotation destinations column only displays candidates that pass destination eligibility. If no candidate passes, it displays `No actionable destination`.

Dashboard note:

> Market review refs are broad comparison assets. Rotation destinations are stricter actionable-review candidates, not trade advice.

## Safety Boundary

This is reporting/dashboard-only classification over already assembled context.

It does not change selection, decision gate, execution planner, executor, broker calls, broker order writes, order submission, or account state.
