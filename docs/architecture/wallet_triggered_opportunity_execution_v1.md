# Wallet-triggered opportunity execution v1

Status: proposed canonical architecture for Issue #557 / Synth V1 Lane C
Scope: market opportunity -> account permission/allocation -> immutable execution intent -> shared executor/reconciliation -> exit coverage -> released-capital reevaluation
Runtime impact: none. This document is audit/design only.

## 1. Decision summary

Synth V1 closes the loop by reusing the existing market, decision, planning and shared-executor contracts. It does not introduce new authority-bearing Asset Analyst, Investment Agent, wallet-agent or BUY/SELL executor services.

Canonical V1 flow:

```text
market-only producer / selection
-> current actionable BUY candidate
-> decision_gate account permission + allocation ceiling
-> execution_planner immutable BUY ladder
-> shared execution handoff / reconciliation
-> BUY fill / canonical position truth
-> canonical automatic-exit profile resolution
-> automatic-exit candidate
-> decision_gate exit permission
-> execution_planner immutable SELL plan
-> shared execution handoff / reconciliation
-> SELL fill
-> refreshed COMPLETE account-state bundle
-> next decision_gate evaluation of current market opportunities
```

Market ranking remains account-agnostic. Account-state changes may cause a new account-aware evaluation, but they never mutate market ranking truth.

Explicit decisions:

1. Do not create `Asset Analyst` or `Investment Agent` as new runtimes. Existing market producers plus `selection_engine`/read models own those logical roles.
2. Do not add a generic `asset_opportunity` table for V1. Reuse existing proposal/candidate identity and provenance.
3. Retain `execution_planner`. BUY still requires deterministic notional-to-quantity conversion, venue-safe rounding, minimum checks and immutable ladder construction after permission.
4. `decision_gate` remains the sole account-aware permission/allocation owner for both BUY and SELL.
5. COMPLETE account-state snapshots plus the canonical automatic-BUY allocation-evidence projection remain the wallet/account source of truth.
6. Reuse the shared side-neutral executor/handoff/reconciliation substrate.
7. Automatic BUY LIVE remains blocked until compatible automatic exit coverage is proven for the exact admitted V1 family.

## 2. Current-state audit

The repository already contains the required BUY-side phases:

```text
#399 Phase 1  market-only automatic BUY candidate
#399 Phase 2  decision_gate BUY permission/allocation
#399 Phase 3  execution_planner immutable BUY ladder
#399 Phase 4  deterministic runtime + append-only evidence
#399 Phase 5  DRY_RUN/PAPER acceptance preview
#399 Phase 6  shared side-neutral executor handoff integration
#399 Phase 7  separately authorized LIVE phase, not yet accepted
```

Relevant owners include:

```text
docs/architecture/strategy_proposal_contract_v1.md
src/entry_policy/automatic_buy_candidate_v1.py
src/decision_gate/automatic_buy_gate_v1.py
src/decision_gate/automatic_buy_account_allocation_evidence_contract_v1.py
src/decision_gate/automatic_buy_account_allocation_evidence_repository_v1.py
src/execution_planner/automatic_buy_planner_v1.py
src/entry_policy/automatic_buy_runtime_orchestrator_v1.py
src/entry_policy/run_automatic_buy_dry_run_acceptance_v1.py
```

The shared executor/handoff foundation already exists from #206 and #399 Phase 6. No BUY-specific broker stack is justified.

### 2.1 Strategy proposal vs automatic BUY candidate

`StrategyProposal` remains the generic market-only proposal contract. `AutomaticBuyCandidateV1` is the narrower current automatic-entry seam. Neither contains account state, permission or broker authority.

Current entry timing is not a full reclaim-state machine. The exact `WAITING / BUY_WINDOW / INVALIDATED / STOP_CHASING` transition and reclaim/recovery trigger remain market-policy/producer concerns upstream of `decision_gate`.

