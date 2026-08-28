# SELL LIVE activation controller v1 (Issue #551, Phase 1)

## Ownership

`src/ops/sell_live_activation_controller_v1.py` is a read-only orchestration
and reporting layer. It owns no permission, credential, kill-switch,
planner, or executor semantics of its own. It only reads the existing,
already-reviewed canonical contracts built for Issue #392 phases 1-6 and
Issue #413/#206, and reports their current state in one structured,
machine-readable run:

| Read-only check | Canonical module/table it reads |
| --- | --- |
| Repository/deployment SHA | `git rev-parse HEAD`; optional `--expected-deployed-sha` comparison |
| Account identity | `trading_account` table (`account_mode`, `enabled`, `live_trading_enabled`, `venue`) |
| Production schema | `SHOW TABLES` presence check against the canonical #392/#206/#413 migration set |
| TRADE_EXECUTION credential binding | `src/executor/execution_credential_scope_v1.py::ExecutorCredentialScopeRepository` |
| decision_gate LIVE permission (Gate 1) | `src/decision_gate/automatic_exit_live_permission_repository_v1.py` + `automatic_exit_live_permission_contract_v1.py` |
| Global kill switch | `src/executor/execution_kill_switch_v1.py::ExecutionKillSwitchRepositoryV1` |
| Runtime/service ownership | `deploy/ownership/account_runtime_capability_ownership_v1.json` |
| Exact-path acceptance (DRY_RUN/PAPER) | `src/execution_planner/automatic_exit_execution_handoff_adapter_v1.py` + `automatic_exit_execution_handoff_application_v1.py`, exercised against a synthetic in-memory fixture |
| Idempotency/restart readiness | `derive_automatic_exit_plan_reference_id_v1` determinism, checked inside `DRY_RUN_ACCEPTANCE` |
| Bounded SELL canary feasibility | new, controller-owned `SellLiveCanaryContractPreviewV1` (see below) |

