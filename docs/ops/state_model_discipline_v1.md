# State Model Discipline v1

## Purpose

This contract prevents local error handling from accidentally becoming the wrong system model.

Before adding or tightening a gate, blocker, lifecycle transition, eligibility rule, or special-case state, define the intended steady state, degraded state, and downstream/user-visible behavior first.

## Core rule

Always distinguish **structural lifecycle/ownership state** from **temporary runtime/data-health state**.

A temporary health condition must not change structural ownership or lifecycle state unless the canonical contract explicitly requires that coupling for a named safety invariant.

Examples of orthogonal state dimensions:

```text
scope_support_state = SUPPORTED
source_health = CURRENT | STALE | MISSING_CANDLES
runtime_state = ACTIVE | BOOTSTRAP_PENDING | BLOCKED
approval_state = ACCEPTED | ABSENT | INVALID
```

Do not collapse these dimensions into combined special-case states when the existing fields already compose to the required meaning.

## Required reasoning sequence

Before implementation:

1. Define the desired steady-state behavior.
2. Define the degraded-state behavior.
3. Define what downstream consumers and reporting surfaces should show.
4. Identify which state dimension owns the condition.
5. Ask whether the condition is structural or temporary.
6. Check whether existing canonical fields already express the required meaning.
7. Only then decide whether a new gate, state, transition, or field is needed.

Use this stop-question before creating or tightening a fail-closed gate:

> Are we preventing an unsafe action, or merely hiding/defering an unhealthy state?

A fail-closed gate must protect a named safety invariant. Imperfect or temporarily unavailable data is not, by itself, sufficient justification for changing lifecycle ownership.

## Degraded does not mean absent

For reporting and dashboards, a managed/supported entity should normally remain visible when temporarily degraded.

Prefer:

```text
VET
scope = SUPPORTED
source_health = MISSING_CANDLES
signal/actionability = unavailable
reporting = visible with attributable warning
```

over silently removing the entity from the reporting surface.

Reporting remains read-only: it displays canonical degraded state and reason codes; it must not infer, repair, or mutate them.

## Prefer composition over state explosion

Before inventing a new state such as `APPROVED_PENDING_SOURCE_DATA`, first test whether the required meaning is already represented by orthogonal fields, for example:

```text
approval = ACCEPTED
readiness = SUPPORTING_SOURCE_STALE
production_promotable = false
```

If existing fields are sufficient, improve reporting/joining rather than adding a duplicate state machine.

## Promotion and readiness

Do not assume that temporary market-data health must either allow or block a structural lifecycle transition such as `PROMOTE_SCOPE`.

First derive the canonical semantics of the lifecycle state itself:

- If `SUPPORTED` means lifecycle/management ownership, temporary stale data may be a valid degraded state after promotion.
- If `SUPPORTED` explicitly guarantees current actionable data, freshness may be a required precondition.

The contract decides. Do not infer the answer from a local failure condition.

## Architecture placement

When a condition must block an action, place the rule at the layer that owns that action or permission.

When a condition only describes runtime/data health, keep it in the canonical market/runtime health projection and let downstream consumers degrade safely.

Do not push health-state logic into account-aware layers, execution planning, executors, or reporting merely to make a local workflow pass.

## Review checklist

For any diff that changes a gate, blocker, lifecycle state, eligibility rule, or degraded behavior, reviewers must ask:

1. What is the desired end-user/downstream result?
2. Which state dimension owns this condition?
3. Is this structural lifecycle state or temporary health state?
4. Could existing fields already express it?
5. What named safety invariant does any new fail-closed gate protect?
6. Would the change make a degraded entity disappear when it should remain visible with a warning?
7. Does the change create unnecessary coupling between lifecycle ownership and transient data health?
8. What breaks later if this responsibility is placed here?

If these questions are not answered, stop before implementation and resolve the state semantics first.