### 2.2 Account and deployable-capital truth

Canonical automatic-BUY account evidence is assembled from account-owned state such as:

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

The gate owns the final account-specific ceiling. Market ranking never reads or derives it.

### 2.3 Planner necessity

The planner remains required because the post-gate transformation is real:

```text
approved EUR notional ceiling
-> reference-price conversion to base quantity
-> side-aware venue rounding
-> min quantity / min notional / capability checks
-> deterministic leg distribution
-> immutable BUY plan
```

Moving this into `decision_gate` would mix permission with execution construction. Moving it into the executor would give order handling execution-policy authority.

## 3. Automatic-exit dependency and V1 family restriction

The canonical #657 Phase A architecture contract is already landed as:

```text
docs/architecture/automatic_exit_profile_promotion_v1.md
```

Its current state is architecture-complete but producer-blocked. The remaining dependency is **#657 Phase B evidence availability**, currently requiring a documented accepted conclusion from #270 or another explicitly reviewed source that supersedes it.

The current `automatic_exit_profile_v1` resolver matches only:

```text
(venue, asset_id, market)
```

It does **not** bind profile rows by strategy, horizon or setup. Therefore V1 must not admit arbitrary same-market BUY candidates and assume the market-level profile is semantically compatible.

### 3.1 Mandatory V1 restriction

Until a separately reviewed profile schema/contract expansion adds strategy/horizon/setup identity, automatic BUY eligibility is restricted to the **exact profile-supported family** established by the accepted #657 Phase B evidence and promotion review.

That family must be documented before any DRY_RUN/PAPER closed-loop acceptance that claims exit coverage and before any LIVE authorization. At minimum the admission contract must identify:

```text
venue
asset_id
market
strategy_id / strategy family
horizon
setup family where relevant
profile evidence_id / method_version
```

Only a BUY candidate matching that reviewed family may be considered covered by the market-level profile. A different strategy/horizon/setup on the same `(venue, asset_id, market)` is **not automatically covered** and must fail closed for automatic closed-loop admission.

This restriction is a V1 architecture gate. It does not alter the existing resolver or schema. If more than one strategy/horizon family per market needs independent exit policy, that requires a separately reviewed schema/contract expansion owned outside this #557 audit.

No profile may be fabricated simply to make the runtime pass.

## 4. Target component ownership / gap matrix

| Target concept | Classification | Canonical V1 owner |
| --- | --- | --- |
| Asset Analyst | RENAME_ONLY logical role | existing market producers + candidate adapters |
| Investment Agent | RENAME_ONLY logical role | `selection_engine` / market ranking read model |
| Generic Strategy Proposal | REUSE_AS_IS | `strategy_proposal_contract_v1` |
| Actionable automatic BUY candidate | REUSE_AS_IS | `automatic_buy_candidate_v1` |
| Generic persisted `asset_opportunity` | NOT_REQUIRED_FOR_V1 | defer |
| Opportunity lifecycle | EXTEND_EXISTING upstream | market/strategy producer |
| Account/wallet truth | REUSE_AS_IS | COMPLETE account-state snapshot bundle |
| Account allocation evidence | REUSE_AS_IS | automatic-BUY allocation-evidence projection |
| BUY permission/allocation | REUSE_AS_IS | `decision_gate` |
| BUY execution construction | REUSE_AS_IS | `execution_planner` |
| BUY runtime/audit/idempotency | REUSE_AS_IS | #399 Phase 4 |
| BUY DRY_RUN/PAPER seam | REUSE_AS_IS | #399 Phase 5 |
| BUY shared executor handoff | REUSE_AS_IS | #399 Phase 6 + #206 |
| Automatic-exit resolver | REUSE_AS_IS | existing automatic-exit runtime/resolver |
| Automatic-exit promotion architecture | REUSE_AS_IS / LANDED | #657 Phase A canonical contract |
| Automatic-exit evidence-backed producer | BLOCKED | #657 Phase B pending accepted evidence |
| Strategy/horizon-specific exit-profile keying | NOT_PRESENT | V1 restricted to exact supported family; future reviewed schema expansion if needed |
| Shared order/fill/reconciliation truth | REUSE_AS_IS | shared executor persistence/reconciliation |
| Wallet-trigger event service | NOT_REQUIRED_FOR_V1 | deterministic cadence first |