It does not read or resolve executor operational LIVE authority
(`src/executor/execution_live_authority_v1.py`, Gate 2's authority half) --
that grant is scoped to an exact
account/venue/side/market/executor_identity/runtime_owner tuple with a
maximum 7-day window and is meant to be provisioned by an operator
immediately before a real activation decision, not resolved speculatively by
a readiness controller. The kill switch (Gate 2's other half) is checked
directly because it is a single global switch with a meaningful idle state.

## Phase contract

Deterministic, fixed order, never reordered at runtime:

```text
PRECHECK
PRODUCTION_SCHEMA_READY
CREDENTIAL_BINDING_READY
LIVE_PERMISSION_READY
KILL_SWITCH_READY
RUNTIME_READY
DRY_RUN_ACCEPTANCE
PAPER_ACCEPTANCE
CANARY_READY
LIVE_AUTHORIZATION_REQUIRED
```

`PRECHECK`'s account_mode / `live_trading_enabled` consistency check and
execution-eligibility check are not special-cased in this controller; both
are shared from the canonical `src.account.account_mode_contract_v1` model
(`docs/architecture/account_mode_contract_v1.md`) also used by
`automatic_exit_gate_v1`, `automatic_buy_gate_v1`, and both execution-handoff
mode resolvers. A `trading_account` row with `account_mode="live_readonly"`
(real broker, read-only, never execution-eligible) blocks `PRECHECK` with
`ACCOUNT_MODE_NOT_EXECUTION_ELIGIBLE`, distinct from
`ACCOUNT_MODE_EVIDENCE_INCONSISTENT` (which means the account_mode /
live_trading_enabled pairing itself is invalid, not merely
execution-ineligible).

Phase 1 **never advances past `LIVE_AUTHORIZATION_REQUIRED`**. There is no
flag, mode, or code path in this module that submits an order, mutates the
kill switch, provisions a credential, grants LIVE authority, applies a
migration, or enables a service/timer.

All nine gated phases (`PRECHECK` through `CANARY_READY`) are evaluated
unconditionally in every run -- each is independently read-only, so nothing
is unsafe about evaluating all of them and reporting every blocker in one
pass, rather than stopping at the first failure. `LIVE_AUTHORIZATION_REQUIRED`
is only evaluated (and only ever `PASSED`) when every gated phase passed; if
any gated phase is `BLOCKED`, `LIVE_AUTHORIZATION_REQUIRED` is reported as
`NOT_EVALUATED` and the run's `terminal_state` is `BLOCKED`.

## Fail-closed semantics

- Any DB connection failure, missing table, missing binding, absent/expired/
  revoked/ambiguous LIVE permission, missing/ambiguous kill-switch state, or
  inactive runtime capability blocks that phase. No "best effort" promotion
  to ready exists anywhere in this module.
- The kill-switch check is deliberately **stricter** than
  `execution_kill_switch_v1.is_engaged()`'s own default: the runtime module
  treats "no event ever recorded" as clear-by-default (a correct behavior
  for a runtime that must remain deny-by-default at the *authority* layer
  regardless). This readiness controller instead treats total absence of
  kill-switch history as `KILL_SWITCH_STATE_UNKNOWN` and blocks -- a
  first-LIVE-canary readiness check must not accept "we never explicitly
  looked" as equivalent to an explicit, reviewed `DISENGAGED` decision. This
  is a deliberate controller-local policy layered on top of the canonical
  contract, not a change to that contract.
- Kill-switch event *freshness* is reported only as an advisory warning
  (`KILL_SWITCH_DISENGAGED_EVENT_AGE_ADVISORY`), never a blocker, because the
  canonical kill-switch contract defines no staleness threshold for a valid
  `DISENGAGED` event -- inventing a hard staleness gate not owned by that
  contract would be scope creep this issue does not authorize.
- No exception message is ever included verbatim in the artifact or logs;
  only the exception's Python class name and, when it matches the
  repository's existing fixed-uppercase-reason-code style, that code. This
  keeps out any accidental leakage of connection parameters or other
  incidental exception text.

## Exact-path acceptance boundary

`DRY_RUN_ACCEPTANCE` and `PAPER_ACCEPTANCE` build a synthetic, clearly
non-production `AutomaticExitCandidateV1` -> `AutomaticExitGateDecisionV1` ->
`AutomaticExitPlanV1` fixture (same shape already proven by
`tests/test_automatic_exit_execution_handoff_adapter_v1.py`), adapt it
through `adapt_automatic_exit_plan_to_approved_execution_plan_v1`, and (for
PAPER) resolve the executor mode through
`resolve_automatic_exit_executor_mode_v1`. They deliberately **stop before**
`ExecutionHandoffRepositoryV1.intake()` / `.intake_live_authorized()` --
calling either performs a real DB insert, and Phase 1 categorically forbids
any DB write, including a DRY_RUN/PAPER one, from this controller. This is a
narrower proof than the full repository-level acceptance already completed
and documented in
`docs/status/issue_392_phase6_sell_live_readiness_v1.md` (2026-08-19 update);
it is sufficient for Phase 1 because it proves the code path is wired and
deterministic without requiring a live, mutable database.

## Canary contract preview (Section J)

`SellLiveCanaryContractPreviewV1` is a new, controller-owned, preview-only
dataclass. It is **not** a reuse of
`src/executor/live_canary_bounds_v1.py::LiveCanaryBoundsV1`: that module is
hard-coded `BUY`-only by explicit, already-reviewed design
(`CANARY_ALLOWED_SIDE = "BUY"`), and this issue requires
`allowed_side=SELL`. Weakening that invariant to accept SELL would be an
unreviewed change to a safety-load-bearing BUY canary contract; a parallel,
equally-narrow SELL-only preview avoids touching it at all.

Constructing this preview activates nothing. It is never persisted as an
authority grant, never consulted by `execution_live_authority_v1` or the
executor, and exists purely so a reviewer can see the exact bounded shape a
first SELL canary activation would take, once a human separately authorizes
it: `trading_account_id`, `venue`, `allowed_side="SELL"`, `allowed_market`,
`max_orders_per_cycle`, `max_notional_eur`, `kill_switch_required=True`
(cannot be constructed otherwise), and `deployed_sha`.

## Artifact contract

Schema: `sell_live_readiness_v1`. Every run produces exactly one JSON
object with:

```text
schema_version, generated_at_utc, repository_sha, deployed_sha,
trading_account_id, venue, phase_results, blockers, warnings,
canary_contract_preview, terminal_state
```

`terminal_state` is exactly one of `BLOCKED`, `CANARY_READY`, or
`LIVE_AUTHORIZATION_REQUIRED`. A fully-ready Phase-1 run always terminates at
`LIVE_AUTHORIZATION_REQUIRED`, never further. `CANARY_READY` is reserved in
the schema for a possible future narrower invocation that intentionally
stops before emitting the authorization-required marker; Phase 1's `main()`
entrypoint always evaluates the full phase list and never emits it as a
terminal value today.

## Evidence path

The artifact is written to `data/ops/sell_live_readiness_v1.json` by
default. No canonical committed ops-evidence directory exists in this
repository (`docs/ops/` holds only permanent narrative documentation; no
prior generated JSON evidence file is committed there or anywhere else). Per
`AGENTS.md`'s Non-Goals section ("do not add generated artifacts to git"),
`data/ops/` is added to `.gitignore` in this change -- it is the canonical
runtime evidence path but is deliberately never a committed record. An
operator who wants to keep a specific run's evidence for audit should copy
it into a reviewed location explicitly (e.g. attach it to the GitHub Issue
or a PR description), not rely on git history of this path.

## Observability

Structured JSON events on stdout: `STARTED`, `PHASE_STARTED`,
`PHASE_PASSED`/`PHASE_BLOCKED` per phase, and exactly one `FINISHED` event
per run. No secret material appears in any event or in the artifact.

## Production check command

```bash
python -m src.ops.sell_live_activation_controller_v1 \
  --check \
  --trading-account-id <id> \
  --venue bitvavo \
  --executor-identity manual_execution_bitvavo_v1 \
  --runtime-owner odroid \
  --canary-market <MARKET> \
  --canary-max-orders-per-cycle 1 \
  --canary-max-notional-eur 25 \
  --expected-deployed-sha <sha-if-known>
```

`--check` is required; there is no other supported mode in Phase 1. Exit
code is `0` when `terminal_state != BLOCKED`, `1` otherwise.

## Explicit LIVE authorization boundary

An `LIVE_AUTHORIZATION_REQUIRED` terminal result means every Phase 1
read-only check passed. It does **not** mean LIVE trading is authorized. A
separate, explicit, human decision is still required, and this controller
performs none of it:

1. An operator with real production DB/credential/systemd access re-runs
   this controller against production and confirms every phase is
   independently `PASSED` at that time (state can change between this run
   and activation).
2. An operator explicitly provisions
   `execution_live_authority_v1.ExecutionLiveAuthorityRepositoryV1.grant(...)`
   scoped to exactly the account/venue/side/market/executor_identity/
   runtime_owner in the reviewed `canary_contract_preview`, with the
   shortest practical effective window.
3. An operator confirms the kill switch is `DISENGAGED` immediately before
   activation (not merely at controller-run time).
4. Only then does a real SELL candidate reaching an `APPROVED` LIVE
   decision-gate result have any path to an actual order -- and only through
   the unmodified, already-reviewed `#392` -> `#206` handoff and `#413`
   authority/kill-switch chain this controller never bypasses.

Building the actual activation/execution step (a Phase 2 controller command
that would ever call `.intake_live_authorized()` or provision authority) is
explicitly out of scope for this issue and is not implemented here.
