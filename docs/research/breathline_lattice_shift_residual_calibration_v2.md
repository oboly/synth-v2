# Breathline Lattice Shift Residual Calibration V2

## Purpose

`run_breathline_lattice_shift_calibration_v2.py` is a research-only calibration lane for
measuring daily-candle alignment between a fixed 21-day replay anchor and a lattice of
candidate template shifts.

V1 remains frozen. This V2 lane does not modify:

- `src/market_context/breath_curve_core_v1.py`
- `src/research/breath_curve_template_matcher_v1.py`
- `src/research/backtest_breath_curve_partial_to_full_v1.py`
- `docs/research/breathline_marker_evidence_viewer_v1.md`

It also does not touch dashboard, selection, decision, execution, broker, schema, or
production services.

## Explicit Terms

- `raw_lattice_anchor_ts_utc`: fixed 21-day replay anchor.
- `template_time_shift_days`: global template shift for one symbol/epoch.
- `effective_schedule_origin_ts_utc = raw_lattice_anchor_ts_utc + template_time_shift_days`.
- `marker_residual_hours`: local deviation after the global shift.

`effective_schedule_origin_ts_utc` is a schedule coordinate only. It is never labeled as a
confirmed market phase start.

## Marker Sets

Base markers determine the selected shift:

1. `0.236 FIRST_LIFT_HIGH HIGH`
2. `0.382 FIRST_DIP_LOW LOW`
3. `0.500 SECOND_PEAK_RETEST_HIGH HIGH`
4. `0.618 SECOND_DIP_HIGHER_LOW LOW`
5. `0.786 IGNITION_PRE_SPIKE HIGH`
6. `1.000 MAIN_PULSE_TP_HIGH HIGH`

Extensions are emitted only after a unique base-shift winner exists and never influence base
ranking:

1. `1.272 EXTENSION_1.272 HIGH`
2. `1.618 EXTENSION_1.618 HIGH`
3. `2.618 EXTENSION_2.618 HIGH`

## Shift Grid

Default candidate grid in days:

```text
-10.5, -10, -9, -8, -7, -6, -5, -4, -3, -2, -1, 0,
+1, +2, +3, +4, +5, +6, +7, +8, +9, +10, +10.5
```

No result is snapped back to old A+ bands.

## Daily Residual Rules

Only `interval_code=1d` is supported.

A daily candle represents:

```text
[open_ts_utc, open_ts_utc + 1 day)
```

Residual semantics:

- residual is `0` when the expected marker time falls inside that candle interval;
- otherwise residual is the distance to the nearest candle boundary.

Sensitivity modes are exact:

- `STRICT = 12h`
- `NORMAL = 18h`
- `MAX = 24h`

The matcher never reuses one candle for multiple base-marker roles, and chosen base-marker
candles must remain strictly chronological.

## Ranking

Each symbol/anchor/sensitivity/shift resolves one ordered base-marker sequence with explicit
matched or unmatched markers.

Base shift ranking order is exactly:

1. highest matched base-marker count
2. highest passed base shape-rule count
3. lowest maximum base-marker residual
4. lowest total base-marker residual

There are no weighted scores, smoothing steps, or re-anchor labels.

Top tie behavior:

- `selection_status = UNIQUE_TOP_CANDIDATE` when exactly one shift wins.
- `selection_status = TIED_TOP_CANDIDATES` when top shifts tie on all ranking fields.
- tied tops keep every winning shift in `tied_shift_days`.
- tied tops do not emit a selected shift.

## Shape Diagnostics

The V2 matcher keeps visible boolean-or-null shape diagnostics derived from V1 where they still
apply, plus explicit passed/available counts.

The old 2.5% retest rule remains diagnostic only:

```text
second_peak_retests_first_lift_within_2p5pct
```

It is surfaced but never used as a hidden ranking rule.

## Calibration Runner

CLI:

```bash
python -m src.research.run_breathline_lattice_shift_calibration_v2 \
  --input-jsonl INPUT.jsonl \
  --out-dir OUTPUT_DIR \
  --candles-jsonl CANDLES.jsonl
```

Supported options:

- `--symbols` optional CSV filter
- `--candles-jsonl` optional deterministic candle fixture source
- `--continuity-alert-delta-days` default `3.0`

When `--candles-jsonl` is absent, candle loading falls back to read-only `obs_market_candle`
queries.

Accepted candle fixture fields:

```text
symbol
open_ts_utc
open
high
low
close
```

Output files:

```text
ranked_shift_candidates.csv
marker_sequence_evidence.csv
extension_marker_evidence.csv
epoch_shift_continuity.csv
tolerance_sensitivity_summary.csv
manifest.txt
```

`epoch_shift_continuity.csv` is audit-only. It reports previous/current unique shifts, raw
shift delta, effective cycle spacing, and threshold comparison without calling any movement a
re-anchor or phase truth.

`manifest.txt` records input hashes, source git commit when available, candle source, zero DB
writes, and explicit research-only boundary markers.

## A+ Raw Comparison

`run_breathline_offset_continuity_aplus_comparison_v1.py` accepts:

- V2 `epoch_shift_continuity.csv`
- a manually mapped A+ CSV with exact required raw columns

Only exact symbol + `raw_lattice_anchor_ts_utc` pairs are aligned.

Only rows with:

```text
offset_unit == "days"
raw_offset_band is finite numeric
```

are comparable. Other units, including source-relative forms, are rejected instead of coerced.

The comparison runner emits raw comparison fields only. It never feeds back into market ranking.

## Boundary

```text
db_writes=0
broker_calls=0
broker_writes=0
order_submission=0
live_orders=0
selection_engine=none
decision_gate=none
execution_planner=none
executor=none
scope=research-only market-only calibration lane
```
