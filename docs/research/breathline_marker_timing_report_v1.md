# Breathline Marker Timing Report V1

## Purpose

`run_breathline_marker_timing_report_v1` is a research-only, market-only, account-agnostic,
file-only runner for historical Breathline marker timing analysis.

Safety boundary:

```text
db_reads=0
db_writes=0
broker_calls=0
broker_writes=0
order_submission=0
```

This runner reads local JSONL produced by
`src/research/backtest_breath_curve_partial_to_full_v1.py` and writes local CSV summaries only.
It does not read the database, does not call brokers, and does not touch selection,
decision, execution, runtime, or UI layers.

## CLI

```bash
python -m src.research.run_breathline_marker_timing_report_v1 \
  --input-jsonl INPUT.jsonl \
  --out-dir OUTPUT_DIR
```

`--out-dir` must not exist with any pre-existing files. The runner rejects a non-empty
output directory and never overwrites artifacts.

## Input Contract

Accepted source rows are limited to:

```text
status == "OK"
```

Required source identity fields:

```text
symbol
anchor_ts_utc
checkpoint_ratio
selected_partial_offset_days
```

Marker data is read only from:

```text
selected_full_same_offset.markers
```

Required marker fields:

```text
code
expected_ts_utc
matched
```

`observed_ts_utc` is required only when `matched=true`.

## Validation

The runner rejects the input with a `ValueError` when any accepted row has:

```text
missing symbol, anchor timestamp, or checkpoint
duplicate accepted source identity by symbol + anchor_ts_utc + checkpoint_ratio
duplicate marker code within one source row
unparsable expected timestamp
matched=true with missing or unparsable observed timestamp
marker expected timestamps that are not strictly ascending in original source order
```

Source marker order is preserved. The runner does not reorder markers to mask invalid input.
Duplicate accepted source identities are rejected to prevent BTC-relative pairing ambiguity.

## Output Files

The runner writes exactly these seven files:

```text
marker_timing_observations.csv
marker_segment_observations.csv
marker_timing_summary.csv
marker_segment_summary.csv
btc_relative_marker_timing_summary.csv
btc_relative_segment_timing_summary.csv
manifest.txt
```

`manifest.txt` records `source_git_commit` when Git metadata is available.
When the runner is executed outside a Git checkout, when `git` is unavailable,
or when Git metadata cannot be resolved, the manifest records:

```text
source_git_commit=unavailable
```

### `marker_timing_observations.csv`

One row per source marker:

```text
symbol
anchor_ts_utc
checkpoint_ratio
selected_partial_offset_days
marker_code
expected_ts_utc
observed_ts_utc
matched
timing_error_hours
```

The runner preserves source `timing_error_hours` when supplied. It does not invent or
backfill a source timing-error value.

### `marker_segment_observations.csv`

One row per adjacent expected-marker pair:

```text
symbol
anchor_ts_utc
checkpoint_ratio
from_marker_code
to_marker_code
expected_duration_hours
observed_duration_hours
observed_minus_expected_hours
both_markers_matched
```

Rules:

```text
expected duration = to.expected_ts_utc - from.expected_ts_utc
observed duration exists only when both markers matched
unmatched pairs remain output rows with blank observed metrics
unmatched pairs are retained in total-count calculations
```

### `marker_timing_summary.csv`

Grouped by:

```text
checkpoint_ratio
symbol
marker_code
```

Columns:

```text
total_rows
matched_rows
match_rate
median_timing_error_hours
min_timing_error_hours
max_timing_error_hours
```

Timing-error statistics use only matched rows with numeric source timing-error values.

### `marker_segment_summary.csv`

Grouped by:

```text
checkpoint_ratio
symbol
from_marker_code
to_marker_code
```

Columns:

```text
total_rows
matched_segment_rows
match_rate
median_expected_duration_hours
median_observed_duration_hours
median_observed_minus_expected_hours
```

### `btc_relative_marker_timing_summary.csv`

Pairs BTC and each non-BTC coin by:

```text
anchor_ts_utc
checkpoint_ratio
marker_code
```

Only rows where both BTC and coin markers matched are included.

Definition:

```text
relative_marker_lag_hours = coin.observed_ts_utc - btc.observed_ts_utc
```

Positive means the coin marker was observed later than BTC.

### `btc_relative_segment_timing_summary.csv`

Pairs BTC and each non-BTC coin by:

```text
anchor_ts_utc
checkpoint_ratio
from_marker_code
to_marker_code
```

Only rows where both BTC and coin segment endpoints matched are included.

Definition:

```text
relative_segment_duration_delta_hours =
    coin.observed_duration_hours - btc.observed_duration_hours
```

Positive means the coin marker-segment interval took longer than BTC.

## Timing Sign Conventions

```text
positive BTC-relative marker lag:
    coin observed marker later than BTC

negative BTC-relative marker lag:
    coin observed marker earlier than BTC

positive BTC-relative segment-duration delta:
    coin observed marker-segment interval longer than BTC

negative BTC-relative segment-duration delta:
    coin observed marker-segment interval shorter than BTC
```

## Why Marker Timing Is Not Phase Duration

This report measures historical marker timing and marker-segment intervals only.
It does not produce a generalized phase-duration model. The source JSONL contains
timestamped marker observations, not a validated regime-length engine or a live timing model.

## Explicit Exclusions

This runner does not do or imply:

```text
transitions
reversals
re-anchors
live calibration
UI work
selection work
decision work
execution work
broker behavior changes
database reads or writes
```

## Reproducible Smoke Command

```bash
python -m src.research.run_breathline_marker_timing_report_v1 \
  --input-jsonl /home/gurk/projects/synth-v2-breathline-baseline-replay/data/research/breathline_backtest_campaign_v1/canonical_28_anchor_replay_20260627T124411Z/partial_to_full/breath_curve_partial_to_full_v1_20260627T124411Z.jsonl \
  --out-dir /tmp/breathline-marker-timing-report-v1-smoke
```
