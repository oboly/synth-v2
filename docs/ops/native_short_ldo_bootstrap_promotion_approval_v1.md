# Native SHORT LDO bootstrap-promotion approval

## Status

APPROVED -- explicit, scope-specific human approval for exactly one
`PROMOTE_SCOPE` bootstrap authorization, following the same mechanism
already used for SOL, ETH, and XRP (`docs/ops/native_short_sol_bootstrap_promotion_approval_v1.md`,
`docs/ops/native_short_eth_bootstrap_promotion_approval_v1.md`,
`docs/ops/native_short_xrp_bootstrap_promotion_approval_v1.md`). This
approval is one of a reviewed, bounded batch of 16 independent approvals
(SUI, SHIB, PEPE, HBAR, AAVE, BNB, ICP, LDO, XPL, VET, ALGO, CC, HOT, FLOKI,
HNT, MOG) landed together in one repository change; each symbol in that
batch, including this one, has its own independent approval document and
its own independently digested manifest entry -- the batch is bounded and
attributable per scope, never a wildcard or a shared approval.

This record closes nothing by itself. It is the `approval_reference` named
by LDO's entry in
`src/market_data/native_short_promotion_bootstrap_manifest_v1.json` and is
the human decision that entry's `accepted: true` state represents. Closing
`BOOTSTRAP_ORCHESTRATION_BLOCKED` and `MULTI_SCOPE_FAILURE_ISOLATION_MISSING`
for the exact LDO scope below (the two blockers this manifest still narrows
-- `PROMOTION_CONTRACT_MISSING` is already closed globally, see
`docs/ops/native_short_sol_promotion_operational_acceptance_v1.md`) is
performed at runtime by
`native_short_scope_administration_transaction_v1.decide_administration`
consuming that entry -- see
`docs/todo/native_short_multi_asset_rollout_contract_v1.md` for the full
mechanism.

## Approval

The operator explicitly approved LDO as one of the next native SHORT
managed production canaries after SOL, ETH, and XRP, for exactly this scope
and no other:

```text
venue: bitvavo
symbol: LDO
quote_currency: EUR
fib_trading_horizon: SHORT
primary_interval: 4h
supporting_interval: 1h
```

This approval is limited to this exact scope. It does not approve SOL, ETH,
XRP, BTC (BTC is a separate, already-legacy scope handled by
`ADOPT_LEGACY_SCOPE`, not this bootstrap path), or any of the other 15
symbols in this same batch. Each of the other 15 is approved separately and
independently in its own `docs/ops/native_short_<symbol>_bootstrap_promotion_approval_v1.md`
document; no approval in this batch depends on or is weakened by any other,
and each is evaluated against its own independent manifest entry and digest.

## Approval basis

The operator identified LDO as one of 16 readiness-qualified, previously
unapproved native SHORT scopes based on the operator's own review of current
production state, and gave an explicit instruction naming exactly these 16
symbols (SUI, SHIB, PEPE, HBAR, AAVE, BNB, ICP, LDO, XPL, VET, ALGO, CC, HOT,
FLOKI, HNT, MOG) for this bounded batch. This repository change does not
itself re-run or independently re-verify `native_short_multi_asset_audit_v1`
against LDO; the eligibility determination and its "readiness-qualified"
classification were supplied by the operator, not re-derived, re-evaluated,
or expanded here, per the operator's explicit instruction that eligibility
review is out of scope for this change. The eligibility determination itself
is understood to be market-only and account-agnostic, not derived from
portfolio holdings or Profit Plan membership. A fresh, current
`native_short_multi_asset_audit_v1` run against LDO immediately before any
production `PROMOTE_SCOPE` execution (itself out of scope for this record)
remains the caller's own existing, unmodified responsibility.

## Approval-evidence binding

```text
approved_implementation_commit: 15fc4c030ced4ed2b5a8ba3dcbf831320fe541a8
```

That is the exact, already-existing, ordinary historical commit, on
`feature/native-short-multi-scope-rollout-v1`, that generalized the
bootstrap-evidence manifest from one hardcoded scope to a reviewed list of
independently evidenced entries -- referenced here as a plain historical
fact, not a value this entry's own tree must contain about itself (same
non-self-referential model as the existing SOL, ETH, and XRP approvals).

Two independent things are verified at every evaluation, neither of them a
same-commit self-reference:

- **approval-evidence digest** -- this entry's own `approval_evidence_digest`
  is a deterministic SHA-256 over `accepted`, the exact LDO scope,
  `approval_reference`, `approved_at_utc`, `approved_implementation_commit`,
  and the current SHA-256 of `native_short_promotion_bootstrap_evidence_v1.py`.
  It is recomputed fresh from those same fields (and a fresh read of that
  file) at every evaluation; any edit to this entry's fields or to the
  evidence module itself, without a matching digest update, fails closed
  (`MANIFEST_DIGEST_MISMATCH`). This entry's declared digest is
  `8b49b119138cf32e130bc8fc0db38cef36690ac1dc168511abe6f3167b21d451`.
- **ancestry, not equality** -- `approved_implementation_commit` must be an
  *ancestor* of the current deployed `HEAD` (`git merge-base
  --is-ancestor`), never required to equal it. Any commit created after
  `15fc4c03...`, on any branch descended from it, satisfies this by
  construction. Deployed-checkout identity itself (clean tree, exact `HEAD`
  known) remains entirely the unmodified job of
  `native_short_repository_source_identity_v1.verify_repository_commit_sha`
  and `src.operations.writer_capability_authorization_v1`, both already
  required before any write.

## Scope of this approval

Approved:

- exactly one `PROMOTE_SCOPE` invocation for the LDO scope above, executed
  through the existing `native_short_scope_administration_transaction_v1`
  owner with `native_short_4h_chain` writer authorization, from any clean
  checkout whose `HEAD` descends from
  `15fc4c030ced4ed2b5a8ba3dcbf831320fe541a8`, processed after SOL, ETH, and
  XRP, at LDO's own position in the documented sequential rollout order.

Not approved by this record:

- SOL, ETH, XRP, BTC, or any of the other 15 symbols in this batch;
- a second promotion of LDO after the first succeeds (structurally
  impossible via this same bootstrap path once LDO's scope row exists --
  see `native_short_promotion_bootstrap_evidence_v1.py`);
- `REMOVE_SCOPE` for LDO or any other scope (`REMOVAL_CONTRACT_MISSING`
  remains fully, unconditionally active for `REMOVE_SCOPE` and unaffected
  by this record);
- map materialization, snapshot publication, Profit Plan rendering, or any
  wallet/account-aware action;
- any change to `run_chain_4h.sh`, systemd units, timers, or the 4h chain's
  scheduling;
- production execution of any `PROMOTE_SCOPE` -- this record and the
  repository change it authorizes are approval preparation only; no
  production promotion is performed as part of landing this record.

## Safety markers

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
new_scope_seeds=0
```

No database write, map materialization, snapshot publication, or Profit
Plan render occurred as part of recording this approval.
