# Native SHORT Automatic Onboarding V1

## Status

Canonical ongoing market-data lifecycle for Bitvavo EUR. This supersedes the
bulk/canary rollout model for ordinary new-market onboarding.

## Flow

```text
active + tradeable Bitvavo EUR market
-> sufficient real 4h/1h candle history/model capability
-> canonical execution constraints
-> Native SHORT context/readiness
-> AUTO_ONBOARD_SCOPE -> SUPPORTED
-> scheduled native_short_4h_chain evaluation/materialization
-> context snapshot publication -> downstream import -> Profit Plan display
```

`AUTO_ONBOARD_SCOPE` is market-only, account-agnostic, deterministic, and
idempotent. It uses the existing atomic scope/cadence/support-event ledger
transaction. The scheduled chain dynamically re-reads `SUPPORTED` rows after
reconciliation; no symbol list or dashboard path creates scope state.

## Authority vocabulary

- `NOT_READY`: canonical market-data or ledger reason is present. No scope is
  created; the exact machine-readable reason is retained by readiness output.
- `READY`: all required real market evidence is present and ledger state is
  coherent, but the scope has not yet been persisted.
- `SUPPORTED`: canonical scope, cadence, and support-event state exist.

## Retained blockers

- inactive, disabled, malformed, or non-tradeable market metadata;
- insufficient real 4h/1h history or unavailable context;
- missing or ambiguous execution constraints/tick rule;
- ledger inconsistency or writer-provenance integrity failure.

## Per-run lifecycle readiness

Current 15m/1h/4h and supporting-source freshness is evaluated by every
scheduled chain run, after dynamic `SUPPORTED` scope selection. `SOURCE_STALE`
and `SOURCE_UNAVAILABLE` fail closed for that run: the scope is
`SKIPPED_NOT_READY`/`BLOCKED_SOURCE`, produces zero actionable map rows, and
publishes explicit stale/unavailable context while unrelated scopes continue.
They never withdraw or prevent structural support. On freshness recovery, the
same supported scope can materialize a fresh map without another onboarding
transition.

## Removed from normal onboarding

Sequential-canary ranking, per-symbol approval documents, manual
`PROMOTE_SCOPE`, bootstrap manifests, and removal-contract evidence are
historical rollout governance. They do not decide `AUTO_ONBOARD_SCOPE`.
Manual administration remains an exceptional repair/removal tool, not the
normal listing lifecycle.

## Safety

No synthetic candles, account reads, decision-gate/planner/executor calls,
broker private calls, or order activity are part of this flow.
