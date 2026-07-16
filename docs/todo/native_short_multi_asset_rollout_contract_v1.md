# TODO — Native SHORT Multi-Asset Rollout Contract

## Status

`blocked` — PR 2a supplies the read-only readiness audit and canonical contract only. BTC remains the sole approved and proven canonical scope. No additional scope is authorized by this document.

## Sources

- merged and live-accepted PR #105;
- `src/market_data/native_short_multi_asset_audit_v1.py`;
- `src/market_data/run_native_short_multi_asset_audit_v1.py`;
- canonical native SHORT scope, map, lifecycle, generation, cadence, status, health-report, materializer, and 4h-owner implementation on `origin/main`;
- read-only production evidence captured on 2026-07-16.

## Current state / facts

Canonical identity is exactly:

```text
(bitvavo, <SYMBOL>, EUR, SHORT, 4h, 1h)
```

BTC proved only that this exact BTC key can run through the existing single-scope 4h-owned chain, retain a complete generation/lifecycle ledger, project one active current map, rerun idempotently, and remain market-only and account-agnostic. It did not prove multi-scope transactions, per-symbol failure isolation, bootstrap behavior for a scope with no current map, attributable writer provenance, general promotion/removal, broader tick coverage, or any non-BTC production scope.

Read-only measured snapshot:

- 430 Bitvavo EUR markets audited;
- 23 readiness-qualified markets including BTC;
- 407 markets excluded from readiness at the snapshot cutoff;
- 403 market-eligible markets lacked both database and approved static tick-rule coverage (406 of all 430 rows when the three fail-closed ineligible markets are retained in the raw missing-tick count);
- SOL, ETH, and XRP were the three highest-ranked qualified future candidates by trailing-30-day public 4h EUR quote volume;
- safe capacity is currently one scope per failure domain.

The proposed queue is therefore sequential, not a simultaneous cohort:

```text
SOL -> ETH -> XRP
```

This queue is a review order only. SOL, ETH, and XRP are not approved for production. Ranking occurs only after public-market eligibility, exact 4h/1h freshness, context availability, unambiguous tick metadata, and empty/unambiguous native SHORT ledger checks pass. Wallets, balances, orders, portfolio membership, Profit Plan state, account state, and `selection_engine` output are prohibited inputs.

The successful BTC-only writer run `b5d9ca6b-ff24-46eb-8155-4e663b948ebc` at `2026-07-15 22:15:46Z` has `host_name=NULL` and is not attributable enough for expansion approval. Provenance remediation is a separate PR and must not be hidden inside cohort work.

## Deterministic audit contract

For every symbol, the audit reports three independent layers:

1. market readiness: canonical metadata flags, 4h and 1h counts/latest closed candle/freshness, context availability, tick state, and trailing-30-day 4h quote volume;
2. ledger readiness: exact-key scope cardinality/state, map/current-map state, lifecycle evidence, and generation-chain validity;
3. global rollout readiness: provenance, promotion, removal, bootstrap, capacity, and failure-isolation blockers.

Output is ordered by symbol. Volume is a ranking field only for rows already classified `READY_FOR_SEQUENTIAL_CANARY_REVIEW`. While any global blocker remains, `production_promotable` must be false.

## Promotion acceptance contract

A later single-symbol promotion may be accepted only when all of the following are evidenced:

- exact canonical identity and no alternate/partial scope key;
- an attributable writer owner, host, process, trigger type, and trigger reference;
- an explicit all-or-nothing single-scope promotion transaction;
- idempotent reruns with exactly one active map candidate;
- one `ATTEMPT_STARTED` plus exactly one terminal generation event per attempt, with every publication linked to its immutable map;
- source freshness `CURRENT` against the expected closed 4h and 1h cadence;
- no ambiguous scope, map, current-status, lifecycle, generation, or tick state;
- bounded completion within the existing 4h owner budget;
- a failure confined to the selected symbol, with deterministic retry and no partial evidence from another symbol;
- three consecutive real 4h cycles after promotion;
- the existing 4h owner remains the only timer/runtime owner.

The required later promotion transaction must lock and validate the exact key, establish the supported scope, append its support evidence, and activate its cadence atomically. It must not materialize a map inside that transaction. A retry must either observe the identical completed state or fail closed on conflict; it must never add a duplicate logical scope.

The required later removal/rollback transaction must lock the same exact key, withdraw support, deactivate cadence, and make the scope non-actionable atomically. It must retain immutable maps and append-only generation/lifecycle/observation/run history, must not mislabel removal as a market lifecycle outcome, and must leave the sole 4h owner able to continue without selecting the removed scope. Until schema and projection behavior can meet those exact semantics without partial state, removal remains blocked.

## Open tasks by priority

The required PR order is fixed:

1. **A — read-only audit merged.** Merge this audit and contract with no runtime mutation.
2. **B — writer provenance attribution.** Make writer evidence attributable and re-audit it.
3. **C — explicit single-scope promotion/removal contract.** Implement and test the transactions described above separately.
4. **D — bootstrap orchestration correction.** Ensure `NO_CURRENT_MAP` is expected bootstrap state for a newly supported scope rather than a fatal orchestration error.
5. **E — SOL canary.** Promote only SOL, then accept three consecutive real 4h cycles.
6. **F — ETH canary.** Consider ETH only after SOL acceptance and removal readiness remain valid.
7. **G — XRP canary.** Consider XRP only after ETH acceptance.
8. **H — broader expansion.** Revisit only after measured capacity and tick-rule coverage improve.

## Blockers / dependencies

- `WRITER_PROVENANCE_UNATTRIBUTED`;
- `PROMOTION_CONTRACT_MISSING`;
- `REMOVAL_CONTRACT_MISSING`;
- `BOOTSTRAP_ORCHESTRATION_BLOCKED`: current `NO_CURRENT_MAP` semantics are fatal for a new scope;
- `MULTI_SCOPE_FAILURE_ISOLATION_MISSING`: current orchestration does not isolate failures by symbol;
- one-scope current failure-domain-safe capacity;
- 403 markets without database/static tick-rule coverage.

## Boundary

Owner: `market_data`, using public canonical market metadata, public candles, tick metadata, and native SHORT ledgers only.

No live trading. No database mutation. No scope seeding. No materialization or lifecycle action. No account/private-broker reads. No broker writes. No order submission. No `selection_engine`, `decision_gate`, `execution_planner`, or executor input. No second timer or runtime owner.

## Non-goals

- provenance remediation;
- promotion or removal writes;
- bootstrap/materializer/orchestrator changes;
- multi-scope execution;
- runtime deployment or service/timer changes;
- Profit Plan changes;
- production approval of SOL, ETH, XRP, or any other new scope.
