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
- scoped to a strategy and a horizon;
- market-only and account-agnostic in itself;
- **not** an order;
- **not** an account-aware permission decision;
- **not** an execution plan;
- expiring and fully traceable back to its inputs.

A proposal is the output of the `strategy` layer only. It carries a
market-only opinion about what a strategy would do, given evidence and
thesis, if it were evaluated and permitted. It never carries account/profile
scope, permission, sizing, or order state itself. Account-aware scope (which
strategy profile, which bucket, which account) is attached only when a
proposal is combined into a `decision_gate` input envelope at evaluation
time — see Section 3a.

## 2. Separation of concerns

```text
market evidence
  (signals, features, framework/Breath-Fibo context, external research context)
-> strategy interpretation / proposal
    (this contract)
-> decision_gate account permission
    (balance, exposure, cooldown, configured profile/buckets; evaluated
    against a decision_gate input envelope that pairs the market-only
    proposal with account-aware profile/bucket/account-scope context —
    Section 3a. The envelope is not part of the proposal object.)
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
- `trade_cycle_id` — links a `BUY` proposal to a later `SELL` proposal (or
  vice versa) that belong to the same round-trip thesis, without merging them
  into a single proposal or a single allocation (see Section 6).

`strategy_profile_id`, `account_scope_ref`, and `bucket_id` are **not**
proposal identity concepts. They identify account-aware evaluation context
and exist only at the `decision_gate` input envelope layer — see Section 3a.

`docs/research/synth_v215_advice_route_contract_v1.md` already uses
`proposal_id` and a `{ACTION}*{HORIZON}*{SETUP}` strategy id format for its
route-stage research design; this contract is the canonical schema authority
for those field names and the route document's proposal-contract section
(3.4) should treat this document as authoritative going forward. No second,
conflicting canonical proposal contract exists.

## 3a. Decision-gate input envelope

A proposal is market-only and carries no account/profile/bucket reference.
When a proposal is submitted for `decision_gate` evaluation, the caller
constructs a **decision-gate input envelope** that pairs the unmodified
proposal with account-aware evaluation context:

| Envelope field | Meaning | Owner |
| --- | --- | --- |
| `proposal` | The unmodified, market-only proposal object (Section 4). | `strategy` layer (unchanged by the envelope). |
| `strategy_profile_id` | Reference to the account-aware strategy profile (Joost's chosen allocation configuration) the proposal is being evaluated under. | `decision_gate` / account-aware configuration. |
| `account_scope_ref` | Reference to the account scope the proposal is being evaluated against, or an explicit account-agnostic marker if evaluation has not yet been scoped to an account. | `decision_gate` / account-aware configuration. |
| `bucket_id` | Reference to the allocation bucket the strategy leg would operate on (for example `SHORT_TACTICAL`), if evaluation proceeds. | `decision_gate` / account-aware configuration. |

The envelope is constructed at the `decision_gate` boundary, not by the
`strategy` layer and not carried inside the proposal object. This keeps the
proposal itself reusable across profiles/accounts and keeps `selection_engine`
and `strategy` strictly market-only and account-agnostic. `decision_gate`
evaluates the envelope (proposal + profile/bucket/account-scope context)
against live account state (Section 8).

## 4. Required proposal fields

Fields that belong to the proposal object:

| Field | Meaning |
| --- | --- |
| `proposal_id` | Unique proposal instance identifier. |
| `strategy_id` | Canonical `{ACTION}_{HORIZON}_{SETUP}` strategy identity. |
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

No account values are invented here. The proposal object carries no
profile, account-scope, or bucket reference at all — those are envelope-level
fields (Section 3a), attached only at `decision_gate` evaluation time, and
`decision_gate` alone owns evaluation of a bucket's percentage, current
allocation, or available capacity (Section 8).

### 4.1 Fields owned elsewhere

For clarity, fields that must **not** appear on the proposal object, and
where they actually belong:

| Field concept | Owner |
| --- | --- |
| `strategy_profile_id`, `account_scope_ref`, `bucket_id` | `decision_gate` input envelope (Section 3a) — attached at evaluation time, never carried by the proposal itself |
| Account balance, available cash, current position size, open orders | `decision_gate` (reads live account state; not carried on the proposal) |
| `bucket_target_pct`, `bucket_available_pct`, `bucket_current_pct` | `decision_gate` (evaluates the envelope's `bucket_id` against current configured/observed allocation) |
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
- the proposal itself carries **no** profile or bucket reference at all —
  `strategy_profile_id` and `bucket_id` exist only in the `decision_gate`
  input envelope (Section 3a), attached at evaluation time, never emitted by
  the `strategy` layer as part of the proposal object;
- `decision_gate` owns evaluation of the envelope (proposal plus
  profile/bucket/account-scope context) against actual account state and
  configured limits, including bucket percentages;
- `execution_planner` and `executor` must not reinterpret bucket policy.

Distinguish clearly between four different bucket-related numbers. None of
them are proposal fields — all four are owned by `decision_gate` and only
become relevant once a proposal is placed into an input envelope for
evaluation:

1. **target/configured bucket percentage** — part of the account-aware
   `strategy_profile_id` configuration, owned by `decision_gate`;
2. **observed/current account allocation** — live account state, owned by
   `decision_gate`;
3. **available allocation** — derived from (1) and (2), owned by
   `decision_gate`;
4. **proposed change** — implied by the proposal's `action`, evaluated by
   `decision_gate` against the `bucket_id` supplied in the input envelope;
   the magnitude/sizing of that change is decided by `decision_gate` and
   `execution_planner`, not carried as a percentage on the proposal.

The v2.14 backlog listed `bucket_target_pct`,
`bucket_available_pct`/`bucket_current_pct`, and a bucket/profile reference
as proposal fields. This contract does not carry that forward in any form:
neither the account-state percentages nor the profile/bucket reference
itself are owned by the proposal schema. The proposal carries no bucket or
profile field; `bucket_id` and `strategy_profile_id` are envelope-only
(Section 3a).

`BUY` and `SELL` legs inside the same bucket are not separate allocations
(for example, a `SELL_SHORT_SPIKE` proposal and a `BUY_SHORT_PULLBACK`
proposal both evaluated by `decision_gate` under an envelope referencing
`bucket_id = SHORT_TACTICAL` must not be summed by `decision_gate` into
double the bucket's target percentage).

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
- show evidence, freshness, lifecycle state, expiry, and the `strategy_id`
  a proposal carries; when a dashboard is explicitly account-aware and shows
  a proposal alongside its `decision_gate` evaluation, it may also show the
  `strategy_profile_id`/`bucket_id` from that evaluation's input envelope
  (Section 3a) — those remain envelope/decision_gate-owned values being
  displayed, not proposal fields;
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
