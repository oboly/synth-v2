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

## Phase 2: account permission boundary

`decision_gate.automatic_exit_gate_v1` now provides a pure, caller-assembled
permission contract from `AutomaticExitCandidateV1` to
`AutomaticExitGateDecisionV1`. It has no persistence, runtime wiring,
manual-execution request/approval dependency, planner, executor, or broker
dependency.

The context binds the exact account, position reference, venue, asset, and
market; identifies the position snapshot; supplies held/free quantity,
reservation-or-open-order conflict state, account mode and explicit lane
permission; and gives explicit timestamps and freshness limits. Ambiguous,
missing, mismatched, naïve, future, or stale evidence is `NON_ACTIONABLE`.
Explicit policy prohibitions (disabled account/lane, non-paper or LIVE fact,
blocking conflict, zero free quantity) are `DENIED`. Only healthy matching
facts yield `APPROVED`.

An approved result preserves the candidate object and its fraction/provenance
unchanged. Its `approved_quantity_ceiling_base` is not a strategy rewrite: it
is `min(candidate fraction × fresh held quantity, fresh free quantity,
optional account risk cap)`. It exists so a later planner cannot bypass
account safety; it contains no ladder, prices, broker payload, or order.

Later phases may add controlled persistence, planner consumption, and runtime
wiring only with separately reviewed authority boundaries.
