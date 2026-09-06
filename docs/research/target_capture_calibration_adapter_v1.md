# Target Capture Calibration Adapter V1 (#559 Phase A)

## Purpose

`target_capture_calibration_adapter_v1` is the Phase A adapter/audit slice
for issue #559. It maps #555
(`historical_fib_map_episode_substrate_v1`) `EpisodeRecord` target roles
T1/T2 into #224 (`execution_offset_replay_v1`) `ExecutionOffsetEpisodeV1` +
`ReplayCandle` inputs, so #559's later expected-return calibration can reuse
the #224 replay substrate against #555's historical Fib/map targets.

It is research-only, market-only, and account-agnostic. It does not
implement quantiles, candidate-buffer calibration, recommendations, a DB
runner, or any runtime/selection_engine/decision_gate/execution_planner/
executor/broker integration -- all later #559 phases.

Safety markers:

```text
research_only=1 market_only=1 account_awareness=0 decision_permission=0
execution_intent=0 broker_calls=0 broker_writes=0 orders=0 db_writes=0
production_profile_writes=0 runtime_activation=0
```

## What This Module Does Not Reimplement

- Fib/map geometry, anchor selection, target/invalidation projection --
  owned by `src.market_data.canonical_fib_zone_map_v1.build_row`, consumed
  here only through #555's already-built `EpisodeFeaturePayload`.
- Execution-offset replay/policy semantics -- owned by
  `src.research.execution_offset_replay_v1`.

It adds only the mapping/identity/filter glue between the two.

## Target Role -> Fib Level / Side Mapping

| Target role | `fib_level_id` | #555 source field |
| --- | --- | --- |
| `T1` | `F1.272` | `EpisodeFeaturePayload.target_t1` |
| `T2` | `F1.618` | `EpisodeFeaturePayload.target_t2` |

`F1.272`/`F1.618` name the same canonical extension levels #555 already
computes (`canonical_fib_zone_map_v1.build_row`'s `ext_1272`/`ext_1618`);
this adapter does not recompute or re-derive them, only labels them for the
#224 episode contract.

Side follows the Fib/exit-profile rule (AGENTS.md: "Pro Elliott/Fibo charts
are harvest maps, not buy/sell buttons"): a bullish map's targets sit above
current structure and are harvested by selling into them; a bearish map's
targets sit below and are harvested by buying into them.

| `EpisodeFeaturePayload.direction` | `ExecutionOffsetEpisodeV1.side` |
| --- | --- |
| `BULLISH` | `SELL` |
| `BEARISH` | `BUY` |

An unrecognized direction fails closed with `UNSUPPORTED_DIRECTION:<value>`
rather than guessing a side.

## Field Mapping

| `ExecutionOffsetEpisodeV1` field | Source | Notes |
| --- | --- | --- |
| `episode_id` | `compute_target_episode_id(...)` | deterministic SHA-256 of source map id, target role, symbol, venue, fib_level_id -- unique per (source map, role) |
| `symbol` / `venue` | `feature.symbol` / `feature.venue` | unchanged |
| `horizon` | `feature.source_timeframe` | `"1h"` / `"4h"` |
| `side` | derived from `feature.direction` | see table above |
| `fib_level_id` | `F1.272` / `F1.618` | per target role |
| `canonical_level` | `feature.target_t1` / `feature.target_t2` | per target role, unmodified |
| `issued_ts_utc` | `feature.map_creation_ts_utc` | unchanged |
| `valid_until_ts_utc` | `labels.terminal_ts_utc` | see "Validity Window" below |
| `invalidation_price` | `feature.invalidation_level` | preserved unmodified |
| `atr_at_issue` | `feature.atr_value` if `> 0`, else `None` | #555 uses `Decimal("0")` as its own "no ATR" sentinel; this adapter converts that to `None` rather than passing a non-positive ATR into #224, which rejects `atr_at_issue <= 0` |
| `regime_state` | always `None` | see "No Regime Semantic Misuse" below |
| `source_map_id` | `feature.episode_id` | the #555 map identity this target episode was derived from |

## Deterministic Target Episode Identity

`compute_target_episode_id(source_map_id, target_role, symbol, venue,
fib_level_id)` hashes a pipe-joined payload (module name/version, source map
id, target role, symbol, venue, fib_level_id) with SHA-256 -- the same
identity discipline #555's own `compute_episode_id` uses. The same
`(source_map_id, target_role)` pair always yields the same `episode_id`;
T1 and T2 for the same source map always yield different `episode_id`s
because `target_role` (and its resulting `fib_level_id`) is part of the
hashed payload.

## Validity Window

`valid_until_ts_utc` is #555's own `EpisodeOutcomeLabels.terminal_ts_utc` --
the forward-scan terminal boundary #555 already computed (T2 reached,
invalidation breached, same-candle target/invalidation ambiguity, or
forward/source exhaustion). This reuses #555's existing lifecycle evidence
rather than inventing a new validity rule.

`ExecutionOffsetEpisodeV1` requires `valid_until_ts_utc > issued_ts_utc`. A
#555 episode with zero forward candles leaves `terminal_ts_utc` equal to
`map_creation_ts_utc` (`build_episode_labels`'s initial value, never
advanced because the forward-scan loop body never executes) -- that case
cannot satisfy a positive validity window and is not silently passed
through. `map_target_episode` fails closed with
`VALIDITY_WINDOW_UNRESOLVED` for exactly this case.

## No Regime Semantic Misuse

`feature.map_state` / `feature.map_confidence` describe Fib/map lifecycle
state and geometry quality (per `historical_fib_map_episode_substrate_v1`),
not market regime. Per `docs/ops/state_model_discipline_v1.md`'s governing
concern for any state relabeling, this adapter never maps either field into
`regime_state`. `regime_state` is always `None` here; a genuine
market-regime source may populate it in a later phase, but this adapter
does not fabricate one from lifecycle/quality state.

## Candle Interval Filtering (#224 Full-Interval PIT Rule)

`convert_forward_candles(candles, issued_ts_utc, valid_until_ts_utc)`
converts #555 `HistoricalCandle` inputs to #224 `ReplayCandle`, applying the
exact PIT rule documented in `docs/research/execution_offset_replay_v1.md`
and enforced by `execution_offset_replay_v1.replay_episode`'s own
forward-candle filter: a candle's full interval must open at or after
`issued_ts_utc` and close no later than `valid_until_ts_utc`. A candle that
opens before issuance is excluded even if it closes later. Output is sorted
by `close_ts_utc` ascending for determinism; `replay_episode` independently
re-validates and re-sorts its own input, so this function's ordering is an
audit convenience, not a correctness dependency of the replay itself.

A non-positive window (`valid_until_ts_utc <= issued_ts_utc`) fails closed
with `INVALID_VALIDITY_WINDOW`.

## Minimal Analysis Context (Not a Schema Change to #224)

`TargetEpisodeAnalysisContextV1` carries `reference_price` and `direction`
from #555's `EpisodeFeaturePayload` alongside the mapped `episode_id` and
`source_map_id`, for #559's later expected-return economics (e.g.
normalizing target distance against the reference price the map was
projected from). This is a separate dataclass, not an addition to
`ExecutionOffsetEpisodeV1` -- the #224 episode schema is owned by issue
#224 and is not modified by this adapter.

