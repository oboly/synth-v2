# Strategy Proposal Contract v1

Status: Permanent architecture contract
Canonical location: `docs/architecture/strategy_proposal_contract_v1.md`
Scope: cross-layer contract — strategy interpretation output, decision-gate
input
Runtime impact: none (documentation-only; defines the schema and boundaries a
future implementation must follow)
Supersedes: the strategy-proposal-contract portions of
`docs/todo/synth_v214_signal_dashboard_strategy_bridge_backlog.md` (removed;
see `docs/development/docs_todo_canonicalization_batch_3b3_v1.md` and
`docs/archive/synth_v214_signal_dashboard_strategy_bridge_backlog_history_v1.md`)

## 1. Purpose

A strategy proposal is:

- a structured interpretation of market evidence;
- scoped to a strategy, a strategy profile, and a horizon;
- **not** an order;
- **not** an account-aware permission decision;
- **not** an execution plan;
- expiring and fully traceable back to its inputs.

A proposal is the output of the `strategy` layer only. It carries an opinion
about what a strategy would do, under a given account profile, if permitted.
It never carries permission, sizing, or order state itself.

## 2. Separation of concerns

```text
market evidence
  (signals, features, framework/Breath-Fibo context, external research context)
-> strategy interpretation / proposal
    (this contract)
-> decision_gate account permission
    (balance, exposure, cooldown, configured profile/buckets)
-> execution_planner execution intent
    (passive/urgent, laddering, tick placement, repricing)
-> executor order handling
    (place/cancel/monitor orders, broker calls)
```

No shortcut may bypass a layer. In particular:

- a proposal must never be treated as account-aware permission;
- a proposal must never be treated as execution intent;
- a proposal must never be submitted to a broker directly;
- a dashboard rendering a proposal must never recompute or reinterpret it as
  an order instruction.

This restates, and does not replace, the layer boundaries in `AGENTS.md` and
`docs/research/synth_v215_advice_route_contract_v1.md`.

## 3. Proposal identity

A proposal has several distinct identity concepts. They are not
interchangeable, and the legacy `strategy_id` / proposal id ambiguity from the
v2.14 backlog is not preserved:

- `proposal_id` — a unique identifier for one emitted proposal instance
  (one strategy evaluation event, one point in time). Never reused.
- `strategy_id` — the stable canonical strategy identity in
  `{ACTION}_{HORIZON}_{SETUP}` enum form (for example `SELL_SHORT_SPIKE`).
  Many proposals over time can share the same `strategy_id`.
- `strategy_profile_id` — the account-aware strategy profile (Joost's chosen
  allocation configuration) that was active when the proposal was generated.
  This is a reference only; the proposal does not own or evaluate the
  profile.
- `trade_cycle_id` — links a `BUY` proposal to a later `SELL` proposal (or
  vice versa) that belong to the same round-trip thesis, without merging them
  into a single proposal or a single allocation (see Section 6).

`docs/research/synth_v215_advice_route_contract_v1.md` already uses
`proposal_id` and a `{ACTION}*{HORIZON}*{SETUP}` strategy id format for its
route-stage research design; this contract is the canonical schema authority
for those field names and the route document's proposal-contract section
(3.4) should treat this document as authoritative going forward. No second,
conflicting canonical proposal contract exists.

## 4. Required proposal fields

Fields that belong to the proposal object:

