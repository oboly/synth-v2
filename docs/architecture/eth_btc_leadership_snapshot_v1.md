# ETH/BTC Leadership Snapshot V1 (#721, under #305, for #617)

## Ownership

- **#305** remains the semantic/architecture owner of ETH/BTC leadership. It
  owns any future leadership *state*, *band*, or *classifier* built on top of
  this evidence. Nothing in this document or in
  `src/features/eth_btc_leadership_snapshot_v1.py` grants a parallel owner.
- **#721** is implementation only: the smallest deterministic, replay-safe,
  market-only producer of raw ETH/BTC return and price-ratio evidence needed
  by #617. It does not define or infer a leadership state.
- **#617** is a downstream consumer. This snapshot is intended as one input
  row for a future `RegimeEvidenceEnvelopeV1`; #617 itself does not compute
  leadership.
- **#315**'s presentation-only BTC-vs-ETH 30-day mini-curve is a separate,
  unrelated renderer and is not read or modified by this producer.

Per `docs/architecture/regime_evidence_matrix_audit_v1.md` 3.7/3.8: before
this change, ETH/BTC leadership evidence was `MISSING` with `owner/table:
"none distinct"`. This document and module resolve that gap for the
market-only evidence layer only; the leadership *classification* itself
remains #305's unresolved future work (see
`docs/todo/market_intelligence/macro_regime_engine_v1.md`).

## Why no native ETH/BTC market is used

Bitvavo (the sole canonical venue, `venue = "bitvavo"`) is EUR-quote only.
There is no native `ETH-BTC` market and no persisted ETH/BTC candle series
anywhere in the repository (confirmed by exhaustive grep before this change).
`obs_market_candle` itself carries no market/pair identity at all -- it is
keyed by `(asset_id, venue, interval_code, open_ts_utc)`, per issue #310's
audit (`docs/architecture/ma_breadth_snapshot_v1.md`). The ETH/BTC comparison
is therefore derived arithmetically from the separately persisted
`BTC-EUR`/`ETH-EUR` daily candle series, joined only by matching UTC
timestamp -- never read as a native pair market.

## Contract shape

