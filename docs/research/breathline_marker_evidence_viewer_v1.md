# Breathline Marker Evidence Viewer V1

## Purpose

`run_breathline_marker_evidence_viewer_v1.py` is a research-only static HTML/SVG viewer for
existing Breathline marker observations. It renders marker evidence pages for manual review.

Every generated page shows this exact warning:

```text
MARKER EVIDENCE — NOT PHASE DURATION
VISUAL REVIEW REQUIRED — NO STRATEGY OR EXECUTION USE
```

The viewer does not recompute markers, does not alter tolerance logic, and does not promote
observations into strategy, decision, execution, broker, or dashboard flows.

## Safety Boundary

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
db_writes=0
```

Scope:

```text
research-only
static self-contained HTML/SVG only
no JS framework
no CDN
no browser fetch
no DB writes
no broker or order access
```

Read-only DB access is allowed only for candle lookup when inline fixture candles are absent.
If candles cannot be read, the viewer renders an explicit warning instead of crashing.

## CLI

```bash
python src/research/run_breathline_marker_evidence_viewer_v1.py \
  --input-jsonl INPUT.jsonl \
  --out-dir OUTPUT_DIR \
  --symbols BTC ETH PEPE \
  --checkpoint-ratio 0.618
```

Filters:

```text
--symbols           optional allowlist, space-separated
--checkpoint-ratio  optional exact checkpoint filter
```

`--out-dir` must be empty or absent. The runner refuses to overwrite an occupied directory.

## Input Contract

Accepted rows are limited to:

```text
status == "OK"
```

Required row identity fields:

```text
symbol
anchor_ts_utc
checkpoint_ratio
selected_partial_offset_days   (or selected_full_same_offset.phase_offset_days as fallback)
```

All `*_utc` timestamps must carry an explicit timezone:

```text
accepted: 2025-01-01T00:00:00Z
accepted: 2025-01-01T00:00:00+00:00
rejected: 2025-01-01T00:00:00
```

Marker evidence is read only from:

```text
selected_full_same_offset.markers
selected_full_same_offset.flags
selected_full_same_offset.tolerance_hours
selected_full_same_offset.interval_code
selected_full_same_offset.venue
```

Required marker fields:

```text
code
expected_ts_utc
matched
```

`matched` must be a JSON boolean:

```text
accepted: true
accepted: false
rejected: "true"
rejected: "false"
rejected: 1
rejected: 0
```

Additional marker fields shown when present:

```text
kind
ratio
observed_ts_utc
observed_price
timing_error_hours
```

The viewer preserves source marker order and rejects:

```text
duplicate accepted record identity by symbol + anchor_ts_utc + checkpoint_ratio
duplicate marker code inside one accepted row
missing required timestamps
matched markers without observed_ts_utc
marker expected timestamps that are not strictly ascending
invalid inline candle geometry or non-monotonic candle timestamps
```

## Candle Source Rules

The viewer resolves candles in this order:

1. Optional inline fixture candles from `evidence_candles` or `candles`
2. Read-only `obs_market_candle` lookup through `src.common.db`

Inline candle payloads are intended for tests and fixture smoke renders. Real observation inputs
usually rely on read-only candle lookup by:

```text
symbol
venue
interval_code
anchor/marker time window
```

No matcher behavior is reimplemented. The viewer only reads existing observation fields and the
public candle path needed to draw them.

For DB-backed daily candles, the viewer uses the candle `open_ts_utc` schedule coordinate so
selected HIGH/LOW extrema align with the same candle timestamp convention used by the matcher.
The chart also shows:

```text
LATTICE ANCHOR = raw anchor_ts_utc
OFFSET-ADJUSTED ORIGIN = anchor_ts_utc + phase_offset_days
```

The offset-adjusted origin is a schedule coordinate only. It is not a confirmed market phase
start.

## Output Files

The runner writes:

```text
index.html
evidence_<symbol>_<anchor>_cp_<checkpoint>.html
evidence_index.csv
manifest.txt
```

`evidence_index.csv` contains one row per rendered page:

```text
symbol
anchor_ts_utc
checkpoint_ratio
page_file
marker_count
matched_marker_count
candle_source
candle_count
warning
```

`manifest.txt` records:

```text
input path
input sha256
rendered row count
filter scope
source_git_commit
db_reads
safety markers
```

## Page Content

Each evidence page includes:

```text
real candles when available
anchor timestamp
expected marker timestamps
visible tolerance windows
selected extrema
marker code
expected versus observed timestamp
timing error
selected offset
checkpoint ratio
shape flags
marker table
```

When candles are missing, the page still renders:

```text
the required warning banner
the anchor and expected-marker timeline
the marker table
an explicit missing-candle warning
```

## Research Use

This viewer is for visual review only. It is not:

```text
phase-duration analysis
strategy evidence by itself
decision permission
execution intent
order guidance
dashboard actioning
```
