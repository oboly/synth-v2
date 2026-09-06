# Target Capture Calibration Runner V1 (#559 Phase C)

## Purpose

`run_target_capture_calibration_v1` is the Phase C DB-facing runner for
issue #559. It builds a deterministic, read-only historical target-capture
calibration report for one `(venue, symbol, timeframe)` per invocation, by
wiring together three already-merged, independently owned building blocks:

- **#555** `historical_fib_map_episode_substrate_v1` /
  `run_historical_fib_map_episode_substrate_v1`: DB fetch (EMA-state
  prehistory, requested window, forward tail) and deterministic Fib/map
  episode construction (`build_episodes`).
- **#559 Phase A** `target_capture_calibration_adapter_v1`: maps each #555
  episode's T1/T2 target roles into #224 `ExecutionOffsetEpisodeV1` +
  `TargetEpisodeAnalysisContextV1` (`map_episode_records`), and PIT-filters
  the shared fetched candle set into each mapped episode's exact
  full-interval replay window (`convert_forward_candles`).
- **#559 Phase B** `target_capture_calibration_analysis_v1`: deterministic
  candidate-buffer economics/disposition (`build_calibration_report`),
  which itself delegates all fill/near-miss replay to the shared #224
  `execution_offset_replay_report_v1`.

This runner adds only CLI/DB orchestration, run identity, exclusion
counting/reporting, and immutable publish. It does not reimplement Fib
geometry, EMA/trend reconstruction, forward-scan lifecycle labeling,
target-role mapping, PIT candle filtering, replay/policy semantics, or
calibration economics -- every one of those stays owned by the module that
already implements it.

Safety markers:

```text
research_only=1 market_only=1 account_awareness=0 decision_permission=0
execution_intent=0 broker_calls=0 broker_writes=0 orders=0 db_writes=0
production_profile_writes=0 runtime_activation=0
broker_private_calls=0 order_submission=0 live_orders=0
decision_gate=none execution_planner=none executor=none
```

## CLI

```bash
python -m src.research.run_target_capture_calibration_v1 \
  --venue bitvavo \
  --symbol BTC \
  --timeframe 4h \
  --from-ts "2026-01-01 00:00:00" \
  --to-ts "2026-06-01 00:00:00"
```

Optional flags: `--episode-stride-candles` (default `1`), `--max-episodes`
(default unbounded), `--target-roles` (comma-separated, default `T1,T2`),
`--min-sample-threshold` (default matches #559 Phase B's
`MIN_SAMPLE_THRESHOLD`), `--output-dir` (default
`data/research/target_capture_calibration_v1`), `--chunk-size-candles`
(default matches #555's DB fetch chunk size).

## Pipeline

1. Fetch, via #555's own functions (imported, never reimplemented):
   `fetch_asset_id`, `fetch_ema_state_prehistory_candles` (full available
   history strictly before `--from-ts`, no `LIMIT`), `fetch_candles` (the
   requested `[--from-ts, --to-ts)` window), `fetch_forward_tail_candles`
   (bounded forward-label evidence at/after `--to-ts`).
2. Validate the combined candle sequence (`validate_candle_sequence`) and
   fingerprint it (`compute_source_input_sha256`) -- the SAME fingerprint
   #555's own run identity uses.
3. Build #555 episodes (`build_episodes`) over the combined candle set,
   emitting only for as-of candles inside `[--from-ts, --to-ts)`.
4. Map every built episode's requested target roles to #224 episodes
   (`map_episode_records`); any (episode, role) pair that cannot be mapped
   deterministically (see #559 Phase A's `TargetEpisodeExclusionV1`
   reasons, e.g. `VALIDITY_WINDOW_UNRESOLVED`) becomes an explicit
   exclusion, never a silent drop.
5. For every successfully mapped target episode, PIT-filter the SAME
   already-fetched combined candle set into that episode's exact
   `[issued_ts_utc, valid_until_ts_utc]` full-interval replay window
   (`convert_forward_candles`) -- no separate per-episode fetch.
6. Run `build_calibration_report` over the resulting `CalibrationInputV1`
   list.
7. Publish `{report_v1.json, manifest_v1.json}` atomically under
   `<output-dir>/<venue>/<symbol>/<timeframe>/<run_id>/`.

## Run identity

`run_id` is a SHA-256 over every dataset-defining CLI parameter (venue,
symbol, timeframe, from_ts, to_ts, episode_stride_candles, max_episodes,
target_roles, min_sample_threshold), this runner's own
builder/contract version, EVERY upstream module version actually used
(#555 substrate builder/contract version, #559 Phase A adapter builder
version, #559 Phase B analysis version), and `source_input_sha256` -- the
same #555 candle-content fingerprint the underlying episodes were built
from. A change to Fib geometry, target-role mapping, or calibration
economics therefore always produces a new `run_id`/immutable path; it can
never silently change the content already published at an existing one.

## Exclusions are always counted and reported

`map_episode_records`'s explicit `TargetEpisodeExclusionV1` list is never
dropped. The manifest carries `mapped_target_episode_count`,
`excluded_target_episode_count`, a `exclusion_reason_counts` breakdown, and
the full `exclusions` list (`source_map_id`, `target_role`, `reason`) for
audit. If every candidate target episode is excluded (or #555 built zero
episodes), `build_calibration_report` raises `NO_CALIBRATION_INPUTS`; this
runner treats that as `FAILED reason=calibration_failed` -- it never writes
an empty or degenerate report to disk.

## Publish

`publish_immutable_pair` mirrors #555's `publish_immutable_run` staging/
rename discipline (stage both files in a private sibling directory, fsync
each file and the directory, then a single atomic `os.rename`), so
`<run_id>/` is always either absent or a complete, mutually consistent
`{report_v1.json, manifest_v1.json}` pair -- never a partial directory with
only one file. It is a local, filename-parameterized function rather than a
direct reuse of #555's `publish_immutable_run` because that function
hardcodes the `episodes_v1.json`/`manifest_v1.json` names that are correct
for its own Fib/map episode contract, not for a calibration report.

A repeat run with identical inputs (same fetched candle content, same CLI
parameters, same upstream module versions) is idempotent: the existing
directory is left untouched and its content hashes are returned unchanged.
A repeat run that resolves to the SAME `run_id` but would produce different
content (e.g. an upstream module change that is not reflected in a version
constant, or a non-deterministic input) fails closed
(`FAILED reason=output_write_failed`) rather than silently overwriting.

## Fail-closed contract

Exactly one of `FAILED reason=<code> ...`, `INTERRUPTED ...`, or
`FINISHED ...` is printed per run. `reason` codes: `invalid_arguments`,
`asset_lookup_failed`, `source_fetch_failed`, `source_validation_failed`,
`build_failed`, `mapping_failed`, `calibration_failed`,
`output_write_failed`. `SIGINT`/`SIGTERM` are handled at the same safe
boundaries #555's runner already establishes (via the shared `_SignalState`
helper); an interrupted run never writes a partial or misleading output.

## Read-only / non-goals

- No DB writes of any kind.
- No broker calls, no order submission, no execution intent.
- No `decision_gate`, `execution_planner`, or `executor` involvement.
- No promotion: the calibration report's `disposition` field
  (`REJECT` / `RESEARCH_ONLY` / `EXECUTION_PLANNER_CANDIDATE`) is research
  evidence only, exactly as #559 Phase B's own documentation states. It
  does not grant execution permission and does not configure
  `execution_planner`.
