# Profit Plan UX backlog audit v1

## Status

Issue #502 audit result against current `main`.

This is backlog reconciliation only. It does not change market truth, account permission, execution intent, order handling, runtime, deployment, or database state.

Canonical invariant:

```text
operator_dashboard = freshest trustworthy evidence that can be truthfully presented
execution_permission = only execution-authoritative evidence
```

Reporting may expose trustworthy read-only evidence with explicit provenance/freshness even when `decision_gate` must fail closed. Reporting must not fabricate market truth or weaken execution authority.

## Classification matrix

### Issue #233 — coin-card scanability

| acceptance_item | classification | evidence_file_or_pr | remaining_gap |
|---|---|---|---|
| Compact `MAP | ACTIONABLE PPP` presentation | SUPERSEDED | PR #348 / #347 Profit Plan card-domain separation | Later accepted domain-separated card semantics replaced the older compact combined-field design. Do not rebuild the historical combined field. |
| Tooltip registry for accepted fields | STILL_NEEDED | Current renderer; no canonical tooltip-registry implementation found in current backlog evidence | If tooltips remain desirable, implement only for the current card vocabulary, not the superseded #233 layout. |
| Duplicate Current-price tile removal | DONE | Current Profit Plan card restructuring from PR #348 / #347 | No separate legacy duplicate-price implementation should be reintroduced. |
| Variable-field alignment across cards | STILL_NEEDED | Current renderer/layout remains the owner | Preserve current domain separation and make optional/variable rows scan consistently. |
| Reporting tests for accepted design states | STILL_NEEDED | Follows surviving current-layout work only | Tests should cover the bounded current-state layout, not superseded #233 semantics. |
| No upstream/trading-layer mutation | DONE | Reporting-only architecture boundary | No gap. |

Disposition: close #233 after transferring the two surviving current-layout items into one bounded current-state reporting issue.

### Issue #240 — cockpit/wallet cleanup

The original Scope B source was a local-only, untracked file. The repository migration manifest records #240 as presentation-only ownership but does not preserve a canonical enumerated Scope B list in shared history (`docs/development/github_issues_batch_2c_migration_v1.md`).

| acceptance_item | classification | evidence_file_or_pr | remaining_gap |
|---|---|---|---|
| Enumerate every Scope B item before implementation | OBSOLETE | `docs/development/github_issues_batch_2c_migration_v1.md` | The historical source is not repository-canonical and the generic bucket is no longer a safe implementation contract. |
| Only defined cockpit/wallet presentation items change | SUPERSEDED | Later Profit Plan/cockpit restructuring, including PR #348 / #347 | Any surviving UX defect must be expressed as a concrete current-state item, not recovered as a generic legacy bundle. |
| Preserve provenance/freshness semantics | DONE | Current reporting architecture | This remains an invariant, not outstanding standalone work. |
| No upstream/trading-layer mutation | DONE | Reporting-only architecture boundary | No gap. |
| Reporting/UI tests cover accepted states | SUPERSEDED | Historical states are not canonical | Tests belong with concrete current-state work only. |

Disposition: close #240. Do not resurrect the local-only historical Scope B as an implementation contract.

### Issue #267 — display row key and freshness presentation

| acceptance_item | classification | evidence_file_or_pr | remaining_gap |
|---|---|---|---|
| Stable display row key across re-renders | OBSOLETE | Manual ladder/request roadmap ownership was retired/restructured; current operator surface must not couple display identity to request/execution identity | No new stable execution-adjacent identity should be introduced in reporting solely for the old manual-ladder surface. |
| Seven freshness observation classes under one policy | STILL_NEEDED | Current reporting has explicit freshness/provenance in several domains but not one complete operator-facing observation set | Preserve only useful read-only freshness facts for current surfaces. Do not rebuild the retired ladder-repair model. |
| Stale/missing account authority suppresses account-specific claims | DONE | Current fail-closed account/permission semantics and reporting provenance | Keep this invariant. |
| Focused reporting tests for key/freshness classification | SUPERSEDED | Row-key portion obsolete; freshness tests belong with surviving current-state presentation work | Test only surviving freshness behavior. |
| No operator-intent/request/plan/executor state access | DONE | Architecture boundary | No gap. |

Disposition: close #267 after transferring the surviving freshness-presentation gap into the bounded current-state reporting issue.

### Issue #313 — Opportunity Rank, actionable counts, empty states

| acceptance_item | classification | evidence_file_or_pr | remaining_gap |
|---|---|---|---|
| Consume canonical persisted/neutral read-model fields only | DONE | PR #491 / #457 Planning PPP provenance and fail-closed actionability semantics | Remains an invariant. |
| Default ordering actionable first, then non-actionable, deterministic tie-break | DONE | PR #421 / #364 global Actionable PPP sorting; closed #256 sorting fix | No gap. |
| `Opportunity Rank` secondary research sort | SUPERSEDED | No validated canonical upstream Opportunity Rank evidence exists in the accepted current architecture | Do not invent ranking semantics in reporting. Reopen only through separate upstream research/validation if ever justified. |
| Actionable-candidate count | STILL_NEEDED | Current operator presentation does not have a canonical bounded count requirement recorded elsewhere | Add a read-only count derived from the same canonical actionability field already consumed by reporting. |
| Explicit zero-actionable state | STILL_NEEDED | Current-state UX gap | Render explicit zero state rather than an apparently empty/failed dashboard. |
| Explicit stale/unavailable state | STILL_NEEDED | Current-state UX gap; coordinate with surviving #267 freshness work | Distinguish zero actionable from stale/unavailable inputs. |

Disposition: close #313 after transferring the three surviving presentation items into the bounded current-state reporting issue.

## Consolidated surviving reporting scope

Create one bounded current-state implementation issue owning only:

1. Current Profit Plan card scanability on the existing domain-separated renderer:
   - accepted/current tooltips where useful;
   - stable alignment of variable/optional fields.
2. Operator-state presentation:
   - actionable-candidate count;
   - explicit zero-actionable state;
   - explicit stale/unavailable state;
   - useful read-only freshness facts with explicit provenance.
3. Focused reporting tests for those states.

Do not include:

- #500 Rotation Pressure y-axis UX;
- #354 expandable Fibonacci map chart;
- any Opportunity Rank calculation;
- market ranking authority;
- account permission;
- execution intent;
- order handling;
- broker access.

## Upstream/data-owner gaps discovered

The audit constraint around AAVE remains an upstream-contract tracing problem, not a reporting fallback request:

- a fresh open-order snapshot can coexist with `ACCOUNT_ORDER_DATA_UNAVAILABLE` if a required account-order aggregate/projection field is absent;
- an available/current native map can coexist with `TIER_METADATA_UNAVAILABLE` when selected-map tier metadata is not canonically available;
- reporting-derived reference levels are not a substitute for canonical entry/re-entry levels required by execution authority.

Those gaps must stay with their true account/order or canonical-map/entry-level owners. Reporting may expose trustworthy current evidence with provenance, but must not synthesize execution-authoritative substitutes.

## Recommended normalization

After this audit is merged:

- close #233 as superseded/partially consolidated;
- close #240 as obsolete/superseded generic legacy scope;
- close #267 as obsolete except for freshness work transferred to the consolidated issue;
- close #313 after transferring actionable-count/zero/stale presentation to the consolidated issue;
- create one bounded current-state reporting issue for the surviving items above;
- close #502 once those normalization actions are recorded.

No generic legacy cleanup bucket should remain open after consolidation.

## Safety

```text
selection_engine_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_writes=0
order_submission=0
live_activation=0
runtime_mutation=0
database_mutation=0
```
