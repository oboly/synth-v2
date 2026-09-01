# Wallet-triggered opportunity execution v1

Status: proposed canonical architecture for Issue #557 / Synth V1 Lane C
Scope: market opportunity -> account permission/allocation -> immutable execution intent -> shared executor/reconciliation -> exit coverage -> released-capital reevaluation
Runtime impact: none. This document is audit/design only.

## 1. Decision summary

Synth V1 should close the loop by reusing the execution lane that already exists instead of creating new named agents or a parallel opportunity/order stack.

Canonical V1 flow:

```text
market-only producer / selection
-> current actionable BUY candidate
-> decision_gate account permission + allocation ceiling
-> execution_planner immutable BUY ladder
-> shared execution handoff / reconciliation
-> BUY fill / position truth
-> canonical automatic-exit policy/profile resolution
-> immutable SELL plan
-> shared execution handoff / reconciliation
-> SELL fill
-> refreshed COMPLETE account-state bundle
-> next decision_gate evaluation of current market opportunities
```

The account-state change is the reason a new investment evaluation becomes useful; it is not a reason to wake or mutate market ranking. Market ranking remains account-agnostic.

The following architectural decisions are explicit:

1. **Do not create `Asset Analyst` or `Investment Agent` as new authority-bearing runtimes.** Market producers plus `selection_engine`/market read models already own those responsibilities.
2. **Do not create a new `asset_opportunity` table for V1.** Reuse existing market proposal/candidate contracts and preserve provenance. A generalized persisted opportunity entity is justified only when multiple validated producers require one shared durable lifecycle owner.
3. **Keep `execution_planner` in the automatic BUY lane.** It performs real deterministic transformation after permission: notional ceiling -> rounded base quantity -> venue-valid multi-leg immutable ladder. This is not permission logic and is not executor order handling.
4. **Keep `decision_gate` as the sole account-aware permission/allocation owner.** No account facts enter market ranking/candidate production.
5. **Use the existing COMPLETE account-state bundle as canonical wallet/account truth.** Do not create a wallet agent or second balance/reservation truth.
6. **Reuse the shared side-neutral executor/handoff/reconciliation substrate.** No BUY-specific or SELL-specific broker stack.
7. **Do not authorize automatic BUY LIVE before safe automatic exit coverage exists.** The current missing `automatic_exit_profile_v1` producer is a closed-loop blocker; #657 owns its design/promotion path.

## 2. Current-state audit

Audit baseline: main `2744efd437b204933715bbe21a6875e4a4c048b8`.

### 2.1 Market proposal and BUY candidate

`docs/architecture/strategy_proposal_contract_v1.md` already defines the permanent market-only proposal boundary:

```text
market evidence
-> strategy proposal
-> decision_gate
-> execution_planner
-> executor
```

It already requires account-agnostic proposal truth, expiry/freshness, provenance, horizon separation, entry/target/invalidation levels and proposal lifecycle.

The automatic BUY lane has a narrower execution adapter in:

```text
src/entry_policy/automatic_buy_candidate_v1.py
```

This is sufficient for the current bounded V1 automatic-entry producer. It is not a replacement for the generic Strategy Proposal Contract and must not become a second market-ranking authority.

Known gap retained from #557: current automatic BUY candidate logic can recognize an already-actionable entry/re-entry zone, but it does not itself own a full fall-through -> invalidated -> recovery/reclaim -> BUY_WINDOW state machine. That transition remains market-policy/producer-owned upstream of `decision_gate`.

### 2.2 Account and deployable-capital truth

Canonical automatic-BUY account evidence is already assembled by:

```text
src/decision_gate/automatic_buy_account_allocation_evidence_contract_v1.py
src/decision_gate/automatic_buy_account_allocation_evidence_repository_v1.py
docs/architecture/automatic_buy_account_allocation_evidence_v1.md
```

The projection reads canonical sources rather than caller-supplied account facts:

```text
trading_account
COMPLETE trading_account_balance_snapshot
COMPLETE account_open_order_snapshot
COMPLETE account_position_snapshot
fresh market_price_snapshot
strategy_bucket_account_config_v1
automatic_buy_account_permission_v1
account protection evidence
```

For V1, deployable BUY capacity is not a second wallet balance. It is the fail-closed `decision_gate` result after composing fresh free quote balance, existing exposure/open-order conflict, bucket/account limits, protection state and the proposed position ceiling.

The gate's final authority remains:

```text
approved_notional_ceiling_eur
```

The existing implementation is deliberately conservative where bucket attribution is unavailable: bucket amount/open-position evidence can be account-wide and therefore over-restrictive. Do not create a speculative per-bucket position ledger merely to make V1 less conservative.