## Exclusion / Fail-Closed Contract

`map_target_episode(record, target_role=...)` raises
`TargetCaptureAdapterError` for any unmappable case
(`VALIDITY_WINDOW_UNRESOLVED`, `UNSUPPORTED_DIRECTION:<value>`,
`UNSUPPORTED_TARGET_ROLE`) rather than silently omitting the target.

`map_episode_records(records, target_roles=(T1, T2))` batch-maps and
partitions every `(record, target_role)` pair into exactly one of two
output lists: a mapped `(episode, context)` entry, or a
`TargetEpisodeExclusionV1(source_map_id, target_role, reason)` entry. Every
input pair lands in exactly one list -- a caller can always verify
completeness via `len(mapped) + len(excluded) == len(records) *
len(target_roles)`. Output is sorted canonically by source-map identity and
T1/T2 role rank, so reversing caller input order does not change the result.
Duplicate source-map identities, duplicate/empty role requests, and unsupported
roles fail closed before mapping. `feature.episode_id` must also equal
`labels.episode_id`; mismatched #555 feature/label provenance fails with
`SOURCE_EPISODE_IDENTITY_CONFLICT`. This is the explicit, non-silent audit
trail Phase A is named for: an unmappable or internally inconsistent source
map is never dropped without a deterministic result.

## Scope Boundary

Implemented in this slice (Phase A):

1. deterministic target-episode identity per (source map, target role)
2. T1/T2 -> Fib level id / side mapping
3. field mapping into `ExecutionOffsetEpisodeV1` (validity window,
   invalidation, ATR, source map id)
4. `TargetEpisodeAnalysisContextV1` (reference price / direction carry-over)
5. #224 full-interval PIT candle conversion/filter
6. explicit exclusion/fail-closed audit trail for unmappable cases
7. focused synthetic unit tests (no DB)

Not implemented in this slice (later #559 phases):

- expected-return quantile computation
- candidate-buffer calibration
- recommendations
- a DB-backed runner
- any runtime, `selection_engine`, `decision_gate`, `execution_planner`,
  `executor`, or broker integration
