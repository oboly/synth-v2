# Strategy Proposal Contract v1

Status: Permanent architecture contract
Canonical location: `docs/architecture/strategy_proposal_contract_v1.md`
Scope: strategy interpretation output and its boundary with `decision_gate`
Runtime impact: none (documentation-only; defines the schema and boundaries a future implementation must follow)
Supersedes: the strategy-proposal-contract portions of `docs/todo/synth_v214_signal_dashboard_strategy_bridge_backlog.md` (removed; see `docs/development/docs_todo_canonicalization_batch_3b3_v1.md` and `docs/archive/synth_v214_signal_dashboard_strategy_bridge_backlog_history_v1.md`)

## 1. Purpose

A strategy proposal is:

- a structured interpretation of market evidence;
- scoped to a strategy, symbol, and horizon;
- account-agnostic;
- **not** an order;
- **not** an account-aware permission decision;
- **not** an execution plan;
- expiring and fully traceable back to its inputs.

A proposal is the output of the strategy/market interpretation layer only. It carries an opinion about what the strategy would do given market evidence. It never carries account identity, profile configuration, allocation capacity, permission, sizing, or order state.

Account/profile context is joined only when the proposal reaches `decision_gate`.

## 2. Separation of concerns

```text
market evidence
  (signals, features, framework/Breath-Fibo context, external research context)
-> strategy interpretation / proposal
    (market-only, account-agnostic; this contract)
-> decision_gate input envelope
    (proposal + account/profile/bucket references)
-> decision_gate account permission
    (balance, exposure, cooldown, configured profile/buckets)
-> execution_planner execution intent
    (passive/urgent, laddering, tick placement, repricing)
-> executor order handling
    (place/cancel/monitor orders, broker calls)
```

No shortcut may bypass a layer. In particular:

- `selection_engine` and strategy proposal production remain market-only and account-agnostic;
- a proposal must never contain account/profile/bucket ownership or capacity fields;
- a proposal must never be treated as account-aware permission;
- a proposal must never be treated as execution intent;
- a proposal must never be submitted to a broker directly;
- a dashboard rendering a proposal must never recompute or reinterpret it as an order instruction.

This restates, and does not replace, the layer boundaries in `AGENTS.md` and `docs/research/synth_v215_advice_route_contract_v1.md`.

## 3. Proposal identity

A proposal has distinct identity concepts. They are not interchangeable, and the legacy `strategy_id` / proposal-id ambiguity from the v2.14 backlog is not preserved:

- `proposal_id` — unique identifier for one emitted proposal instance (one strategy evaluation event, one point in time). Never reused.
- `strategy_id` — stable canonical strategy identity in `{ACTION}_{HORIZON}_{SETUP}` form, for example `SELL_SHORT_SPIKE`. Many proposals over time can share the same `strategy_id`.
- `trade_cycle_id` — optional market-thesis/cycle link between related `BUY` and `SELL` proposals. It is not an account-allocation identifier.

The following are explicitly **not proposal identity**:

- `strategy_profile_id`;
- `account_scope_ref`;
- `bucket_id`.

Those are account-aware `decision_gate` input-envelope fields; see Section 8.

`docs/research/synth_v215_advice_route_contract_v1.md` already uses `proposal_id` and a `{ACTION}*{HORIZON}*{SETUP}` strategy-id format for its route-stage research design. This contract is the canonical schema authority for those field names and the route document's proposal-contract section should treat this document as authoritative going forward.

## 4. Required proposal fields

Fields that belong to the canonical proposal object:

| Field | Meaning |
| --- | --- |
| `proposal_id` | Unique proposal instance identifier. |
| `strategy_id` | Canonical `{ACTION}_{HORIZON}_{SETUP}` strategy identity. |
| `trade_cycle_id` | Optional link between related market-thesis `BUY`/`SELL` proposals. |
| `symbol` | Traded asset/pair. |
| `horizon` | `SHORT` / `MID` / `LONG` (Section 6). |
| `action` | `BUY` / `SELL` / `HOLD` / `ROTATE` / `WARN` (Section 5). |
| `setup` | Canonical setup enum (Section 7). |
| `activation_condition` | Deterministic market condition under which the proposal becomes actionable for review. |
| `leg_state` | Lifecycle state of this proposal/strategy leg (Section 9). |
| `input_signal_refs` | References to primitive signal rows that produced this proposal. |
| `input_context_run_id` | Reference to the framework/confirmation context run that produced this proposal. |
| `created_ts_utc` | Creation timestamp. |
| `expiry_ts_utc` | Expiry timestamp. |
| entry/target/invalidation levels appropriate to `action` | Market levels; see below. |
| `invalidation_level` | Market level that invalidates the proposal thesis. |
| `confidence` | Confidence bucket or score derived from market evidence. |
| `rationale` | Human-readable market/strategy explanation. |
| `requires_manual_review` | Always `true` unless a separately validated automated lane exists. |