## 5. Trigger semantics

V1 uses deterministic cadence over canonical state as the authoritative trigger.

```text
SELL fill / released quote capacity
-> reconciliation
-> next COMPLETE account-state bundle
-> next automatic BUY evaluation cycle
-> decision_gate evaluates current ranked opportunities with fresh account facts
```

A future event may accelerate a cycle, but the event is only a hint. It never carries canonical balance truth, market ranking truth or permission.

## 6. Duplicate and race prevention

Use existing identities:

```text
candidate/proposal identity
+ canonical account evidence identity/timestamps
+ config/protection identities
-> automatic BUY runtime idempotency key
-> immutable BUY plan identity
-> shared executor plan_reference_id / handoff identity
-> deterministic per-leg client order identity
```

Repeated evaluation of identical evidence must not create a second logical plan or order. Singleton/locking, persistence uniqueness and shared reconciliation remain authoritative.

## 7. Fill -> exit coverage

A BUY plan is not a position. Exit quantity is derived only from confirmed fill/position truth.

```text
confirmed filled quantity
-> canonical position/fill evidence
-> exact admitted V1 family check
-> automatic-exit profile resolution
-> automatic-exit candidate
-> decision_gate exit permission
-> execution_planner immutable SELL plan
-> shared executor/reconciliation
```

SELL planned quantity may not exceed confirmed available quantity. Partial fills receive exit coverage only for confirmed filled quantity; unfilled BUY remainder stays BUY-order state.

If no unique valid profile resolves, or if the filled BUY does not match the exact reviewed profile-supported family, automatic exit handling fails closed.

## 8. Opportunity lifecycle while BUY is open

Market lifecycle and broker-order lifecycle remain distinct.

- `INVALIDATED` / `STOP_CHASING` remain market-side facts.
- An open BUY is executor/order state.
- Cancellation requires an explicit upstream-approved cancel intent; executor never infers strategy invalidation from price.
- A better opportunity does not silently steal an existing reservation.
- Reallocation occurs only after canonical account/order state reflects released capacity and `decision_gate` evaluates again.

## 9. Multi-horizon and multi-account semantics

Market ranking may retain separate 1h/4h/1d/etc. opportunities. They remain distinct market objects.

However, automatic closed-loop V1 admission is narrower than market ranking: only the single exact strategy/horizon/profile family reviewed as compatible with the market-level exit profile may enter the automatic loop. Other same-market horizons remain visible/rankable but are non-eligible for automatic closed-loop execution until compatible profile semantics exist.

Multiple accounts may independently evaluate the same admitted market opportunity. Account identity appears only downstream at `decision_gate`.

## 10. Provenance

Required lineage:

```text
market proposal/candidate evidence
-> admitted V1 strategy/horizon family identity
-> AutomaticBuyGateDecisionV1
-> AutomaticBuyPlanV1
-> ApprovedExecutionPlanV1 / handoff
-> BUY order leg(s)
-> fill / position evidence
-> automatic exit profile + evidence_id/method_version
-> automatic-exit candidate
-> SELL decision
-> SELL plan
-> shared handoff
-> SELL order leg(s)
-> fills / realized outcome
```

A reporting-only `source_opportunity_id` may supplement lineage but never replaces plan/order/fill identities.

## 11. Schema delta

No new schema is justified by #557 Phase A.

Do not add from this issue:

```text
asset_opportunity
asset_opportunity_event
wallet_agent_state
investment_agent_state
current_limit_sell_orders
```