| Field | Meaning |
| --- | --- |
| `proposal_id` | Unique proposal instance identifier. |
| `strategy_id` | Canonical `{ACTION}_{HORIZON}_{SETUP}` strategy identity. |
| `strategy_profile_id` | Reference to the account-aware profile active at generation time. |
| `account_scope_ref` | Explicit reference to the account scope this proposal was profiled against, or an explicit account-agnostic marker if none applies. |
| `bucket_id` | Reference to the allocation bucket the strategy leg operates on (for example `SHORT_TACTICAL`). Reference only — see Section 8. |
| `trade_cycle_id` | Optional link between paired `BUY`/`SELL` proposals. |
| `symbol` | Traded asset/pair. |
| `horizon` | `SHORT` / `MID` / `LONG` (Section 6). |
| `action` | `BUY` / `SELL` / `HOLD` / `ROTATE` / `WARN` (Section 5). |
| `setup` | Canonical setup enum (Section 7). |
| `activation_condition` | Deterministic condition under which the proposal becomes actionable for review. |
| `leg_state` | Lifecycle state of this specific strategy leg (Section 9). |
| `input_signal_refs` | References to the primitive signal rows that produced this proposal. |
| `input_context_run_id` | Reference to the framework/confirmation context run that produced this proposal. |
| `created_ts_utc` | Creation timestamp. |
| `expiry_ts_utc` | Expiry timestamp. |
| entry/target/invalidation levels appropriate to `action` | See below. |
| `invalidation_level` | Level that invalidates the proposal's thesis. |
| `confidence` | Confidence bucket or score. |
| `rationale` | Human-readable explanation. |
| `requires_manual_review` | Always `true` unless a separately validated automated lane exists. |

Levels are action-scoped, not universally required:

- `sell_levels` only when `action` is `SELL` or `HOLD`;
- `buy_levels` only when `action` is `BUY`.

No account values are invented here. `bucket_id` is a reference to a bucket
that `decision_gate` owns and evaluates — the proposal never carries the
bucket's percentage, current allocation, or available capacity (Section 8).

### 4.1 Fields owned elsewhere

For clarity, fields that must **not** appear on the proposal object, and
where they actually belong:

| Field concept | Owner |
| --- | --- |
| Account balance, available cash, current position size, open orders | `decision_gate` (reads live account state; not carried on the proposal) |
| `bucket_target_pct`, `bucket_available_pct`, `bucket_current_pct` | `decision_gate` (evaluates the proposal's `bucket_id` against current configured/observed allocation) |
| Limit/market intent, laddering, tick placement, repricing | `execution_planner` |
| Broker order id, fill state, cancel/replace requests | `executor` |

No broker-write or order-submission fields belong in this contract. A
proposal that includes any of `order_id`, `broker_order_payload`,
`order_submit`, `cancel_order`, or `replace_order` is malformed.

## 5. Canonical action enum

- `BUY` — the only canonical action for adding or restoring exposure (covers
  entry, re-entry, rebuy, reload, dip-buy).
- `SELL` — the only canonical action for reducing exposure (covers exit,
  take-profit, reduce, trim).
- `HOLD` — keep exposure with levels, trailing, or invalidation context.
- `ROTATE` — reduce or shift exposure in favor of another thesis or
  opportunity.
- `WARN` — no-action warning (for example no-chase or stale-context warning).

Synonym-normalization rules:

- do not use `entry`, `re-entry`, `rebuy`, `reload`, `dip-buy`, `retrace`, or
  `pullback-buy` as separate canonical action names — use `BUY` with
  `setup = PULLBACK` or `RECLAIM`;
- do not use `exit`, `take-profit`, `reduce`, or `trim` as separate canonical
  action names — use `SELL`;
- internal ids are stable all-caps enums; dashboard display labels are
  human-readable sentence-case and may be renamed without changing the
  internal id.

`BUY` and `SELL` **must remain separate proposals**, even when linked by a
common `trade_cycle_id`. A cycle link is traceability metadata, not a merge
of the two proposals into one.

## 6. Horizon enum

- `SHORT` — tactical trade-management horizon; typically expressed on lower
  intraday timeframes (`15m` / `1h` / `4h`) and event triggers.
- `MID` — swing horizon; typically expressed across `4h` / `1d` and several
  days.
- `LONG` — core-thesis horizon; typically expressed on `1d` / `1w` and
  multi-week or multi-month review.

Horizons are defined semantically (cadence of re-evaluation and thesis
duration), not solely by a hardcoded timeframe. The timeframes above are
illustrative examples; a proposal's horizon ownership is not determined by
which candle interval happened to trigger it.

## 7. Setup enum

Starter taxonomy, retained from the v2.14 backlog as it does not conflict
with existing canonical enums (no other canonical document defines a
competing setup taxonomy for strategy proposals):

- `SPIKE`
- `PULLBACK`
- `RECLAIM`
- `BASE`
- `REL_STRENGTH`
- `LEGACY_EXIT`
- `EXHAUSTION`
- `NO_CHASE`

If a future canonical document introduces a conflicting setup taxonomy, that
document must explicitly reconcile with this one rather than create a
duplicate enum.

## 8. Strategy profile and bucket ownership

This section is load-bearing for the architecture boundary.

A user/account-selected strategy profile and its target allocation buckets
are **account-aware configuration**:

- they must not live in `selection_engine`;
- they must not be selected or rewritten by market signals;
- the proposal may only *reference* the profile and bucket under which it was
  generated (`strategy_profile_id`, `bucket_id`);
- `decision_gate` owns evaluation of a proposal against actual account state
  and configured limits, including bucket percentages;
- `execution_planner` and `executor` must not reinterpret bucket policy.

Distinguish clearly between four different bucket-related numbers, and note
that only the first is proposal-adjacent (as a static profile fact, not a
proposal field) — the other three never appear on the proposal:

1. **target/configured bucket percentage** — part of the account-aware
   `strategy_profile_id` configuration, owned by `decision_gate`;
2. **observed/current account allocation** — live account state, owned by
   `decision_gate`;
3. **available allocation** — derived from (1) and (2), owned by
   `decision_gate`;
4. **proposed change** — implied by the proposal's `action` and `bucket_id`,
   but the magnitude/sizing of that change is decided by `decision_gate` and
   `execution_planner`, not carried as a percentage on the proposal.

The v2.14 backlog listed `bucket_target_pct` and
`bucket_available_pct`/`bucket_current_pct` as proposal fields. This contract
does not carry that forward: live or configured account-state percentages
are not owned by the proposal schema merely because a prior draft listed
them. The proposal carries `bucket_id` only.

`BUY` and `SELL` legs inside the same bucket are not separate allocations
(for example, a `SELL_SHORT_SPIKE` proposal and a `BUY_SHORT_PULLBACK`
proposal both referencing `bucket_id = SHORT_TACTICAL` must not be summed by
`decision_gate` into double the bucket's target percentage).

## 9. Proposal lifecycle

Proposal lifecycle is distinct from order lifecycle (`executor`-owned) and
from execution-plan lifecycle (`execution_planner`-owned). Deterministic
proposal states:

- `created` — proposal emitted, not yet reviewed.
- `active` / `pending_review` — within its freshness/expiry window, visible
  for manual or `decision_gate` review.
- `expired` — `expiry_ts_utc` passed without action; must not display as
  active.
- `invalidated` — market moved through `invalidation_level`; thesis no
  longer holds.
- `accepted_by_decision_gate` — `decision_gate` evaluated the proposal as
  permitted for the current account state.
- `rejected_by_decision_gate` — `decision_gate` evaluated the proposal as not
  permitted (insufficient cash, exposure conflict, cooldown, or profile
  mismatch).
- `superseded` — a newer proposal for the same `strategy_id`/`symbol`
  replaces this one before it was acted on.
- `consumed` / `planned` — where applicable, `execution_planner` has turned
  an accepted proposal into an execution plan. This state lives on the
  execution-planner side of the boundary; the proposal record only reflects
  that it was consumed, not the plan's own state machine.

A proposal never transitions directly into an order state. Only
`decision_gate` may move a proposal into `accepted_by_decision_gate` /
`rejected_by_decision_gate`, and only `execution_planner` may mark a proposal
`consumed`.

## 10. Freshness and provenance

Every proposal must carry:

- `input_signal_refs` — source primitive signal rows;
- `input_context_run_id` — the framework/confirmation context run that
  produced it;
- `created_ts_utc`;
- `expiry_ts_utc`;
- a deterministic, reproducible link from proposal back to the evidence that
  produced it.

A stale proposal (past `expiry_ts_utc`, or built from stale
`input_context_run_id`) must not be displayed as active. Dashboard rendering
must not own or control freshness — freshness is computed by the layer that
produced the proposal, not by the renderer (see
`docs/ops/runtime_chain_ownership_v1.md`, "Freshness Contract").

## 11. External/LLM proposal producers

An LLM or external agent may act only as a **proposal producer**. It may:

- consume an explicit, bounded context bundle;
- emit schema-valid proposals under this contract;
- provide `rationale`;
- attach provenance (`input_signal_refs`, `input_context_run_id`);
- set `expiry_ts_utc`.

It may not:

- grant account-aware permission;
- bypass `decision_gate`;
- create execution intent;
- submit, modify, or cancel orders;
- mutate canonical market evidence.

This restates and narrows the "Agent / LLM Bridge Boundary" already defined
in `docs/ops/runtime_chain_ownership_v1.md`; that document remains the
runtime-ownership-side statement of the same boundary, this contract is the
schema-side statement. Both must stay consistent; this document does not
grant any authority beyond what is stated here.

## 12. Manual ingestion boundary

Where a proposal is transported into Synth manually (for example, an
external LLM session producing proposals outside a live agent connection),
only the following transport principles are permanent:

- atomic intake — a proposal batch is accepted as a whole or not at all;
- an explicit completeness marker accompanies the batch;
- an `incoming` / `processed` / `rejected` lifecycle for transport files;
- schema validation against this contract before acceptance;
- idempotency — re-ingesting the same batch must not duplicate proposals;
- partial or malformed payloads are rejected, not partially applied.

XLSX is **not** the canonical proposal format. It is one optional transport
representation for the manual fallback path; the architecture contract is
the schema in Section 4, independent of transport encoding.

## 13. Reporting contract

Only durable, read-only reporting principles are canonical here:

- asset cards, tables, or other layouts are presentation choices, not
  architecture;
- show human-readable labels with the stable internal id available
  (tooltip/detail);
- show evidence, freshness, lifecycle state, expiry, and the
  strategy/profile references a proposal carries;
- no hidden final labels — a displayed conclusion must be traceable to a
  visible strategy, visible inputs, and visible freshness;
- no dashboard-owned calculation or reinterpretation of a proposal's action.

UI layout details (card vs. table, column order, collapse/expand behavior)
do not belong in this contract unless they enforce traceability or safety;
those remain owned by the relevant dashboard TODO/Issue
(`docs/todo/signal_matrix_dashboard.md`, `docs/todo/manual_ladder_dashboard.md`).

## 14. Anti-patterns

- signals directly emit account-aware advice;
- account bucket configuration placed in `selection_engine`;
- dashboard owns ingestion or canonical calculation;
- LLM acts as permission, execution, or order layer;
- allocation double-counting across linked `BUY`/`SELL` legs sharing a
  `trade_cycle_id`;
- hidden proposal logic (a conclusion without visible inputs);
- a stale proposal displayed as active;
- HTF context universally vetoing valid lower-horizon evidence (every
  timeframe may carry its own truth; HTF is context, not a block);
- external A+/forecast context replacing Synth-native evidence as source of
  truth (external research may validate or calibrate, never replace).

## 15. Related documents

- `docs/research/synth_v215_advice_route_contract_v1.md` — route-stage
  research design (`framework_context` -> `synth_confirmation_context` ->
  `strategy_interpretation` -> proposal); this contract is the canonical
  schema authority for its proposal-contract section.
- `docs/ops/runtime_chain_ownership_v1.md` — runtime ownership and freshness
  contract; canonical for dashboard/runtime-side boundary statements.
- `docs/ops/market_breath_context_bridge_v1.md` — Synth-native Market Breath
  vs. A+ legacy context separation.
- `docs/research/external_research_ingestion_v1.md` and
  `docs/research/external_elliott_wave_claim_validation_v1.md` — external
  research normalization; feed `framework_context`/`rationale` only, never
  proposal truth directly.
- `docs/research/paper_advice_manual_trading_cockpit_v1.md` — read-only
  manual-review cockpit role.
- `docs/todo/signal_matrix_dashboard.md` and
  `docs/todo/manual_ladder_dashboard.md` — active dashboard lanes that will
  eventually render proposals under this contract; still open, not
  superseded by this document.
- `docs/archive/synth_v214_signal_dashboard_strategy_bridge_backlog_history_v1.md`
  — historical-only predecessor material.