Levels are action-scoped, not universally required:

- `sell_levels` only when `action` is `SELL` or `HOLD`;
- `buy_levels` only when `action` is `BUY`.

### 4.1 Fields owned elsewhere

Fields that must **not** appear on the proposal object:

| Field concept | Owner |
| --- | --- |
| `strategy_profile_id`, `account_scope_ref`, `bucket_id` | `decision_gate` input envelope/context |
| Account balance, available cash, current position size, open orders | `decision_gate` live account state |
| `bucket_target_pct`, `bucket_available_pct`, `bucket_current_pct` | `decision_gate` configured/derived account allocation state |
| Permission result, sizing/capacity decision | `decision_gate` |
| Limit/market intent, laddering, tick placement, repricing | `execution_planner` |
| Broker order id, fill state, cancel/replace requests | `executor` |

No broker-write or order-submission fields belong in this contract. A proposal that includes any of `order_id`, `broker_order_payload`, `order_submit`, `cancel_order`, or `replace_order` is malformed.

## 5. Canonical action enum

- `BUY` — canonical action for adding/restoring exposure if later permitted by `decision_gate`.
- `SELL` — canonical action for reducing exposure if later permitted by `decision_gate`.
- `HOLD` — market/strategy recommendation to keep exposure; account feasibility remains outside the proposal.
- `ROTATE` — market/strategy recommendation to shift exposure from one thesis/opportunity toward another; actual account rotation permission and sizing remain `decision_gate`-owned.
- `WARN` — no-action market/strategy warning, for example no-chase or stale-context warning.

Synonym-normalization rules:

- do not use `entry`, `re-entry`, `rebuy`, `reload`, `dip-buy`, `retrace`, or `pullback-buy` as separate canonical action names — use `BUY` with `setup = PULLBACK` or `RECLAIM`;
- do not use `exit`, `take-profit`, `reduce`, or `trim` as separate canonical action names — use `SELL`;
- internal ids are stable all-caps enums; dashboard display labels are human-readable and may be renamed without changing the internal id.

`BUY` and `SELL` must remain separate proposals even when linked by a common `trade_cycle_id`.

## 6. Horizon enum

- `SHORT` — tactical trade-management horizon; typically expressed on lower intraday timeframes (`15m` / `1h` / `4h`) and event triggers.
- `MID` — swing horizon; typically expressed across `4h` / `1d` and several days.
- `LONG` — core-thesis horizon; typically expressed on `1d` / `1w` and multi-week or multi-month review.

Horizons are semantic (cadence of re-evaluation and thesis duration), not solely determined by a hardcoded candle interval.

## 7. Setup enum

Starter taxonomy retained from the v2.14 backlog:

- `SPIKE`
- `PULLBACK`
- `RECLAIM`
- `BASE`
- `REL_STRENGTH`
- `LEGACY_EXIT`
- `EXHAUSTION`
- `NO_CHASE`

If a future canonical document introduces a conflicting setup taxonomy, that document must explicitly reconcile with this one rather than create a duplicate enum.

## 8. Decision-gate account/profile envelope

This section is load-bearing for the architecture boundary.

A user/account-selected strategy profile and its allocation buckets are **account-aware configuration**. They must never be present in market-only strategy proposal production.

`decision_gate` receives two distinct inputs:

1. the canonical account-agnostic proposal defined by this document;
2. account/profile context assembled at the permission boundary.

The second input may use an explicit envelope such as:

| Envelope field | Meaning |
| --- | --- |
| `proposal_id` | Reference to the immutable account-agnostic proposal being evaluated. |
| `account_scope_ref` | Account/profile scope against which permission is evaluated. |
| `strategy_profile_id` | Account-aware strategy/allocation configuration selected for this account. |
| `bucket_id` | Allocation bucket to which the account policy maps this proposal/strategy. |

These envelope fields do **not** become proposal fields merely because they are joined to a proposal for evaluation.

`decision_gate` owns:

- selecting/resolving the applicable account/profile context;
- mapping a proposal/strategy into account bucket policy;
- target/configured bucket percentage;
- observed/current account allocation;
- available allocation/capacity;
- account balance, exposure, cooldown, open-order conflicts, and other protections;
- final account-aware permission and allowed sizing/capacity.

`selection_engine` and strategy proposal producers must not read or infer these values.

`execution_planner` and `executor` must not reinterpret bucket policy.

The v2.14 backlog listed `strategy_profile_id`, `account_scope_ref`, `bucket_id`, `bucket_target_pct`, `bucket_available_pct`, and `bucket_current_pct` adjacent to proposal data. This contract does not carry that ownership forward. They are account-aware permission context and belong at `decision_gate`.