The strategy/horizon/profile mismatch is handled in V1 by a strict admission restriction, not by silently changing `automatic_exit_profile_v1`. If multi-family automatic execution becomes required, the profile-key expansion must be a separate reviewed schema/contract issue.

#657 Phase B owns its own producer/promotion schema decisions and the pre-Phase-B immutability/supersession requirement already documented in `automatic_exit_profile_promotion_v1.md`.

## 12. Failure modes

| Failure mode | V1 behavior |
| --- | --- |
| stale/missing market candidate | fail closed / no BUY plan |
| stale/missing account evidence | fail closed in gate path |
| insufficient free quote balance | deny |
| open BUY/reservation conflict | deny according to canonical policy |
| duplicate evaluation | idempotent same logical outcome |
| simultaneous workers | singleton/lock + persistence uniqueness |
| candidate invalidated while BUY open | explicit cancel-intent path only; executor does not infer |
| partial BUY fill | exit only confirmed filled quantity |
| no exit profile | fail closed |
| conflicting exit profiles | fail closed exactly-one-match |
| same market but wrong strategy/horizon family | fail closed automatic-loop admission |
| missing SELL coverage after fill | reconciliation/runtime surfaces uncovered position; never invent target |
| target/profile revision | only canonical profile/policy owner may supersede |
| account snapshot lag | fail closed on freshness |
| broker snapshot lag | reconciliation remains source of broker-order truth |
| venue rejection/minimum/tick failure | planner/venue constraints reject where possible; preserve broker rejection truth |
| broker/API outage | preserve persisted intent/state; no invented success |
| restart | recover from persisted runtime/handoff/order identity |
| multiple accounts | independent downstream decisions |
| multiple horizons same market | only exact admitted family automatic; others stay market-only/non-eligible |
| delisting/suspension | fail closed at capability/order boundary |
| kill switch/pause | never bypassed |

## 13. Issue reconciliation

### #399 automatic BUY

Keep open. Repository Phases 1-6 are reusable. Phase 7 LIVE remains separate and must not proceed until exact closed-loop DRY_RUN/PAPER acceptance includes compatible exit coverage.

### #657 automatic exit profile promotion

V1 critical. **Phase A is already landed** in `docs/architecture/automatic_exit_profile_promotion_v1.md`. Do not schedule it again. Current dependency is Phase B evidence availability plus the Phase-B implementation/preview/approval work defined by that contract.

### #270 exit/target research

Current upstream evidence gate for #657 Phase B. It must return an explicit reviewed disposition and must not itself write production policy.

### #665 retracement/reload

May attach later as another market-only producer. It is not admitted to automatic closed-loop execution unless its strategy/horizon family is explicitly covered by compatible exit-profile semantics.

### #666 V1 finish line

This contract narrows Lane C to reuse existing owners and one safe profile-supported automatic family rather than expanding V1 breadth.

## 14. Dependency-ordered implementation sequence

1. Merge this #557 architecture contract after review.
2. Complete #270 or accept another explicitly reviewed canonical evidence source for #657 Phase B.
3. Implement the smallest #657 Phase B producer/read-only preview permitted by the landed Phase A contract, including its documented schema/supersession prerequisites.
4. Review and explicitly record the exact V1 automatic family `(market + strategy/horizon/setup semantics)` supported by the promoted profile evidence.
5. Exercise one exact DRY_RUN/PAPER closed loop for that family only: candidate -> BUY gate -> BUY planner -> shared handoff/reconciliation -> confirmed fill evidence -> family compatibility check -> exit profile -> SELL gate -> SELL planner -> shared handoff/reconciliation -> released-capital reevaluation.
6. Only after that exact path is accepted, review #399 Phase 7 separately with bounded account/market/notional/order authority and existing kill-switch/credential/runtime gates.
7. Broaden strategies, horizons, profile schema or event-trigger acceleration only after V1 acceptance.

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
