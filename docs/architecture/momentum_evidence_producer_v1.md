# Canonical MOMENTUM evidence producer v1

Status: implemented, docs-only-scoped follow-up to
[`momentum_evidence_canonical_owner_audit_v1.md`](momentum_evidence_canonical_owner_audit_v1.md).
Resolves that audit's `BUILD_MINIMAL_CANONICAL_OWNER` decision for issue
#617, tracked by #741.

## Owner

- Production module: `src/features/momentum_evidence_snapshot_v1.py`.
- Manual runner (no timer activation): `src/features/run_momentum_evidence_snapshot_v1.py`.
- Persistence: `momentum_evidence_snapshot_v1` table
  (`db/migrations/20260904_momentum_evidence_snapshot_v1.sql`).
- `MODEL_ID = "momentum_evidence_snapshot"`, `MODEL_VERSION = "1.0"`.

This producer is the canonical, market-only, production-safe MOMENTUM
evidence owner referenced by #617's `RegimeEvidenceEnvelopeV1`. It does not
implement #617 itself (no `RegimeEvidenceEnvelopeV1` assembly, no dashboard
consumption) and grants no `selection_engine`, `decision_gate`,
`execution_planner`, or `executor` authority.

## Source

Reads canonical persisted candles from `obs_market_candle` only
(`venue`, `asset_id`, `interval_code`, `close_ts_utc`, `close_price`,
`candle_id`). No other table is read. `feat_candle` (the existing
`rsi_14`/`ema_20`/`ema_50` primitives audited in
`momentum_evidence_canonical_owner_audit_v1.md`) is not reused here: this
producer computes its own EMA12/EMA26 directly from `obs_market_candle`
closes, because `feat_candle` has no `model_id`/`model_version`/horizon
fields to build a #243 contract on top of, and its `ema_20`/`ema_50`
periods do not match the MACD-standard 12/26/9 family.

## Math (fixed; do not silently change periods)

```text
fast EMA period   = 12
slow EMA period   = 26
signal EMA period = 9

MACD             = EMA12(close) - EMA26(close)
signal           = EMA9(MACD)
histogram        = MACD - signal
histogram_delta  = histogram[t] - histogram[t-1]
```

