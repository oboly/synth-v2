# Account protection contract V1

## Status

Issue [#227 — Design account-aware drawdown, loss, and cooldown protection
contract](https://github.com/oboly/synth-v2/issues/227), P1 scope: contract
design only. This document and
`src/decision_gate/account_protection_contract_v1.py` are the accepted
artifacts for that scope.

Runtime implementation belongs to the separately gated Issue
[#318 — Implement P2 minimal account-protection runtime inside
decision_gate](https://github.com/oboly/synth-v2/issues/318). P2 supplies
typed pre-derived account-risk facts, append-only lifecycle persistence, and
decision-gate composition. It grants no broker, executor, planner, or live
activation authority.

Historical design context: `docs/todo/decision_gate_account_protections_v1.md`
(candidate `NEW-10`, frozen legacy/reference file; this document and Issue
#227 are the live spec).

Issue #392 Phase 6 blocker C wires this P2 boundary into the real
automatic-exit runtime (see "Real #392 wiring" below) and adds a durable
account-scoped policy-configuration contract. No metric-fact producer for
`MAX_ACCOUNT_DRAWDOWN` / `DAILY_REALIZED_LOSS` / `REPEATED_STOPLOSS_STREAK`
exists yet; see `docs/status/issue_392_phase6_sell_live_readiness_v1.md` for
current Phase 6 readiness state. No LIVE trading, executor, or broker
authority is granted by this wiring.

## Why `docs/architecture/`

This is a permanent, versioned system contract describing a `decision_gate`
subsystem's inputs, outputs, and invariants — the same category as
`docs/architecture/automatic_exit_policy_v1.md`, which documents the sibling
`exit_policy` -> `decision_gate` -> `execution_planner` contract chain. It is
not an operational runbook (`docs/ops/`) and not raw research
(`docs/research/`), so `docs/architecture/` is the correct canonical home,
matching the Issue #392 Phase 4A delivery precedent.

## Boundary

`decision_gate` is the sole owner of account-aware protection locks.

```text
selection_engine        = unchanged, market-only, no protection awareness
sector rotation          = unchanged, market-only
decision_gate            = account-aware protection owner (this contract)
execution_planner        = unchanged
executor                 = unchanged
broker_private_calls     = 0
broker_writes            = 0
order_submission         = 0
live_orders               = 0
runtime_activation        = 0
```

A protection may only reduce or block permission. It can never raise market
rank, create a candidate, force an entry or exit, size an order, or submit an
order. `selection_engine` and `trade_setup_filter` must not import this
module or hold any protection state — they remain market-only and
account-agnostic.

## What this module is (and is not)

`src/decision_gate/account_protection_contract_v1.py` is a pure,
schema/contract-only module:

- typed, versioned dataclasses for the lock fact and the evaluation outcome;
- a pure resolver, `resolve_account_protection_state_v1`, that composes
  caller-assembled `ProtectionLockFactV1` rows into one permission signal;
- lifecycle and immutable event-identity helpers for deterministic
  restart/audit semantics.

It has no database, broker, credential, scheduler, execution_planner, or
executor import, and it does not compute drawdown, daily realized loss, or a
stop-loss streak from raw account data. That derivation — reading the
point-in-time equity curve, realized-PnL ledger, and stoploss/fill history
and turning them into `ProtectionLockFactV1` rows — is P2/Issue #318's
runtime responsibility. This mirrors
`src/exit_policy/automatic_exit_runtime_contract_v1.py` (Phase 4A): pure
resolution over caller-supplied facts, not live evaluation.

## Protection codes and scope

```text
MAX_ACCOUNT_DRAWDOWN_BLOCK      scope: ACCOUNT
DAILY_REALIZED_LOSS_BLOCK       scope: ACCOUNT
REPEATED_STOPLOSS_BLOCK         scope: ACCOUNT | ASSET
LOW_PROFIT_ASSET_COOLDOWN       scope: ASSET
POST_CLOSE_REENTRY_COOLDOWN     scope: ASSET
MANUAL_ACCOUNT_LOCK             scope: ACCOUNT | SLEEVE | ASSET (V1 compatibility)
```

Scope types are `ACCOUNT`, `SLEEVE`, `ASSET`, matching
`docs/todo/decision_gate_account_protections_v1.md`'s "Required lock
contract". `PROTECTION_ALLOWED_SCOPES` in the module enforces the legal
`(protection_code, scope_type)` pairs; a mismatched pairing is a contract
violation (`AccountProtectionContractError`), not a runtime data-quality
issue, and fails loudly rather than silently evaluating.

`MANUAL_ACCOUNT_LOCK` is included even though Issue #227's summary lists five
capabilities (drawdown, daily loss, stop streak, cooldown, expiry/recovery),
because the source TODO's lock contract explicitly requires "explicit manual
lock/unlock authority" as part of the same P1 design, and manual authority
needs a protection code to participate in precedence like any other lock.
P2 administrative manual-lock producers emit `ACCOUNT` scope only. The
historical narrower V1 scopes remain valid for backward-compatible replay;
they do not create a global lock.

## Action applicability

Protection evaluation is always for one explicit decision-gate permission
action:

```text
BUY     increases or adds market exposure
REDUCE  decreases a held position without fully closing it
EXIT    fully closes a held position
```

These are permission semantics only. `decision_gate` does not calculate
quantity, ladders, or orders. The action matrix is canonical in
`PROTECTION_BLOCKED_ACTIONS` in
`src/decision_gate/account_protection_contract_v1.py`; it is contract
configuration, not duplicated onto persisted lock facts.

```text
protection                         BUY       REDUCE    EXIT
MAX_ACCOUNT_DRAWDOWN_BLOCK         BLOCK     ALLOW     ALLOW
DAILY_REALIZED_LOSS_BLOCK          BLOCK     ALLOW     ALLOW
REPEATED_STOPLOSS_BLOCK            BLOCK     ALLOW     ALLOW
LOW_PROFIT_ASSET_COOLDOWN          BLOCK     ALLOW     ALLOW
POST_CLOSE_REENTRY_COOLDOWN        BLOCK     ALLOW     ALLOW
MANUAL_ACCOUNT_LOCK                BLOCK     BLOCK     BLOCK
```

The first five protections are risk-increase protections. They must not trap
an existing position by denying a risk-reducing `REDUCE` or `EXIT`.
`MANUAL_ACCOUNT_LOCK` is explicit administrative trading authority and blocks
all three actions. It is not an executor/runtime kill switch: shared
execution kill authority remains owned by Issue #206.

## Typed inputs and outputs

`ProtectionLockFactV1` is the immutable, append-only fact:

```text
lifecycle_id               stable lifecycle/correlation identity; shared by
                           every event in one protection lifecycle
event_id                   immutable event/row identity; unique for every
                           append-only lifecycle transition
protection_code            one of the six codes above
protection_version         "1" (LOCK_FACT_CONTRACT_VERSION)
trading_account_id         int, > 0
scope_type                 ACCOUNT | SLEEVE | ASSET
scope_id                   str; ACCOUNT -> str(trading_account_id),
                            SLEEVE -> sleeve_code, ASSET -> str(asset_id)
observed_from_ts_utc       tz-aware UTC, start of the observation window
observed_to_ts_utc         tz-aware UTC, > observed_from_ts_utc
triggered_ts_utc           tz-aware UTC, when this fact became authoritative
expires_ts_utc             tz-aware UTC or None (no natural expiry); if set,
                            must be > triggered_ts_utc
reason_code                free-text evidence reason (human-readable)
evidence_refs              tuple[str, ...] of evidence pointers
configuration_version      str, versions the threshold/window configuration
lock_state                 ACTIVE | EXPIRED | RECOVERED | MANUALLY_CLEARED
```

`lock_state` is the persisted-fact lifecycle vocabulary and is intentionally
distinct from the evaluation `decision_state` vocabulary below — a
`ProtectionLockFactV1` with `lock_state=ACTIVE` is a candidate to block, but
whether it currently blocks also depends on its trigger/expiry window versus
the evaluation instant.

`AccountProtectionEvaluationV1` is the pure evaluation outcome:

```text
evaluation_contract_version   "1"
decision_state                PERMITTED | BLOCKED   (no third neutral state)
reason_code                   OK, or a *_TRIGGERED / *_ACTIVE /
                               ACCOUNT_STATE_EVIDENCE_* code
trading_account_id
protection_code               winning protection, or None when PERMITTED
scope_type / scope_id         winning lock's scope, or None when PERMITTED
expires_ts_utc                winning lock's expiry, or None
contributing_lock_facts        all currently in-force matching locks
                               (evidence trail; not only the winner)
evaluated_ts_utc
```

## Reason codes

```text
OK
MAX_ACCOUNT_DRAWDOWN_TRIGGERED
DAILY_REALIZED_LOSS_TRIGGERED
REPEATED_STOPLOSS_TRIGGERED
LOW_PROFIT_ASSET_COOLDOWN_ACTIVE
POST_CLOSE_REENTRY_COOLDOWN_ACTIVE
MANUAL_ACCOUNT_LOCK_ACTIVE
ACCOUNT_STATE_EVIDENCE_STALE
ACCOUNT_STATE_EVIDENCE_MISSING
```

Malformed caller input (bad account id, invalid fact shape, cross-account
fact leakage, naive timestamps) raises `AccountProtectionContractError`
rather than returning a reason code — that is a caller/integration bug, not
routine account-data uncertainty.

## Precedence

When more than one lock is simultaneously in force for a lookup, the
resolver returns exactly one winner (the surfaced `protection_code` /
`reason_code`) but preserves every in-force lock in
`contributing_lock_facts` so no evidence is lost for audit/reporting.
Precedence, highest first:

```text
1. MANUAL_ACCOUNT_LOCK        human operator authority always dominates
2. MAX_ACCOUNT_DRAWDOWN_BLOCK  hardest automated capital-preservation cap
3. DAILY_REALIZED_LOSS_BLOCK   second account-level circuit breaker
4. REPEATED_STOPLOSS_BLOCK     systematic pattern signal, narrower impact
5. POST_CLOSE_REENTRY_COOLDOWN temporary, asset-scoped
6. LOW_PROFIT_ASSET_COOLDOWN   temporary, asset-scoped, least severe
```

For final permission, precedence applies only after filtering active,
in-scope locks to the protections that block the requested action. Thus a
drawdown lock and cooldown do not block `EXIT`, while a simultaneous manual
lock does.

## Freshness and fail-closed behavior

The resolver takes an explicit `account_state_observed_ts_utc`,
`account_state_fresh` flag, and `max_account_state_age_seconds` (default 15
minutes, matching the automatic-exit contract's default). If
`account_state_fresh` is `False`, or the observed timestamp is stale or in
the future relative to the evaluation instant `at`, the result is always
`BLOCKED` with `ACCOUNT_STATE_EVIDENCE_MISSING` or
`ACCOUNT_STATE_EVIDENCE_STALE` — never `PERMITTED`. This is enforced before
any lock facts are considered, so uncertain, stale, or missing account state
blocks unconditionally rather than silently permitting.

On the real #392 path this flag/timestamp is populated from the same
`account_state_snapshot_run_v1`-derived bundle the automatic-exit runtime
already loaded for the candidate/gate evaluation (see "Real #392 wiring"
below) — never a second snapshot query and never an implicit `True`.

## Account isolation

Every `ProtectionLockFactV1` carries an explicit `trading_account_id`. The
resolver raises `AccountProtectionContractError("CROSS_ACCOUNT_EVIDENCE_LEAKAGE")`
if any fact in the caller-supplied iterable belongs to a different account
than the one being evaluated — it never silently filters foreign-account
facts, because silently dropping them could mask an upstream query bug that
already leaked cross-account data into the process. Scope matching within one
account (`ACCOUNT` vs `SLEEVE` vs `ASSET`) further restricts which locks can
apply to a given lookup: an `ASSET`-scoped lock for asset 99 never affects an
evaluation for asset 42, and a `SLEEVE`-scoped lock only applies when the
caller's `sleeve_code` matches.

## Deterministic restart semantics

Lock history is strictly append-only. `ACTIVE`, `RECOVERED`, `EXPIRED`, and
`MANUALLY_CLEARED` are separate immutable facts/events. A recovery, expiry,
or clear must append a new fact with the stable `lifecycle_id` of the prior
active lifecycle and a distinct `event_id`; it must never update, upsert, or
otherwise mutate the historical `ACTIVE` fact.

`account_protection_lock_lifecycle_id_v1` hashes stable correlation fields
(protection code/version, account, scope, observation window, configuration
version). It deliberately is not a row key. For each transition,
`account_protection_lock_event_id_v1` derives a separate immutable event key
from that lifecycle identity, `lock_state`, and `triggered_ts_utc`. A future
P2 persistence writer must insert each event exactly once and must reject a
duplicate event identity rather than treating it as permission to mutate a
prior event.

The resolver deterministically collapses complete immutable event history to
the latest authoritative event per `lifecycle_id` before evaluating. Distinct
events for one lifecycle at the same authoritative timestamp are ambiguous
and rejected fail-closed rather than arbitrarily ordered. A process restart that
reloads the same history reconstructs identical state regardless of input
order. Nothing is held in memory between evaluations — the resolver is pure
and stateless.

## Composition with existing `decision_gate` permission evaluation

This contract is an **additional required check**, not a replacement for
`decision_gate.decision_gate_v1.evaluate_selection_for_account`. A future P2
runtime must combine both with a logical AND: execution intent may proceed
only if the existing selection/sleeve/balance/duplicate evaluation allows it
**and** `resolve_account_protection_state_for_action_v1` returns
`STATE_PERMITTED`. A
`BLOCKED` protection result always overrides an otherwise-allowed selection
decision; the existing evaluation is never given authority to override an
active protection lock. P2 callers must supply `requested_action`; the
original `resolve_account_protection_state_v1` remains a compatibility surface
for generic lock-state composition only, not final action permission.
Unsupported actions are rejected fail-closed as caller contract errors.
Account-state freshness is required only when the configured protection
requires current account-state evidence; persisted manual locks and cooldowns
do not require unrelated balance/position evidence.

## P2 runtime, fact ownership, and reporting

Issue #318 implements the pure P2 boundary in
`src/decision_gate/account_protection_runtime_v1.py`:

```text
canonical/pre-derived account-risk metric
-> typed protection trigger fact
-> action-aware #227 resolver
-> existing decision_gate permission AND protection permission
```

The runtime accepts typed pre-derived drawdown, daily-realized-loss, and
stoploss-streak metrics with their observation window and provenance. It does
not create a second balance, realized-PnL, position, fill, or equity ledger.
`account_state_snapshot_run_v1` remains the reusable source for current
account-state freshness only. A configured metric missing, malformed, stale,
or contradictory evidence fails closed; facts for an unconfigured protection
are not required.

Manual locks and cooldown lifecycle facts are durable in the migration-only
append-only `account_protection_lock_fact_v1` table. An unlock/recovery is a
new `MANUALLY_CLEARED`, `RECOVERED`, or `EXPIRED` event with the same lifecycle
identity, never deletion or update. The reader loads complete account-scoped
history, so restart replays the same immutable events and cannot clear or
duplicate an active lock. The action matrix is not persisted per row.

Decision results retain protection state/reason/code as read-only audit and
reporting evidence. Reporting has no create, unlock, expiry, broker, planner,
or executor authority. Automatic-exit candidates provide `REDUCE` or `EXIT`
to the same action-aware evaluator before their existing gate composition;
`exit_policy`, `execution_planner`, and `executor` do not inspect protection
internals.

### Real #392 wiring (Issue #392 Phase 6 blocker C)

`src/decision_gate/account_protection_evaluation_v1.py` is the single
composition seam that wires the real automatic-exit runtime to this P2
boundary. `src/exit_policy/automatic_exit_runtime_orchestrator_v1.py` calls
`evaluate_account_protection_for_automatic_exit_v1` for every candidate
before building `AutomaticExitGateContextV1`, and always supplies its
`AccountProtectionEvaluationV1` result to
`AutomaticExitGateContextV1.account_protection_evaluation` — the field never
stays `None` on the real path anymore. `requested_action` is mapped directly
from `candidate.candidate_action` (`REDUCE`/`EXIT`); `sleeve_code` is always
`None`, matching the automatic-exit domain's lack of a sleeve concept.
`account_state_fresh` is computed explicitly from the same aligned
`account_state_snapshot_run_v1`-derived timestamp the automatic-exit runtime
already loaded (`item.account_state_observed_ts_utc`) against a 15-minute
default bound — never an implicit `True`.

Durable, account-scoped configuration (`AccountProtectionPolicyV1` thresholds)
now has a canonical persistence contract:
`src/decision_gate/account_protection_policy_contract_v1.py` (pure,
versioned resolver) and
`src/decision_gate/account_protection_policy_repository_v1.py` (DB reads),
backed by the append-only `account_protection_policy_config_v1` table
(migration artifact only: `db/migrations/20260817_account_protection_policy_config_v1.sql`,
not applied). No effective row for the account, more than one simultaneously
effective row, or an unsupported `config_version` all resolve to
`AccountProtectionPolicyConfigError` and the composition seam converts that
to a typed `BLOCKED` evaluation (`PROTECTION_CONFIGURATION_UNRESOLVED`) —
**an account with no protection policy row cannot reach an `APPROVED`
automatic-exit gate decision.** Provisioning at least a permissive
(all-thresholds-`None`) config row is therefore an operational prerequisite
before any account's automatic-exit candidates can stage a plan again.

`account_protection_policy_config_v1` rows are permanently immutable: both
the `UPDATE` and `DELETE` triggers reject unconditionally, with no exception
for closing an open-ended (`effective_until_ts_utc IS NULL`) row. Ending or
superseding a config is expressed exclusively through an immutable fact in
the companion `account_protection_policy_config_revocation_v1` table (config
id, denormalized `trading_account_id`, `revocation_version`,
`effective_ts_utc`, `actor`, `reason`) — itself `UPDATE`/`DELETE`-rejecting.
`resolve_account_protection_policy_v1` now takes both the config rows and
the revocation facts: a config row counts as revoked at evaluation time `T`
if *any* of its revocation facts has `effective_ts_utc <= T`. Multiple
revocation facts per config row are valid by design — a revocation scheduled
for the future must never block a second, immediate revocation from also
being recorded and taking effect right away. Malformed revocations (dangling
config reference, effective timestamp at/before the referenced config's own
`effective_from_ts_utc`, empty `actor`/`reason`) and cross-account corruption
(a revocation's own `trading_account_id` disagreeing with its referenced
config row's account) both fail closed, as does an unsupported
`revocation_version`. Superseding a config is therefore, in one transaction:
`INSERT` a revocation fact for the old row (`effective_ts_utc` = the new
row's `effective_from_ts_utc`), then `INSERT` the new config row — never an
`UPDATE` to the old row. `tests/test_account_protection_policy_config_mariadb_ddl_v1.py`
proves this end-to-end against a disposable MariaDB schema, including that
config/revocation rows reject every update and delete shape and that a
config with an already-scheduled future revocation still accepts a second,
immediate one.

`AccountProtectionPolicyConfigRowV1.source_provenance` (who/what provisioned
the row) is loaded by the repository and validated non-empty by the resolver
on the winning row — it is operational audit trail only and is never used as
threshold semantics.

`MAX_ACCOUNT_DRAWDOWN`, `DAILY_REALIZED_LOSS`, and `REPEATED_STOPLOSS_STREAK`
still have **no canonical metric-fact producer**: the composition seam always
supplies an empty `metric_facts` tuple. If a future durable config ever
enables one of those thresholds without a producer wired into the seam, the
existing P2 evaluator fails closed on its own
(`REQUIRED_PROTECTION_METRIC_MISSING`) rather than the seam inventing a
value; this remains a real, tracked blocker, not silently worked around.
Persisted `MANUAL_ACCOUNT_LOCK` and cooldown facts (and, if a future producer
appends a metric-derived lock directly, `MAX_ACCOUNT_DRAWDOWN_BLOCK` /
`DAILY_REALIZED_LOSS_BLOCK` / `REPEATED_STOPLOSS_BLOCK` rows) already flow
correctly end-to-end today through
`account_protection_repository_v1.load_protection_lock_facts_for_account_v1`.

`exit_policy` and `execution_planner` still do not embed protection logic;
`automatic_exit_runtime_orchestrator_v1` only calls the seam and forwards its
typed result. The append-only `automatic_exit_evaluation_audit_v1` table
gained two nullable provenance columns, `protection_code` and
`protection_reason_code`, populated from the gate decision on every write
(including permitted evaluations, where they record `NULL`/`OK`) — audit/
review evidence only, never an executor input or protection configuration
source.

## Non-goals

- No Freqtrade code copy or dependency.
- No ad hoc derivation of drawdown/realized-loss/streak values from raw
  account data; a canonical producer must supply the typed pre-derived metric.
- No market-regime classification or `selection_engine` change.
- No automatic sell or liquidation path.
- No dashboard-owned risk logic or unlock authority.
- No live trading activation.
