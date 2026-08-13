# Automatic exit policy V1

## Boundary

The automatic exit-policy candidate evaluator belongs in the narrow,
account-aware `exit_policy` package. It needs a held-position identity, which
market-only layers cannot receive, and it determines exit-policy intent:
target/invalidation trigger semantics, `REDUCE` versus `EXIT`, fraction
candidate, and urgency. Those are not account permission decisions.

```text
position + market exit context
-> exit_policy.automatic_exit_candidate_v1
-> decision_gate permission/risk/conflict validation
-> execution_planner immutable SELL ladder
-> executor
```

`selection_engine` remains market-only and account-agnostic. `decision_gate`
answers only whether the proposed candidate may proceed for the account.
Reporting stays read-only. The evaluator never writes state, builds broker
payloads, resolves base quantity, creates a manual request, calls the
planner/executor, or grants permission.

## V1 contract

`evaluate_automatic_exit_candidate_v1` takes explicit position and market
exit-context observations plus an explicit evaluation timestamp. It returns
exactly one of:

- `NO_ACTION`: no held quantity or no target/invalidation condition is met.
- `NON_ACTIONABLE`: position/profile evidence is stale, missing, malformed,
  mismatched, or policy fractions are unsafe.
- `CANDIDATE`: a typed `REDUCE` or `EXIT` candidate carrying only a bounded
  reduction-fraction candidate, urgency, reason, position identity, and
  target/profile evidence.

V1 uses a 25% reduction candidate when the active target is reached and a
100% candidate when invalidation is breached. These are candidates only;
`decision_gate` must validate live account availability, reservations, risk,
and conflicts before any planner call. No final base quantity exists in this
contract.

Freshness is explicit and defaults to fifteen minutes for both input classes.
The passed evaluation timestamp makes same-input/same-output deterministic.
Missing required profile provenance or an invalid price fails closed to
`NON_ACTIONABLE`. All timestamps must be timezone-aware UTC instants; naïve
timestamps fail closed to `NON_ACTIONABLE` rather than being assumed UTC.

## Deferred work

This V1 module is not scheduled or wired to persistence, `decision_gate`
permission, `execution_planner`, manual-execution artifacts, executor, or
LIVE authority. Those changes require separately reviewed phases.