EMA convention matches the rest of the repository's feature primitives
(`etl_candle_feat.py`'s `ema_20`/`ema_50`/RSI/ATR): pandas
`Series.ewm(span=N, adjust=False, min_periods=N).mean()`. This is a
recursive EMA seeded at the first observation (`y_0 = x_0`), not an
SMA-seeded EMA; `min_periods` only masks the first `N-1` outputs to `NaN`,
it does not change the recursion itself.

No categorical momentum states are produced (no `EARLY_UP`, `BULLISH`,
`CROSS_PENDING`, etc.) -- raw numeric primitives only, per this task's
explicit constraint.

## Warmup (explicit minimum-history requirements)

| Value | Minimum bars |
| --- | --- |
| EMA12 | 12 |
| EMA26 | 26 |
| MACD | 26 (bounded by EMA26) |
| signal EMA9(MACD) | 34 (26 + 9 - 1; `min_periods=9` only starts counting once MACD itself becomes non-null at bar 26) |
| histogram | 34 (bounded by signal) |
| histogram_delta | 35 (needs two consecutive valid histogram values: bars 34 and 35) |

`WARMUP_BARS = 35` is the single floor this producer enforces end to end,
so that whenever raw values are emitted, all four
(`macd_value`, `signal_value`, `histogram_value`, `histogram_delta`) are
simultaneously valid -- never a partial row. Insufficient warmup is never
treated as valid evidence (`data_quality = INSUFFICIENT_WARMUP`, all raw
fields `None`).

## asof / replay discipline

- Every call requires an explicit `asof_ts_utc` and `evaluated_at`; there is
  no current/latest fallback anywhere in `momentum_evidence_snapshot_v1.py`
  or its runner.
- `fetch_candles_for_asof` bounds the source query to
  `close_ts_utc <= asof_ts_utc` -- the fetched window can never include a
  candle from after the requested point in time.
- `build_momentum_evidence` additionally rejects (raises
  `MomentumEvidenceInputError`) any caller-supplied row with
  `close_ts_utc > asof_ts_utc` or a duplicate `close_ts_utc`, since a
  replay caller passing such rows is a caller-shape defect, not a data-
  quality state to silently coerce.
- `asof_ts_utc` after `evaluated_at` (future asof) fails closed to
  `status = INSUFFICIENT_DATA` with `ASOF_AFTER_EVALUATION_TS`
  (`evidence_contract_v1.compute_freshness`, reused unmodified) and
  `data_quality = FUTURE_ASOF`. This short-circuits before any
  candle/interval/warmup handling: `macd_value`, `signal_value`,
  `histogram_value`, and `histogram_delta` are all `None` on the returned
  snapshot -- a future asof must never carry any usable computed momentum
  primitive, not merely a rejected top-level `status`.

## Freshness (two distinct concepts, not conflated)

1. **Source candle freshness** -- is the exact `asof_ts_utc` candle actually
   persisted, or is the source gapped/missing at that boundary? This reuses
   the one existing canonical candle-freshness authority in the repository,
   `operations.persisted_market_candle_freshness_v1.classify_persisted_candle_boundary`,
   applied to the point-in-time-bounded fetch (so "latest" in that
   classifier's output can never be a real wall-clock value). Result feeds
   `data_quality` (`OK` / `MISSING_SOURCE_CANDLE` / `STALE_SOURCE_CANDLE` /
   `MALFORMED_SOURCE_CANDLE`). `FUTURE_ASOF` is a separate, higher-priority
   `data_quality` value set before source-candle classification even runs
   (see "asof / replay discipline" above).
2. **#243 evidence freshness** (`SignalHorizonV1Evidence.freshness`) -- asof
   vs. `evaluated_at` only, via `evidence_contract_v1.compute_freshness`,
   reused unmodified. No second staleness policy is invented. Because
   `compute_freshness` never returns `FRESH` (no reviewed staleness rule
   exists for any producer yet), the top-level `status` field is always
   `INSUFFICIENT_DATA` by design until an owner explicitly reviews and
   declares a #243 freshness rule for this producer -- this mirrors the
   existing precedent in `structure_evidence_contract_v1` and
   `relative_strength_evidence_contract_v1`. It does **not** gate whether
   the raw MACD/signal/histogram numbers are computed; `data_quality`
   governs that.

## Horizons (#243 discipline)

`input_interval` ("4h") != `lookback_horizon` (bar-count description,
`"35 bars @ 4h"`) != `effective_horizon` != `observed_lifecycle`. No
reviewed effective-horizon mapping exists for this producer, so
`effective_horizon` is always `UNKNOWN` (never inferred from
`input_interval`, per #243 12.3) and `observed_lifecycle_status` is always
`UNMEASURED` -- both reused unmodified from `features.evidence_contract_v1`.

## Interval scope (v1) and extensibility

`INPUT_INTERVAL = "4h"` only. 4h is the interval already exercised by the
other reviewed canonical snapshot producers on `obs_market_candle`
(`ma_breadth_snapshot_v1`, native SHORT scope), so its ETL lookback default
and replay-boundary support are already proven in production. 1h/1d/1w/2w
are explicitly **not** implemented in v1 -- adding one requires a
deliberate follow-up that reviews that interval's own candle-completeness
and replay-boundary guarantees; this doc does not claim they are supported.

## Persistence

`momentum_evidence_snapshot_v1` (new table). Deterministic idempotent
identity: `UNIQUE KEY (venue, asset_id, market, input_interval, asof_ts_utc,
model_id, model_version)`, with `INSERT ... ON DUPLICATE KEY UPDATE
created_at = created_at` (a repeat write for the same identity is a no-op,
matching `ma_breadth_snapshot_v1`'s pattern). `reason_codes_json` and
`provenance_payload` are `LONGTEXT` JSON payloads, matching the existing
`reason_codes_json`/`provenance_payload` convention used elsewhere in
`db/migrations/`. A `CHECK` constraint enforces that the four raw fields are
either all `NULL` or all non-`NULL` together (never a partial row).

No new persistence framework was introduced; this extends the existing
snapshot-table pattern (`ma_breadth_snapshot_v1`, `eth_btc_leadership_snapshot_v1`).

## Writer authorization

`--write-db` requires `writer_capability_authorization_v1`
(`require_capability_write_authorization("momentum_evidence_snapshot",
...)`), the single shared fail-closed writer-capability mechanism used
across the repository. `"momentum_evidence_snapshot"` is **deliberately not
registered** in that module's `CAPABILITY_IDENTITY` map or in
`deploy/ownership/writer_capability_ownership_v1.json` -- this mirrors the
existing `ma_breadth_snapshot` precedent. Any `--write-db` invocation
therefore fails closed with `unknown capability_id=momentum_evidence_snapshot`
until an explicit, separately reviewed registration/authorization decision
is made. No production authorization is granted by this change; no runtime
activation (no systemd unit/timer) is added.

## Reason codes

Shared #243 codes (`MISSING_ASOF_TS`, `ASOF_AFTER_EVALUATION_TS`,
`FRESHNESS_NOT_OWNER_DEFINED`, `UNMAPPED_HORIZON`) are reused unmodified
from `evidence_contract_v1.ReasonCode`. Producer-specific codes
(`MomentumReasonCode` in `momentum_evidence_snapshot_v1.py`):
`MISSING_SOURCE_CANDLE`, `STALE_SOURCE_CANDLE`, `MALFORMED_SOURCE_CANDLE`,
`NON_CONTIGUOUS_SOURCE_WINDOW`, `INSUFFICIENT_WARMUP`,
`NON_FINITE_COMPUTED_VALUE`, `UNSUPPORTED_INTERVAL`.

## Non-goals

- No #617 `RegimeEvidenceEnvelopeV1` assembly or dashboard consumption.
- No #301 composite regime scoring.
- No duplication of #415 (RSI divergence) or #449 (Rotation Flip); this
  module contains no RSI or rotation logic of its own.
- No `selection_engine`, `decision_gate`, `execution_planner`, or
  `executor` coupling; no account state; no broker calls; no order
  submission.
- No production write authorization; no timer/service activation.
