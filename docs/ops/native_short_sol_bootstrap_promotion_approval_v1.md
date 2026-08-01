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

## Repository commit binding

```text
repository_commit_sha: a74ff33121d42a7771eef0654e1526847d5c5d12
```

That is the exact commit, on
`fix/native-short-production-promotion-bootstrap-v1`, that introduced this
approval and the manifest naming it (recorded here, in a later commit, as a
plain historical reference to an already-existing commit -- not
self-referential, exactly like the existing
`38346fc1460453469ca5bd3bc2f45159f0dc303e` reference in
`docs/todo/native_short_multi_asset_rollout_contract_v1.md`).

A git commit object cannot state its own hash inside its own tree (the hash
is a function of the tree's content, so self-reference is not achievable
without brute-force hash-grinding, which this repository does not perform
or condone). Because of that property, the *manifest itself*, as committed
at commit `a74ff33...`, cannot show that same value -- it ships with an
intentional, never-real, all-zero placeholder instead. Production execution
therefore requires exactly one additional, mechanical, reviewed follow-up
commit that updates only
`repository_commit_sha` in the manifest to match the true final `git
rev-parse HEAD` of this branch, performed immediately before the
production command is run. Until that follow-up commit exists and is
checked out, `evaluate_promotion_bootstrap_evidence` fails closed with
`COMMIT_MISMATCH` for every possible checkout -- this is a safety property,
not a defect: the bootstrap exception cannot silently authorize a
different, unreviewed commit.

## Scope of this approval

Approved:

- exactly one `PROMOTE_SCOPE` invocation for the SOL scope above, executed
  through the existing `native_short_scope_administration_transaction_v1`
  owner with `native_short_4h_chain` writer authorization, from the exact
  commit named above (once pinned per the note above).

Not approved by this record:

- ETH, XRP, or any other symbol;
- a second promotion of SOL after the first succeeds (structurally
  impossible via this same bootstrap path once SOL's scope row exists --
  see `native_short_promotion_bootstrap_evidence_v1.py`);
- `REMOVE_SCOPE` for SOL or any other scope (`REMOVAL_CONTRACT_MISSING`
  remains active and unaffected by this record);
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