## 9. Proposal lifecycle

Proposal lifecycle is distinct from order lifecycle (`executor`-owned) and execution-plan lifecycle (`execution_planner`-owned).

Market/strategy-side proposal states may include:

- `created` — proposal emitted, not yet reviewed;
- `active` / `pending_review` — within freshness/expiry window;
- `expired` — `expiry_ts_utc` passed without action;
- `invalidated` — market moved through `invalidation_level`;
- `superseded` — newer proposal for the same `strategy_id`/`symbol` replaces this one.

Downstream processing may separately record that a proposal was:

- accepted or rejected by `decision_gate`;
- consumed by `execution_planner`.

Those downstream outcomes must not be confused with proposal-owned market lifecycle state. A proposal never transitions directly into an order state.

## 10. Freshness and provenance

Every proposal must carry:

- `input_signal_refs`;
- `input_context_run_id`;
- `created_ts_utc`;
- `expiry_ts_utc`;
- a deterministic, reproducible link from proposal back to the market evidence that produced it.

A stale proposal (past `expiry_ts_utc`, or built from stale context) must not be displayed as active. Dashboard rendering must not own or control freshness; freshness is computed upstream by the proposal-producing market/strategy layer.

## 11. External/LLM proposal producers

An LLM or external agent may act only as a **market/strategy proposal producer**. It may:

- consume an explicit, bounded market/context bundle;
- emit schema-valid proposals under this contract;
- provide `rationale`;
- attach provenance;
- set `expiry_ts_utc`.

It may not:

- read account balances, positions, open orders, bucket capacities, or account profile configuration for proposal generation;
- grant account-aware permission;
- choose an account bucket;
- bypass `decision_gate`;
- create execution intent;
- submit, modify, or cancel orders;
- mutate canonical market evidence.

This restates the agent/LLM boundary in `docs/ops/runtime_chain_ownership_v1.md`. This document grants no authority beyond market/strategy proposal production.

## 12. Manual ingestion boundary

Where a proposal is transported into Synth manually, only the following transport principles are permanent:

- atomic intake — a proposal batch is accepted as a whole or not at all;
- explicit completeness marker;
- `incoming` / `processed` / `rejected` lifecycle for transport files;
- schema validation against this contract before acceptance;
- idempotency — re-ingesting the same batch must not duplicate proposals;
- partial or malformed payloads are rejected, not partially applied.

XLSX is not the canonical proposal format. It is one optional transport representation for the manual fallback path; the architecture contract is the schema in Section 4, independent of transport encoding.

Manual ingestion must not inject account/profile/bucket context into the proposal object. That join still occurs only at `decision_gate`.

## 13. Reporting contract

Only durable, read-only reporting principles are canonical here:

- asset cards, tables, or other layouts are presentation choices, not architecture;
- show human-readable labels with the stable internal id available;
- show evidence, freshness, lifecycle state, and expiry;
- account/profile/bucket information, when shown alongside a proposal, must be labeled as downstream `decision_gate` context rather than proposal-owned data;
- no hidden final labels — a displayed conclusion must be traceable to visible strategy inputs and freshness;
- no dashboard-owned calculation or reinterpretation of a proposal's action.

UI layout details remain owned by the relevant dashboard TODO/Issue.

## 14. Anti-patterns

- signals or strategy proposal producers read account state;
- account/profile/bucket fields embedded in the canonical proposal schema;
- account bucket configuration placed in `selection_engine`;
- dashboard owns ingestion or canonical calculation;
- LLM acts as permission, execution, or order layer;
- hidden proposal logic (a conclusion without visible inputs);
- a stale proposal displayed as active;
- HTF context universally vetoing valid lower-horizon evidence;
- external research replacing Synth-native evidence as source of truth;
- any direct proposal -> execution/order shortcut that bypasses `decision_gate`.

## 15. Related documents

- `docs/research/synth_v215_advice_route_contract_v1.md` — route-stage research design; this contract is the canonical schema authority for its proposal-contract section.
- `docs/ops/runtime_chain_ownership_v1.md` — runtime ownership and freshness contract.
- `docs/ops/market_breath_context_bridge_v1.md` — Synth-native Market Breath vs. A+ legacy context separation.
- `docs/research/external_research_ingestion_v1.md` and `docs/research/external_elliott_wave_claim_validation_v1.md` — external research normalization; may feed market/framework context, never account-aware permission.
- `docs/research/paper_advice_manual_trading_cockpit_v1.md` — read-only manual-review cockpit role.
- `docs/todo/signal_matrix_dashboard.md` and `docs/todo/manual_ladder_dashboard.md` — active dashboard lanes that may eventually render proposals under this contract.
- `docs/archive/synth_v214_signal_dashboard_strategy_bridge_backlog_history_v1.md` — historical-only predecessor material.
