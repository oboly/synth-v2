# Execution Offset Replay v1

Issue #224 owns the shared research substrate for execution-offset studies.
This contract is research-only and does not change planner, executor, broker, or live behavior.

## Episode contract

Each immutable episode preserves market identity, source map identity, canonical Fib level, side, horizon, issuance time, validity window, invalidation, ATR-at-issue, and optional regime context.

Only candles whose full interval starts at or after `issued_ts_utc` and closes no later than `valid_until_ts_utc` may label an episode. A candle opened before issuance is excluded even if it closes later. Future candles are labels only.

When one OHLC candle spans both the candidate execution price and invalidation price before any prior fill, intrabar ordering is unknowable. The replay records `same_candle_fill_invalidation_ambiguous=true`, claims neither fill nor invalidation-before-fill, and stops that episode rather than inventing an order of events.

## Baseline policies

- `EXACT_LEVEL`: execution price equals canonical market level.
- `STATIC_BUFFER`: BUY moves above the level; SELL moves below the level by a fixed fraction.
- `VOLATILITY_SCALED_BUFFER`: same side semantics, with offset derived from ATR known at issuance.

The canonical Fib level is never rewritten.

Near-miss distance is policy-specific: it is measured against the candidate `execution_price`, while the raw canonical level remains separately preserved for audit. MFE/MAE starts only on candles strictly after the fill candle because OHLC cannot establish whether an excursion inside the fill candle occurred before or after the fill.

`touched` is policy-specific and means the candidate execution price was reached/crossed. `canonical_level_touched` separately preserves whether the raw Fib level itself traded inside a candle range. Therefore a buffered fill may have `touched=true` and `canonical_level_touched=false` without conflating market truth and execution policy.

Every replay row persists the exact policy parameters plus a SHA-256 `policy_fingerprint` over policy id, version, static buffer and ATR multiple. Policy id/version alone is not treated as sufficient identity for reproducible grouping.

## Phase B: dataset export and baseline report

`src/research/execution_offset_replay_report_v1.py` adds a pure module that
assembles the replay dataset and a deterministic baseline summary from
caller-supplied episodes, candles, and policies. It performs no I/O, no DB
access, and no policy learning/calibration.

`build_replay_dataset(episodes, candles_by_episode_id, policies)`:

- fails closed on a duplicate `episode_id`, a duplicate policy fingerprint
  (`policy_fingerprint`, not policy id/version alone), missing candles for a
  supplied episode, no episodes, or no policies;
- calls `replay_episode` once per (episode, policy) pair and rejects any
  resulting duplicate `(episode_id, policy_fingerprint)` row identity;
- returns rows sorted by `(episode_id, policy_fingerprint)` so output order
  never depends on caller iteration order.

`export_dataset(rows, episodes_by_id)` emits a self-contained dataset row with separate immutable episode provenance and replay result objects; each exported row preserves all required episode context.
The episode object carries the immutable provenance (`symbol`, `venue`,
`horizon`, `side`, `fib_level_id`, `canonical_level`, `issued_ts_utc`,
`valid_until_ts_utc`, `invalidation_price`, `atr_at_issue`, `regime_state`,
`source_map_id`) from the referenced episode. A downstream reader (Issue
#559) never has to join a separate episode mapping onto the exported
dataset to recover that context.

`export_dataset` fails closed with `MISSING_EPISODE_FOR_ROW` if a row's
`episode_id` is not present in `episodes_by_id`, and with
`CANONICAL_LEVEL_CONFLICT` if a row's `canonical_level` does not match the
referenced episode's `canonical_level`.

Every `Decimal` field is rendered via `format(value, "f")` (exact string, no
float rounding) and every timestamp is rendered via `.isoformat()` on an
aware `datetime`. The SHA-256 `dataset_fingerprint` is computed over the
canonically ordered, canonically JSON-encoded *export* row set, so it covers
episode provenance as well as replay metrics — a change to episode identity
fields changes the fingerprint even if replay metrics are unchanged. Same
input rows in any order produce the same fingerprint and the same
serialized bytes.

`summarize_baseline(rows, episodes_by_id, min_sample_threshold=30)` segments
results at minimum by:

- `overall` — all supplied rows;
- `policy` — grouped by `policy_fingerprint` (covers `EXACT_LEVEL`,
  `STATIC_BUFFER`, `VOLATILITY_SCALED_BUFFER` as supplied by the caller;
  the module does not restrict or learn which policies are compared beyond
  what `execution_offset_replay_v1` already validates);
- `policy_symbol` — policy segments further split by episode `symbol`;
- `policy_regime` — policy segments further split by episode `regime_state`
  (missing regime uses the explicit `UNKNOWN_REGIME_KEY` sentinel, never
  silently dropped).

Each segment reports `sample_count`, `min_sample_threshold`, and an explicit
`confidence_state` of `SUFFICIENT_SAMPLE` or `INSUFFICIENT_SAMPLE` alongside
fill/touch/invalidation/ambiguity rates and average near-miss, time-to-fill,
MFE, and MAE. Segments never merge different `policy_fingerprint` values,
so differing policy parameters cannot be silently averaged together.

`summarize_baseline` and `build_report` fail closed with
`INVALID_MIN_SAMPLE_THRESHOLD` if `min_sample_threshold <= 0`, so a
non-positive threshold cannot silently mark every segment as
`SUFFICIENT_SAMPLE`.

`build_report(...)` combines `export_dataset` and `summarize_baseline` into
one payload; `render_report_json(...)` renders it as stable, sorted-key,
`Decimal`-safe JSON.

### Phase B non-goals

- No parameter learning or calibration (Issue #559 scope) — policy
  parameters are supplied by the caller and used as-is.
- No runtime, decision_gate, execution_planner, executor, or broker
  integration.
- No database reads or writes; episodes and candles are passed in by the
  caller from whatever research source the caller chooses.
- No mutation of canonical Fib levels or episode inputs; `canonical_level`
  on every output row is the unmodified value from the source episode.
