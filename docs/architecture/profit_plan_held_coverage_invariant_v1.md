# Profit Plan Held-Token Coverage Invariant v1

## Purpose

Issue #238 requires the Profit Plan to remain portfolio-first and continuously current for the assets actually held by the rendered account.

The existing Profit Plan renderer already composes persisted account balance data, persisted market-price data, canonical reference levels, Planning PPP, and optional persisted cost basis. This contract adds a deterministic **post-render reporting invariant** so that incomplete, stale, duplicated, or internally inconsistent held-token coverage is detectable instead of silently accepted.

This contract is reporting-only. It does not create market truth, trade permission, execution intent, or orders.

## Authoritative held universe

For one rendered account/profile, the held universe is derived from the latest persisted `trading_account_balance_snapshot`:

```text
held_amount = available_amount + reserved_amount
held = held_amount > 0
```

The quote currency is excluded.

`account_asset`, native SHORT context, market-selection state, lifecycle state, and Planning PPP availability are **not** prerequisites for held-token visibility.

## Required held-card coverage

Every positive held asset must have exactly one Profit Plan card.

The card must preserve or expose:

- wallet-held identity;
- persisted held amount;
- persisted EUR value when a current usable persisted price exists;
- explicit unavailable EUR value when no current usable persisted price exists;
- wallet snapshot freshness/status;
- current market price plus visible price status, source timestamp, and freshness when a numeric price is shown;
- numeric Planning PPP **or** a precise unavailable reason;
- canonical re-entry, target, and invalidation reference levels when canonical 4h context reports itself available;
- persisted cost basis only when authoritative account-position data supplies it.

A card with native SHORT lifecycle context unavailable remains valid and visible when the above reporting truth is satisfied.

## Planning PPP

Planning PPP is a reporting reference and does not require native SHORT lifecycle verification.

The invariant accepts either:

```text
planning_ppp_pct = numeric
```

or:

```text
planning_ppp_pct = unavailable
planning_ppp_unavailable_reason = precise non-empty reason
```

It does not turn Planning PPP into an actionable PPP, permission, or execution input.

## Canonical levels

When a card reports:

```text
short_context_coverage_status = CANONICAL_4H_CONTEXT_AVAILABLE
```

it must expose all three reference categories:

- re-entry/buy level(s);
- target level(s);
- invalidation level.

The invariant does not build or recompute those levels. It only checks that reporting preserved an already-persisted canonical context result.

## Cost basis boundary

Issue #353 owns population of authoritative account position cost basis / average entry price.

Issue #238 must not infer or synthesize cost basis from:

- wallet balance;
- current market price;
- price history;
- orders;
- Fibonacci levels;
- lifecycle state.

If `account_position_snapshot.average_entry_price_eur` is unavailable, Profit Plan must display cost basis as unavailable.

When a persisted cost basis is present, the Profit Plan must retain explicit account-position authority/provenance for it.

## Currentness invariant

The checker compares an already-rendered Profit Plan JSON snapshot against a newly read latest persisted account context.

It fails when, among other cases:

- the rendered `account_snapshot_ts_utc` differs from the latest persisted balance snapshot timestamp;
- `wallet_held_count` differs from the latest positive-balance universe;
- a held card is missing or duplicated;
- a card is still marked wallet-held after the latest positive balance disappears;
- held amount/value differs from persisted truth;
- wallet freshness/status differs from current classification;
- numeric price lacks visible provenance/freshness;
- Planning PPP is unavailable without a reason;
- canonical 4h context claims availability while reference levels are missing.

This deliberately detects a stale render rather than silently blessing it.

## Runner

```text
python -m src.reporting.run_profit_plan_held_coverage_v1 \
  --account-profile joost \
  --venue bitvavo
```

Optional machine-readable output:

```text
python -m src.reporting.run_profit_plan_held_coverage_v1 \
  --account-profile joost \
  --venue bitvavo \
  --output json
```

Exit codes:

```text
0 = coverage PASS
1 = coverage FAIL
2 = input / persisted-context load error
```

The checker reads persisted account/market snapshots and the rendered Profit Plan JSON only. It does not rerender, mutate account state, enroll markets, publish Fib maps, or contact a broker.

## Relation to earlier #238 work

Earlier work added portfolio-first composition and separate held-market publication coverage. This v1 invariant does not reopen upstream enrollment/publication ownership. Under the current Lane 2 scope, it validates the reporting result only.

If a held card truthfully reports that upstream canonical context is unavailable, the checker does not fabricate it. Upstream market-data/publication defects remain with their owning lane.

## Architecture boundaries

Canonical architecture remains:

```text
persisted account snapshots -----> reporting composition
persisted market snapshots  -----> reporting composition
persisted canonical levels  -----> reporting composition
                                  -> Profit Plan HTML/JSON
                                  -> held coverage invariant
```

Forbidden:

```text
reporting -> selection_engine logic
reporting -> decision_gate mutation
reporting -> execution_planner
reporting -> executor
reporting -> broker call/write
reporting -> order submission/cancel
reporting -> fabricated lifecycle
reporting -> fabricated cost basis
```

Safety markers:

```text
reporting_only=true
broker_calls=0
broker_writes=0
order_submission=0
decision_gate=none
execution_planner=none
executor=none
```

## Acceptance criteria

- [ ] Every positive held asset from the latest persisted balance snapshot has exactly one card.
- [ ] Held amount and EUR value match current persisted reporting inputs.
- [ ] Wallet freshness/status is explicit.
- [ ] Numeric current prices preserve status/timestamp/freshness provenance.
- [ ] Planning PPP is numeric or has a precise unavailable reason.
- [ ] Native SHORT context is never required for held-token visibility.
- [ ] Canonical 4h reference levels are present when canonical context reports available.
- [ ] Missing cost basis remains explicitly unavailable; #353 is not implemented here.
- [ ] A stale rendered account snapshot fails the invariant.
- [ ] No selection, decision, planning, execution, broker, or order authority is introduced.
