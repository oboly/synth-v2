# Dashboard Candidate Readiness Axis V1

## Purpose

The entry dashboard now shows a display-only candidate readiness axis.

It is:

- market/setup context only
- reporting-only
- not order permission
- not a `decision_gate` bypass
- not an `execution_planner` bypass

## Axis

Axis name:

- `candidate_readiness_pressure`

Range:

- `-10 .. 0 .. +10`

Mapping:

- `AVOID = -10`
- `BLOCKED_NO_NEW_BUY = -6`
- `CAUTION = -3`
- `WAIT = 0`
- `CORE_CONTEXT = +2`
- `WATCH_FOR_CONFIRMATION = +4`
- `BUY_CANDIDATE = +6`
- `ENTRY_CANDIDATE = +8`
- `BUY_READY = +10`

## Interpretation

- `CORE_CONTEXT` means positive structural context, not an entry trigger.
- `WAIT` means neutral/no setup, not blocked.
- `AVOID` means unfavorable context for new adds or new buys.
- `BLOCKED_NO_NEW_BUY` means a true no-new-buy block. The cause/unblock text still matters.
- `BUY_READY` means market/setup side is ready for evaluation only. It is still not order permission.
- `INSUFFICIENT_SAMPLE` is separate from the signed axis. It is data unknown, not bearish.

## Entry Dashboard

The entry dashboard summary now separates readiness buckets instead of collapsing:

- positive context
- neutral wait
- avoid
- true block
- data unknown

This answers:

1. Is this buy-ready?
2. If not, why not?
3. Is it positive context, neutral wait, avoid, true block, or data-unknown?

## Boundary

- UI/reporting only
- no `selection_engine` changes
- no advice logic changes
- no `decision_gate` changes
- no `execution_planner` changes
- no `executor` changes
- no broker calls
- no broker writes
- no orders