### 2.3 Automatic BUY repository phases

Issue #399 repository Phases 1-6 are already present:

```text
Phase 1  automatic BUY candidate
Phase 2  decision_gate permission/allocation
Phase 3  execution_planner BUY ladder
Phase 4  deterministic runtime + append-only persistence
Phase 5  DRY_RUN/PAPER acceptance preview
Phase 6  shared side-neutral executor handoff integration
```

Key files include:

```text
src/decision_gate/automatic_buy_gate_v1.py
src/execution_planner/automatic_buy_planner_v1.py
src/entry_policy/automatic_buy_runtime_orchestrator_v1.py
src/entry_policy/run_automatic_buy_dry_run_acceptance_v1.py
```

PR #447 proves Phase 6 adapts `AutomaticBuyPlanV1` to the existing shared `ApprovedExecutionPlanV1` / `ExecutionHandoffRepositoryV1` substrate rather than inventing a BUY executor.

Phase 7 is intentionally separate LIVE authorization and must remain so.

### 2.4 Why the BUY planner remains

The #557 audit explicitly re-opened whether `execution_planner` could be removed for BUY. Current code answers that question: **retain it**.

After `decision_gate` approves a notional ceiling, `automatic_buy_planner_v1` still owns non-trivial deterministic transformation:

```text
approved EUR notional ceiling
-> reference-price conversion to base quantity
-> side-aware quantity/price rounding
-> venue capability + min-quantity + min-notional checks
-> deterministic multi-leg distribution
-> immutable BUY plan
```

Moving this into `decision_gate` would mix permission/allocation with execution construction. Moving it into the executor would give the order-handling layer execution-policy authority. Neither is acceptable.

### 2.5 Shared executor / reconciliation

Issue #206 and #399 Phase 6 provide the shared BUY/SELL handoff and order-handling substrate. The closed-loop architecture therefore reuses:

```text
ApprovedExecutionPlanV1
ExecutionHandoffRepositoryV1
shared per-leg persistence/state
client-order idempotency
shared venue adapter
shared reconciliation
```

Do not add `current_limit_sell_orders`, a BUY executor, a SELL executor, or another broker-order truth table.

### 2.6 Automatic exit coverage

Automatic exit runtime/profile resolution exists and correctly fails closed when no unique valid `automatic_exit_profile_v1` exists.

Issue #657 owns the missing evidence-backed profile producer/promotion architecture. Its current dependency split is canonical:

```text
Phase A design contract: may proceed now
Phase B producer/promotion: requires validated upstream evidence, currently #270 unless superseded by another reviewed canonical source
```

For V1, breadth is not required. One bounded deterministic strategy/horizon/profile family is sufficient to prove closed-loop exit coverage, but fabricated generic targets are forbidden.

## 3. Target component ownership

| Target concept | Classification | Canonical V1 owner |
| --- | --- | --- |
| Asset Analyst | RENAME_ONLY / logical role | existing market producers + proposal/candidate adapters |
| Investment Agent | RENAME_ONLY / logical role | `selection_engine` / market-only ranking read model |
| Generic Strategy Proposal | REUSE_AS_IS | `strategy_proposal_contract_v1` |
| V1 actionable automatic BUY candidate | REUSE_AS_IS | `automatic_buy_candidate_v1` |
| Generic persisted `asset_opportunity` entity | NOT_REQUIRED_FOR_V1 | defer until multiple producers require shared persistence/lifecycle |
| Opportunity lifecycle | EXTEND_EXISTING upstream | strategy proposal/market producer; never `decision_gate` |
| Account/wallet truth | REUSE_AS_IS | COMPLETE account-state snapshot bundle |
| Account allocation evidence | REUSE_AS_IS | `automatic_buy_account_allocation_evidence_*` |
| Account permission/allocation | REUSE_AS_IS | `decision_gate` / `automatic_buy_gate_v1` |
| BUY execution construction | REUSE_AS_IS | `execution_planner/automatic_buy_planner_v1` |
| BUY runtime/audit/idempotency | REUSE_AS_IS | automatic BUY runtime Phase 4 |
| BUY DRY_RUN/PAPER seam | REUSE_AS_IS | #399 Phase 5 |
| BUY shared executor handoff | REUSE_AS_IS | #399 Phase 6 + #206 shared executor |
| Automatic exit profile resolution | REUSE_AS_IS | automatic exit runtime/resolver |
| Automatic exit profile producer | NEW_REQUIRED | #657, evidence-backed only |
| Shared order/fill/reconciliation truth | REUSE_AS_IS | shared executor/order persistence |
| Wallet-trigger event service | NOT_REQUIRED_FOR_V1 | deterministic cadence over canonical account state first |

