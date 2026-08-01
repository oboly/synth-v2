# Native SHORT SOL bootstrap-promotion approval

## Status

APPROVED — explicit, scope-specific human approval for exactly one
first-canary `PROMOTE_SCOPE` bootstrap authorization.

This record closes nothing by itself. It is the `approval_reference`
named by `src/market_data/native_short_promotion_bootstrap_manifest_v1.json`
and is the human decision that manifest's `accepted: true` state represents.
Closing `PROMOTION_CONTRACT_MISSING`, `BOOTSTRAP_ORCHESTRATION_BLOCKED`, and
`MULTI_SCOPE_FAILURE_ISOLATION_MISSING` for the exact SOL scope below is
performed at runtime by
`native_short_scope_administration_transaction_v1.decide_administration`
consuming that manifest -- see
`docs/todo/native_short_multi_asset_rollout_contract_v1.md` for the full
mechanism.

## Approval

The operator explicitly approved SOL as the first native SHORT managed
production canary, for exactly this scope and no other:

```text
venue: bitvavo
symbol: SOL
quote_currency: EUR
fib_trading_horizon: SHORT
primary_interval: 4h
supporting_interval: 1h
```

This approval is limited to this exact scope. It does not approve ETH,
XRP, BTC (BTC is a separate, already-legacy scope handled by
`ADOPT_LEGACY_SCOPE`, not this bootstrap path), or any broader rollout.

## Approval-evidence binding (corrected)

**Superseded note:** an earlier version of this section required the
manifest's `repository_commit_sha` to exactly equal deployed `HEAD`,
requiring "one additional, mechanical, reviewed follow-up commit" before
any checkout could match. That design was unsound (a git commit cannot
state its own hash inside its own tree) and is replaced by the model
below; no follow-up pin commit exists or is needed.

```text
approved_implementation_commit: a74ff33121d42a7771eef0654e1526847d5c5d12
```

That is the exact, already-existing, ordinary historical commit, on
`fix/native-short-production-promotion-bootstrap-v1`, that introduced this
approval and the reviewed bootstrap mechanism it trusts -- referenced here
as a plain historical fact, not a value the manifest's own tree must
contain about itself (exactly like the existing
`38346fc1460453469ca5bd3bc2f45159f0dc303e` reference in
`docs/todo/native_short_multi_asset_rollout_contract_v1.md`).

Two independent things are verified at every evaluation, neither of them a
same-commit self-reference:

- **approval-evidence digest** -- `approval_evidence_digest` in the
  manifest is a deterministic SHA-256 over `accepted`, the exact SOL
  scope, `approval_reference`, `approved_at_utc`,
  `approved_implementation_commit`, and the current SHA-256 of
  `native_short_promotion_bootstrap_evidence_v1.py`. It is recomputed
  fresh from those same fields (and a fresh read of that file) at every
  evaluation; any edit to a manifest field or to the evidence module
  itself, without a matching digest update, fails closed
  (`MANIFEST_DIGEST_MISMATCH`).
- **ancestry, not equality** -- `approved_implementation_commit` must be an
  *ancestor* of the current deployed `HEAD` (`git merge-base
  --is-ancestor`), never required to equal it. Any commit created after
  `a74ff33...`, on any branch descended from it, satisfies this by
  construction. Deployed-checkout identity itself (clean tree, exact
  `HEAD` known) remains entirely the unmodified job of
  `native_short_repository_source_identity_v1.verify_repository_commit_sha`
  and `src.operations.writer_capability_authorization_v1`, both already
  required before any write.

## Scope of this approval

Approved:

- exactly one `PROMOTE_SCOPE` invocation for the SOL scope above, executed
  through the existing `native_short_scope_administration_transaction_v1`
  owner with `native_short_4h_chain` writer authorization, from any clean
  checkout whose `HEAD` descends from `a74ff33121d42a7771eef0654e1526847d5c5d12`.

Not approved by this record:

- ETH, XRP, or any other symbol;
- a second promotion of SOL after the first succeeds (structurally
  impossible via this same bootstrap path once SOL's scope row exists --
  see `native_short_promotion_bootstrap_evidence_v1.py`);
- `REMOVE_SCOPE` for SOL or any other scope (`REMOVAL_CONTRACT_MISSING`
  remains fully, unconditionally active for `REMOVE_SCOPE` and unaffected
  by this record -- it no longer applies to `PROMOTE_SCOPE` at all, a
  separately corrected, unrelated defect documented in
  `docs/todo/native_short_multi_asset_rollout_contract_v1.md`);
- map materialization, snapshot publication, Profit Plan rendering, or any
  wallet/account-aware action;
- any change to `run_chain_4h.sh`, systemd units, timers, or the 4h chain's
  scheduling.

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
