# BOOTSTRAP_ORCHESTRATION_BLOCKED — evidence contract and accepted state

Status: **EVIDENCE-DRIVEN** — closes while the machine-readable contract confirms
Reason code when confirmed: `EVIDENCE_CONFIRMS_CLOSED`
Reason code when absent/invalid: `EVIDENCE_ABSENT_OR_INVALID`
Reason code for a caller that supplies no evidence: `EXACT_PROOF_REQUIRED` (fail-closed default)
Owning issues: #276 (previous active state), #298 (resolution)
Evidence module: `src/market_data/native_short_bootstrap_no_current_map_evidence_v1.py`

## Summary

`BOOTSTRAP_ORCHESTRATION_BLOCKED` is no longer unconditionally active in
`src/market_data/native_short_multi_asset_audit_v1.evaluate_global_blockers()`.
Issue #298 supplied the substantive guarantee it was waiting for, and the
blocker is now wired to a canonical, machine-readable evidence source in the
same shape `MULTI_SCOPE_FAILURE_ISOLATION_MISSING` uses (#276).

It closes only while that evidence confirms, and re-opens by itself the
instant the guarantee regresses. The pure `evaluate_global_blockers()`
default — a caller that supplies no bootstrap evidence at all — still keeps
the blocker active with `EXACT_PROOF_REQUIRED`.

## The defect that is now fixed

Previously, `select_gate_decision()` in
`src/market_data/native_short_map_level_status_materializer_v1.py` returned
`(BLOCKED, NO_CURRENT_MAP)` whenever a scope's rebuilt projection had no
`current_map_id`/`current_map_cycle_id`. A genuinely brand-new scope that had
never published its first map was exactly this case. That `BLOCKED` raised
`NativeShortMapLevelStatusBlockedError`, and `execute_runtime()`'s per-scope
loop in `src/market_data/run_native_short_scope_status_chain_v1.py` treated
`BLOCKED` as a hard stop: it rolled back that scope and `break`ed out of the
loop.

Consequence: immediately after any `PROMOTE_SCOPE` — precisely the situation
a bulk rollout creates — every 4h chain run halted at the newly promoted
scope and never evaluated any already-established scope ordered after it,
until that scope published its first map.

#200 fixed *transaction and rollback* isolation, so a failing scope could no
longer roll back other scopes' committed work. It deliberately did not change
the loop-halting policy. Transaction isolation and loop continuation are
independent properties; #298 addressed the second one, for this case only.

## The exact predicate (ledger-only, not timing)

`NO_CURRENT_MAP` arises from two genuinely different ledger situations, and
only one of them is an integrity defect:

```text
(a) zero native_short_map_v1 rows have EVER existed for the exact canonical
    scope key
    -> the expected, transient first-map bootstrap state of a scope that has
       never published any map
    -> branch EXPECTED_BOOTSTRAP_NO_CURRENT_MAP  (exempt, non-fatal)

(b) map rows exist for the exact scope key but none is currently selected
    (for example an established scope whose maps are all SUPERSEDED with no
    successor published yet)
    -> an UNEXPECTEDLY missing current map on an established scope; possibly
       a stuck or broken rollover
    -> branch BLOCKED                             (unchanged hard stop)
```

The distinguishing predicate is pure ledger existence:

```text
never_published_any_map = not existing_maps
```

where `existing_maps` is the exact-scope-key map list
(`native_short_map_materializer_v1._fetch_maps_for_scope`) that
`evaluate_and_project_scope()` already fetches before the projection rebuild.
It is independent of `as_of_utc`, independent of lifecycle state, and adds no
query.

It is deliberately **not** a timing, ordering, or grace-window inference. In
particular it is not `SCOPE_RECENTLY_ADDED` (the first-SUPPORTED-timestamp
grace window in `native_short_scope_status_projection_v1.py`), which is
exactly the kind of heuristic Issue #298 forbids for this classification.

## Runtime behavior of an exempted scope

* Its transaction boundary remains `exact_scope` and fully attributable; it
  **commits** normally rather than being rolled back.
* It emits zero level rows and atomically clears any stale level collection,
  exactly as `BLOCKED` does — the contract's "no dynamic level state
  fabricated" invariant holds identically for this branch
  (`docs/architecture/native_short_map_level_status_contract_v1.md`).
* `ScopeChainOutcome.bootstrap_pending` is `True`, independently of `failed`,
  which keeps reflecting only `evaluate_scope`'s own soft-degrade contract.
  An expected bootstrap state is not a failure and does not increment
  `failed_scope_count`, so it does not trip `RuntimeScopeEvaluationError`.
* Its per-scope evidence is `SCOPE_STATUS_BOOTSTRAP_PENDING`
  (`"BOOTSTRAP_PENDING"`), a status distinct from `SUCCEEDED`: the bootstrap
  state stays visible and is never misreported as normal success.
* The loop **continues** to the next scope. Unrelated, already-established
  scopes ordered after it are still evaluated in the same bounded invocation,
  and the run terminalizes `FINISHED` when the bootstrap case was the only
  anomaly.
* Rerunning is deterministic and idempotent: an unchanged still-bootstrapping
  scope produces identical evidence and exactly one terminal record per
  invocation.

Issue #543 classifies the proven source-readiness tuple
`SOURCE_UNAVAILABLE` or `SOURCE_STALE` + `BLOCKED_SOURCE` as
`SCOPE_STATUS_SKIPPED_NOT_READY`: the scope projection and empty level
collection commit fail-closed, the loop continues, and the run remains
`FINISHED` when no other failure occurs. All other `BLOCKED` states — case (b)
above and `PROJECTION_MISSING`, `PROJECTION_INVALID`, `GEOMETRY_INVALID`,
`CONFIGURATION_UNAVAILABLE`, `OBSERVATION_OVERDUE`, and any inconsistent
combination — retain their hard-stop, fail-closed behavior.

## What counts as evidence

`evaluate_bootstrap_no_current_map_evidence()` requires both, with no DB
access (repository and import inspection only):

1. **Ancestry** — the #200 per-scope isolation commit
   `4c4d3c0e8a54250ae957364adb7af4858fe8170e` is an ancestor of `HEAD`. This
   guarantee is only meaningful on top of per-scope transaction isolation:
   continuing to the next scope is worth nothing if that scope's writes share
   a rollback domain with the bootstrap scope's.

2. **Structural contract of the live modules** — inspected by import, not by
   narrative claim or test existence:
   * `native_short_map_level_status_materializer_v1.EXPECTED_BOOTSTRAP_NO_CURRENT_MAP
     == "EXPECTED_BOOTSTRAP_NO_CURRENT_MAP"`
   * `select_gate_decision` is callable and its signature carries the
     `never_published_any_map` ledger predicate
   * `native_short_scope_status_materializer_v1.ScopeChainOutcome` is a
     dataclass with a `bootstrap_pending` field
   * `run_native_short_scope_status_chain_v1.SCOPE_STATUS_BOOTSTRAP_PENDING
     == "BOOTSTRAP_PENDING"`

The #298 implementation commit itself is deliberately **not** pinned: it has
no stable SHA at authoring time, and check 2 inspects the live code directly,
which is strictly stronger evidence that the fix is present.

## Regression reactivates the blocker fail-closed

Removing or renaming any element of the structural contract — most pointedly
dropping the `never_published_any_map` parameter, which would collapse the
bootstrap case back into a genuine `BLOCKED` hard stop — makes the evidence
evaluate `confirmed=False` and the blocker active again, with no human
remembering required. So does reverting #200 out of the ancestry, an
unavailable git/ancestry check, an import failure, a wrong attribute value,
or a wrong dataclass field set. An unavailable check is never treated as a
passed check.

## Cross-references

- Issue #298 — bootstrap classification, this document's resolution
- Issue #276 / PR #287 — evidence-driven rollout, previous active state
- Issue #200 / PR #274 — per-scope transaction isolation
  (commit `4c4d3c0e8a54250ae957364adb7af4858fe8170e`)
- `src/market_data/native_short_bootstrap_no_current_map_evidence_v1.py`
- `src/market_data/native_short_runtime_isolation_evidence_v1.py`
- `docs/architecture/native_short_map_level_status_contract_v1.md`
- `docs/todo/native_short_multi_asset_rollout_contract_v1.md` (frozen
  historical context; not edited)

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