## 4. Versioned contract decisions

No new runtime dataclass is required by this architecture PR. Existing typed contracts already cover the V1 chain.

Conceptual names from #557 map as follows:

```text
AssetOpportunityV1
  -> StrategyProposal contract generically
  -> AutomaticBuyCandidateV1 for current automatic BUY execution seam

RankedOpportunityV1
  -> selection_engine/read-model output; no account fields

AccountInvestmentStateV1
  -> AutomaticBuyAccountAllocationEvidenceV1 + canonical protection/config inputs

DecisionGateInvestmentDecisionV1
  -> AutomaticBuyGateDecisionV1

ApprovedBuyIntentV1
  -> AutomaticBuyPlanV1 after execution_planner transformation

ExitIntent/Ladder
  -> existing automatic-exit candidate/gate/planner chain, once #657 supplies a valid profile
```

Do not rename stable code merely to match these conceptual labels.

## 5. Trigger semantics

V1 should use a **deterministic cadence over canonical state** as the authoritative trigger mechanism.

Rationale:

- account snapshots and open-order/position truth already have canonical freshness semantics;
- runtime idempotency already prevents duplicate logical evaluation/handoff;
- a cadence is restart-safe and does not require a new event bus;
- fill/account-change events may later be used as low-latency hints without becoming a second source of truth.

Thus:

```text
sell fill / balance release
-> canonical reconciliation + next COMPLETE account snapshot
-> next automatic BUY evaluation cycle sees changed account evidence
-> decision_gate reevaluates the already-current market opportunity set
```

An event may trigger an earlier cycle later, but the event itself must not carry balance truth or investment permission.

## 6. Duplicate and race prevention

Use existing identities rather than introducing a new investment transaction id:

```text
market candidate/proposal identity
+ canonical account evidence identity/timestamps
+ policy/protection/config identities
-> automatic BUY runtime idempotency key
-> immutable BUY plan identity
-> deterministic shared executor plan_reference_id / handoff identity
-> deterministic per-leg client order identity
```

Repeated evaluation of the same snapshot must resolve to the same logical outcome/handoff. Simultaneous workers must respect the existing singleton/locking and persistence uniqueness contracts. Broker reconciliation remains the final order-state truth boundary.

## 7. Partial fills and exit coverage

A BUY plan is not evidence of a position. Confirmed fill/position truth is required before SELL quantity is constructed.

Closed-loop rule:

```text
confirmed filled quantity
-> canonical position/fill evidence
-> automatic exit profile resolution
-> exit gate/planner
-> SELL plan no greater than confirmed available quantity
-> shared executor/reconciliation
```

Partial fills therefore create coverage only for confirmed filled quantity; remaining open BUY quantity remains BUY-order state. Restart/reconciliation must recover both independently.

If no unique valid automatic exit profile resolves, the automatic exit lane must remain fail-closed. This is why #657 is a V1-critical dependency before automatic BUY LIVE activation.

## 8. Opportunity changes while a BUY is open

Market lifecycle and order lifecycle remain distinct.

- `INVALIDATED` / `STOP_CHASING` are market-side facts.
- An already-open broker BUY is executor/order state.
- Upstream policy may issue a reviewed cancel intent when an open BUY is no longer valid, but the executor must never infer cancellation from price/strategy itself.
- A better-ranked opportunity does not silently steal an existing reservation. Reallocation requires a new `decision_gate` decision after canonical order/account state reflects released capacity.

The exact reclaim/recovery trigger that restores `BUY_WINDOW` is not invented by this document.

## 9. Multi-horizon and multi-account

Separate horizons remain separate market opportunities/proposals and preserve their own strategy/setup/provenance identity. `selection_engine` may rank them without account knowledge.

Competition for one account's capital occurs only in `decision_gate`, using account policy/exposure constraints. The same market opportunity may produce independent decisions/plans for multiple accounts; account identity enters only downstream of the market candidate.

## 10. Provenance chain

Required deterministic lineage:

```text
proposal/candidate identity + evidence
-> AutomaticBuyGateDecisionV1
-> AutomaticBuyPlanV1
-> ApprovedExecutionPlanV1 / handoff plan_reference_id
-> broker BUY order leg(s)
-> fill / canonical position evidence
-> automatic exit profile + provenance
-> SELL decision/plan
-> shared executor handoff
-> broker SELL order leg(s)
-> fills / realized outcome
```

