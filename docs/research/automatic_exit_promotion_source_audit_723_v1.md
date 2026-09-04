# #723 Phase A0 — Automatic-exit promotion source/substrate audit v1

Status: **AUDIT COMPLETE — reusable PIT episode substrate not found**

Issue: #723
Related: #555, #664, #657, #707
Layer: research only

## Decision

Do **not** start #723 promotion qualification directly from current production Fib/map snapshots and do **not** build a second Fib implementation.

The repository currently has specifications for the required historical replay dataset, but no reviewed implementation or immutable historical 1h/4h map-episode substrate that #664/#723 can consume.

Therefore the next implementation step is a **small canonical historical Fib/map episode substrate owned by #555**, reused by #664 and #723.

## Evidence inspected

### #555

Issue #555 requires historical replay of the same canonical map/Fibonacci code path under independent `1h` and `4h` configurations and explicitly forbids a second Fib implementation.

Its required per-map output already contains nearly all structural fields needed downstream by #664/#723:

- symbol / market
- map creation timestamp
- source timeframe
- selected anchors
- reference price
- entry/re-entry levels
- target levels
- invalidation level
- target/invalidation distances
- lifecycle outcomes and timing
- ATR-normalized distances

#555 also explicitly says its historical map episodes should be reused for #664 rather than rebuilding a second dataset.

### #664

Issue #664 defines the calibration dataset and forward labels that should consume those historical episodes. It is research-only and market-only and requires point-in-time-safe features with future candles used only as labels.

No #664 implementation PR or branch was found during this audit.

### Existing current-state map/snapshot infrastructure

The repository has current-state canonical map/snapshot infrastructure, including native map identities and immutable snapshot publication. That is useful production truth, but it is not by itself the required historical replay episode corpus:

- it represents selected current/published map state rather than a chronological PIT episode history;
- it does not establish independent 1h/4h historical replay coverage;
- it cannot be repurposed into a backfilled historical episode dataset by applying current/latest context to old candles.

It may be reused as the canonical geometry/source-code path where applicable, but not as a substitute for historical replay.

## Required minimal substrate

Implement one reusable, deterministic historical episode contract under #555.

Each immutable episode must carry at minimum:

```text
schema_version
method_version
episode_id
symbol
venue
market
timeframe
asof_ts_utc
map_identity / source identity
anchor_low_ts / anchor_low_price
anchor_high_ts / anchor_high_price
reference_price
invalidation_price
raw target levels + prices
ATR / volatility context available at as-of
source candle bounds
code_commit_sha
input/provenance digest
```

Forward labels must be stored separately from as-of features/geometry so future data cannot leak back into episode construction.

Required forward-label examples:

```text
first_touch_ts per level
reached_before_invalidation per level
time_to_reach per level
invalidation_ts
MFE
MAE
map replacement/completion reason where canonical
```

## Architecture boundary

```text
historical market candles
-> canonical Fib/map engine replayed PIT
-> immutable historical map episode
-> forward-label pass (future data = labels only)
-> #555 horizon analysis
-> #664 reach calibration
-> #723 promotion qualification
```

No account state belongs anywhere in this lane.

```text
account_awareness=0
decision_permission=0
execution_intent=0
broker_calls=0
broker_writes=0
order_submission=0
production_profile_writes=0
runtime_activation=0
```

## Implementation constraints

1. Reuse the canonical Fib/map geometry implementation. Do not copy target formulas into a research-only fork.
2. Episode construction is strictly point-in-time: each episode may use only information available at `asof_ts_utc`.
3. Future candles are consumed only by a separate labeler.
4. Preserve 1h and 4h as independent episode streams. Do not merge them into one synthetic map.
5. Freeze episode identity and provenance deterministically.
6. Prefer immutable file evidence under `data/research/` over new production tables.
7. No scheduler, runtime integration, DB writes, selection policy changes, or #657 wiring in this phase.

## Entry criterion for #723 Phase A1

#723 may freeze its promotion-qualification methodology only after the substrate can produce a deterministic sample of historical episodes with:

- exact 1h/4h identity;
- exact as-of timestamps;
- canonical geometry provenance;
- target + invalidation values;
- no future leakage in construction;
- reproducible immutable artifact output.

Until then:

```text
723_PROMOTION_QUALIFICATION=BLOCKED_ON_HISTORICAL_EPISODE_SUBSTRATE
657_PHASE_B=BLOCKED
```

## Cleanup / ownership

Do not add a second episode implementation under #664 or #723. #555 owns the reusable substrate; #664 owns calibration; #723 owns promotion-grade qualification; #657 owns promotion mechanics only.
