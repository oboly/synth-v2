# Automatic exit policy V1

## Boundary

The automatic exit-policy candidate evaluator belongs inside `decision_gate`
as a pure account-aware input evaluator. It needs a held-position identity,
which market-only layers cannot receive, but it does not make permission or
execution decisions. Keeping it in `decision_gate` avoids a second
account-aware runtime layer while preserving the canonical flow:

```text
position + market exit context
-> automatic_exit_candidate_v1
-> decision_gate permission/risk/conflict validation
-> execution_planner immutable SELL ladder
-> executor
```

`selection_engine` remains market-only and account-agnostic. Reporting stays
read-only. The evaluator never writes state, builds broker payloads, resolves
base quantity, creates a manual request, calls the planner/executor, or grants
permission.

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
`NON_ACTIONABLE`.

## Deferred work

This V1 module is not scheduled or wired to persistence, `decision_gate`
permission, `execution_planner`, manual-execution artifacts, executor, or
LIVE authority. Those changes require separately reviewed phases.