`source_opportunity_id` may be useful as a reporting reference later, but it must never replace account/plan/order/fill identities.

## 11. Schema delta

**No new schema is justified by #557 Phase A.**

Specifically, do not add:

```text
asset_opportunity
asset_opportunity_event
wallet_agent_state
current_limit_sell_orders
investment_agent_state
```

Current persisted runtime/audit/handoff/account-state structures are sufficient for the V1 loop. If later multi-producer opportunity persistence demonstrates a real lifecycle/query gap, that must be proposed as a separate minimal schema delta against the then-current contracts.

#657 may require its own profile-producer provenance/version/effective-time schema decisions; those belong to #657, not this document.

## 12. Failure-mode policy

| Failure mode | V1 behavior |
| --- | --- |
| stale/missing market candidate | fail closed / no BUY plan |
| stale/missing account snapshot | fail closed in account-evidence/gate path |
| insufficient free quote balance | deny/no plan |
| conflicting open BUY/reservation | deny according to current gate evidence/policy |
| duplicate evaluation | idempotent same logical audit/plan/handoff |
| simultaneous runtime workers | singleton/lock + persistence uniqueness |
| opportunity invalidated while BUY open | market layer records invalidation; cancellation requires explicit downstream intent, executor does not infer strategy |
| STOP_CHASING while BUY open | same separation as invalidation |
| partial BUY fill | exit only confirmed filled quantity |
| missing exit profile | fail closed; #657 blocker |
| conflicting exit profiles | fail closed exactly-one-match resolver semantics |
| missing SELL ladder after fill | reconciliation/exit runtime must detect uncovered position; never invent targets |
| target revision | only canonical profile/policy owner may supersede; executor never recalculates |
| broker/API outage | no invented success; preserve persisted intent/state for reconciliation |
| process restart | recover through persisted runtime/handoff/order state and deterministic identities |
| exchange tick/minimum rejection | planner/venue constraints fail before handoff where possible; executor preserves broker rejection truth |
| fee reserve | remain account/gate/venue-policy concern; do not hide inside market ranking |
| market suspension/delisting | fail closed at venue/order capability boundary |
| kill switch/pause | shared runtime/executor authority gate; never bypassed by opportunity logic |
| multiple accounts | independent account decisions from shared market truth |
| multiple horizons same asset | separate candidates; account competition resolved only by gate |

## 13. Issue reconciliation

### #399 automatic BUY

Keep open until its separately authorized LIVE phase and acceptance are genuinely complete.

Repository Phases 1-6 are reusable and consistent with this architecture. The planner is **not** superseded. Do not proceed to LIVE merely because Phase 6 exists: safe exit coverage and full DRY_RUN/PAPER closed-loop acceptance are prerequisites.

### #657 automatic exit profile promotion

V1 critical. Proceed with its design contract now. Phase B producer/promotion stays evidence-gated. A single bounded validated profile family is sufficient for V1; broad calibration can follow later.

### #270 exit/target research

Parallel upstream evidence lane. It must return an explicit research disposition and must not itself promote production policy.

### #665 retracement/reload

May attach later as another market-only producer after the core loop works. It must not add account-fill dependence to market ranking.

### #666 V1 finish line

This document implements the Lane C architecture decision requested by #666: reuse current contracts, keep boundaries strict, and stop expanding V1 with unnecessary new services/entities.

## 14. Dependency-ordered implementation sequence

1. Merge this #557 architecture contract after review.
2. Land #657 Phase A design contract with source/provenance/effective-time/exact-one semantics and read-only preview boundary.
3. Complete/consume accepted upstream target evidence (#270 or explicitly reviewed replacement).
4. Implement the smallest #657 bounded producer/promotion preview; still no production write until reviewed acceptance.
5. Exercise one exact DRY_RUN/PAPER closed loop: actionable market candidate -> gate -> BUY plan -> shared handoff/reconciliation simulation -> confirmed fill fixture/evidence -> exit profile -> SELL plan -> shared handoff/reconciliation -> released-capital reevaluation.
6. Only after the exact path is accepted, review the separately authorized #399 LIVE phase with bounded account/market/notional/order limits and existing kill-switch/credential/runtime gates.
7. Add event-trigger acceleration, broader opportunity persistence, more strategy families and richer reload behavior only after V1 closed-loop acceptance.

## 15. Safety

```text
phase=audit_and_contract_only
production_db_mutation=0
runtime_activation=0
broker_private_write=0
order_submission=0
live_orders=0
LIVE_authority_change=0
kill_switch_mutation=0
selection_account_awareness=0
decision_gate_bypass=0
executor_strategy_authority=0
```
