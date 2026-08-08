# BOOTSTRAP_ORCHESTRATION_BLOCKED — current state and exact remaining proof

Status: **ACTIVE** (fail-closed)
Reason code: `EXACT_PROOF_REQUIRED`
Owning issue: #276
Supersedes reason: `IMPLEMENTATION_PENDING_SEPARATE_LANE` (no longer accurate)

## Summary

`BOOTSTRAP_ORCHESTRATION_BLOCKED` remains an active global blocker in
`src/market_data/native_short_multi_asset_audit_v1.evaluate_global_blockers()`.

Issue #276 made its sibling blocker
`MULTI_SCOPE_FAILURE_ISOLATION_MISSING` evidence-driven (see
`src/market_data/native_short_runtime_isolation_evidence_v1.py`) because #200
supplied the substantive guarantee it was waiting for. This blocker got no
such treatment, deliberately: no current evidence closes it.

Its previous reason code, `IMPLEMENTATION_PENDING_SEPARATE_LANE`, is now
inaccurate — the "separate lane" it referred to (the generalized bootstrap
manifest and the rollout orchestrator) has landed. What remains is not
missing implementation but one exact, named, unproven runtime property. The
reason code is therefore `EXACT_PROOF_REQUIRED`.

This blocker takes no evidence parameter in `evaluate_global_blockers()`.
Adding an optional parameter with no evaluator behind it would make a
fail-closed default look negotiable; when a canonical evidence source exists,
it can be wired in the same shape the isolation blocker now uses.

## Why it stays active: the NO_CURRENT_MAP / stop-on-BLOCKED interaction

`docs/todo/native_short_multi_asset_rollout_contract_v1.md` records this
blocker's meaning as "current `NO_CURRENT_MAP` semantics are fatal for a new
scope." That is still true after #200. Exact trace, verified against this
checkout:

1. `src/market_data/native_short_map_level_status_materializer_v1.py`,
   `select_gate_decision()` — the first branch returns
   `(BLOCKED, NO_CURRENT_MAP)` whenever a scope's rebuilt projection has no
   `current_map_id` (or no `current_map_cycle_id`). A genuinely brand-new
   scope that has never published its first map is exactly this case.

2. That `BLOCKED` branch raises `NativeShortMapLevelStatusBlockedError`.

3. `src/market_data/run_native_short_scope_status_chain_v1.py`,
   `execute_runtime()` — the per-scope loop catches
   `NativeShortMapLevelStatusBlockedError`, rolls back **only** that scope's
   transaction, records `SCOPE_STATUS_BLOCKED`, and then **`break`s** out of
   the loop. The in-code comment states the policy explicitly: "Blocked stays
   a hard stop for the run: no further scope is attempted." Contrast the
   sibling `except Exception` branch immediately below it, which records
   `SCOPE_STATUS_UNEXPECTED_FAILED` and `continue`s.

Consequence: immediately after any `PROMOTE_SCOPE` — precisely the situation
a bulk rollout creates — the newly promoted scope has no current map yet, so
every 4h chain run halts at that scope and never evaluates any
already-established scope ordered after it. This persists on every run until
the new scope publishes its first map.

## What #200 did and did not fix

#200 restructured *transaction and rollback* boundaries so each scope owns
its own failure domain: a failure in scope N can no longer roll back
committed work from scopes 1..N-1. That is real and is what the isolation
evidence now verifies.

#200 did **not** change the loop-halting policy for the domain-`BLOCKED`
case, which it deliberately preserved. Transaction isolation and
loop-continuation are independent properties; the first is proven, the second
is not, for this specific case.

## Exact remaining proof required to close this blocker

A separate, explicitly reviewed decision on how the runtime chain should
treat a brand-new scope's expected, transient `NO_CURRENT_MAP` state. Neither
option below is implemented here — Issue #276 explicitly does not touch the
runtime chain files — and both are named only as the open alternatives for
that future decision:

- **Option A — reclassify transient `NO_CURRENT_MAP` as a soft degrade.**
  Distinguish "brand-new scope, no first map yet" (expected, self-resolving)
  from a genuine integrity `BLOCKED` (unexpected, must halt), and let the
  former record a non-fatal per-scope status and `continue`. Requires proving
  the two cases are reliably distinguishable and that nothing downstream
  depends on a partially-evaluated run halting.

- **Option B — an explicit bounded warm-up window.** Exclude a newly promoted
  scope from the shared chain run until it has published its first map (or
  until a bounded deadline), so it cannot halt established scopes. Requires a
  reviewed definition of the window, its expiry behavior, and what happens if
  the scope never warms up.

Closing this blocker additionally requires a canonical, machine-readable
evidence source for whichever option is chosen — narrative acceptance in a
document is explicitly not evidence under this repository's contract — plus
its own tests, in the shape
`native_short_runtime_isolation_evidence_v1.py` now establishes.

## Cross-references

- Issue #276 — native SHORT evidence-driven rollout
- Issue #200 / PR #274 — per-scope transaction isolation
  (commit `4c4d3c0e8a54250ae957364adb7af4858fe8170e`)
- `src/market_data/native_short_runtime_isolation_evidence_v1.py`
- `docs/todo/native_short_multi_asset_rollout_contract_v1.md` (frozen
  historical context; not edited by #276)

Safety markers for the work that produced this document:

```text
production_db_mutation=0
runtime_activation=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```
