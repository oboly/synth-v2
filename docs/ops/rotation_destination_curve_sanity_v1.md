# Rotation Destination Curve Sanity V1

## Scope

This change is reporting/dashboard only.

Files:

- `src/reporting/rotation_destination_eligibility_v1.py`
- `src/reporting/run_position_rotation_static_dashboard_v1.py`
- `tests/test_rotation_destination_eligibility_v1.py`

No selection, decision, execution, broker, order, or account-mutation paths are changed.

## Purpose

Rotation destinations were previously filtered by setup, lifecycle, target distance, and A+/market context, but they did not surface a compact read of whether the destination still shows visible upside confirmation.

This adds a curve sanity label so weak or damaged destination structures stay visible as market-review context without appearing as clean rotation destinations.

## Curve Sanity Labels

- `CURVE_UP_CONFIRMED`
- `CURVE_NEUTRAL`
- `CURVE_WEAK`
- `CURVE_DOWN_PRESSURE`
- `CURVE_FAILED_RECLAIM`
- `CURVE_NO_UP_SIGNAL`

## Reporting Rules

- `CURVE_UP_CONFIRMED` is the only curve state that can remain clean/actionable in the rotation destination dashboard.
- `CURVE_WEAK` downgrades to `LOW_CONFIDENCE_DESTINATION`.
- `CURVE_DOWN_PRESSURE`, `CURVE_FAILED_RECLAIM`, and `CURVE_NO_UP_SIGNAL` downgrade to non-clean destination context.
- Missing curve context also stays non-clean and is surfaced as market-only/low-confidence context.
- Fresh `A+` context is still required for high confidence. Aging `A+` context can remain medium confidence when the curve is already up-confirmed.

## Inputs Used

The curve sanity label uses only existing dashboard/reporting context that is already available in the rotation preview:

- leg direction
- target state
- risk state
- lifecycle/recompute state
- price progress state and labels
- next-zone / reclaim / target labels
- existing confirmation display state

No DB schema changes were added.

## UI

The dashboard now shows the curve sanity pill directly under destination confidence in candidate diagnostics, and the compact rotation-destination string includes the curve sanity label.

Dashboard note added:

`Curve sanity checks whether the destination has visible up-confirmation. Weak/down-pressure curves lower destination confidence; not trade advice.`

## KITE Regression Intent

KITE may remain visible as a market review reference.

KITE should not appear as a clean/high-confidence rotation destination when:

- no visible up confirmation is present
- curve context is weak or under down pressure
- A+ context is missing or stale