Producer: `src/features/eth_btc_leadership_snapshot_v1.py`
Table: `eth_btc_leadership_snapshot_v1`
(`db/migrations/20260904_eth_btc_leadership_snapshot_v1.sql`)
Idempotency key: `(asof_ts_utc, venue, btc_market, eth_market, input_interval,
lookback_horizon, model_id, model_version)` -- a unique key enforced by the
migration; `persist_snapshot` performs an insert-once
`ON DUPLICATE KEY UPDATE created_at=created_at` no-op, matching the
`ma_breadth_snapshot_v1` (#310) pattern.

Fields (raw numeric values are the primary output):

```text
venue                       "bitvavo"
asof_ts_utc                 exact UTC candle close timestamp evaluated
btc_market / eth_market     canonical venue_market identity ("BTC-EUR"/"ETH-EUR")
input_interval               "1d" -- the only interval this producer reads
lookback_horizon              "24h" -- exactly one prior daily candle
effective_horizon             "UNKNOWN" (see below -- not resolved by #305 yet)
model_id / model_version      "eth_btc_leadership_snapshot" / "1.0"
freshness                     FRESH | STALE | INSUFFICIENT_DATA
data_status                   AVAILABLE | INSUFFICIENT_DATA
btc_return_pct / eth_return_pct / eth_minus_btc_return_pct
eth_btc_ratio_start / eth_btc_ratio_end / eth_btc_ratio_change_pct
reason_codes                  JSON array, deterministic and enumerated
provenance                    JSON object: exact candle boundaries consulted
```

No `ETH_LED`/`BTC_LED` (or any other) leadership band is computed, stored, or
implied. `eth_minus_btc_return_pct > 0` is raw arithmetic only; it is not
translated into a leadership label by this module.

## `effective_horizon`: explicit unresolved-ownership blocker

Per #243 3.3, `effective_horizon` must never be inferred from
`input_interval`. No #305 owner decision has declared an `effective_horizon`
for ETH/BTC leadership. This module therefore leaves it `UNKNOWN` and always
adds `UNMAPPED_HORIZON` to `reason_codes` -- an explicit, documented blocker,
not an invented value. This exactly mirrors the precedent already accepted
for `RELATIVE_STRENGTH.CROSS_SECTIONAL_RANK`
(`src/features/relative_strength_evidence_contract_v1.py`), which shipped
with the same unresolved-ownership handling rather than blocking the whole
producer. Promoting this to a declared `effective_horizon` (or a longer
lookback lane) requires a future #305 owner decision, tracked outside this
module.

## Freshness: reused canonical authority, not invented

`freshness` reuses the existing canonical persisted-candle freshness
classifier, `src.operations.persisted_market_candle_freshness_v1.classify_persisted_candle_boundary`
(issue #606), rather than inventing a new staleness rule. That classifier is
venue+interval scoped, not asset scoped; this module's own
`fetch_asset_boundary` adds an `asset_id` filter to the same query shape and
hands the unmodified result to the same, already-reviewed classifier -- once
per required exact boundary:

```text
BTC candle at asof         BTC candle at asof-24h (lookback)
ETH candle at asof         ETH candle at asof-24h (lookback)
```

Each boundary classifies independently to `FRESH` / `MISSING` / `STALE` /
`FUTURE` / `MALFORMED`. These four results fold into one snapshot as follows:

- any boundary `MISSING` -> `freshness=INSUFFICIENT_DATA`
  (`MISSING_BTC_CANDLE` / `MISSING_ETH_CANDLE` /
  `MISSING_BTC_LOOKBACK_CANDLE` / `MISSING_ETH_LOOKBACK_CANDLE`)
- any boundary `FUTURE` or `MALFORMED` -> `freshness=INSUFFICIENT_DATA`
  (`FUTURE_CANDLE_BOUNDARY` / `MALFORMED_CANDLE_BOUNDARY`) -- a data-integrity
  contradiction, not a staleness judgement
- else any boundary `STALE` -> `freshness=STALE`
  (`STALE_BTC_CANDLE` / `STALE_ETH_CANDLE` / `STALE_BTC_LOOKBACK_CANDLE` /
  `STALE_ETH_LOOKBACK_CANDLE`)
- all four `FRESH` -> `freshness=FRESH`, and only then are the raw
  return/ratio numbers computed

Separately, `asof_ts_utc`/`lookback_ts_utc` being later than the caller's
`evaluated_at` fails closed to `INSUFFICIENT_DATA`
(`ASOF_AFTER_EVALUATION_TS`) before any candle boundary is even consulted --
a future evaluation instant is a data-integrity contradiction, not staleness.
`evaluated_at` is a required keyword argument with no default anywhere in
`build_snapshot`, so a replay caller can never have this function silently
observe the wall clock, and historical replay can never fall back to a
latest/current row: every input row must be the exact historical row for the
exact boundary being evaluated.

## Non-goals (explicitly out of scope for #721)

- No `RegimeEvidenceEnvelopeV1` implementation (#617's own future work).
- No leadership state/band classifier (#305's future work).
- No dashboard/UI (`src/reporting/`, `apps/`) changes.
- No change to `src/reporting/market_rotation_pressure_dashboard_v1.py`,
  Rotation (#593/#676/#710-equivalent), `relative_strength`/Structure
  (#669/#672), Conviction (#591), `selection_engine` (`src/selection/`),
  `decision_gate`, `execution_planner`, `executor`, or account state.
- No broker calls, no order submission, no deploy, no timer/service
  activation. `--write-db` in the runner requires an explicit
  `writer_capability_authorization_v1` grant for the
  `eth_btc_leadership_snapshot` capability, which is intentionally
  unregistered by this change -- a live write requires a separate, future
  production-authorization decision (out of scope here; dry-run is the only
  mode exercised by this PR).

## Related documents

- `docs/architecture/regime_evidence_matrix_audit_v1.md` (#617 audit; ETH/BTC
  leadership `MISSING` finding, #305 ownership confirmation)
- `docs/architecture/multi_horizon_signal_contract_v1.md` (#243)
- `docs/architecture/ma_breadth_snapshot_v1.md` (#310; persisted-producer
  template this module follows)
- `docs/architecture/structure_relative_strength_evidence_contract_v1.md`
  (#669/#672; confirms ETH/BTC leadership was explicitly out of scope there)
- `docs/todo/market_intelligence/macro_regime_engine_v1.md` (#305 spec)
