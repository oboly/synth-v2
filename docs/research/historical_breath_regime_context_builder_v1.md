# Historical Breath Regime Context Builder V1

## Purpose

`historical_breath_regime_context_builder_v1` emits replay-safe, research-only context rows for later backtests and symbol behavior profiling.

This runner exists because the repo currently has `PARTIAL_CONTEXT_EXISTS`, not a single canonical historical context backbone.

## Boundary

- research-only
- market-only
- account-agnostic
- file output only
- no DB writes
- no broker calls
- no broker writes
- no order submission
- no selection, decision, execution, or executor integration

Safety markers:

```text
research_only=true
broker_calls=0
broker_writes=0
order_submission=0
executor=none
db_writes=0
```

## Canonical output row

Each emitted row uses this schema:

```text
symbol
venue
interval
asof_ts_utc
source_event_ts_utc
breath_phase
breath_alignment
market_regime
btc_context
symbol_regime
fibo_context
aplus_context_state
martee_context_state
relative_strength_bucket
momentum_bucket
quality_state
confidence_bucket
source_refs
research_only
```

## Source priority in v1

### 1. Historical breath spine

Primary source:

`data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl`

Optional preferred source when explicitly provided:

`data/research/historical_market_breath_source_enrichment_v1/historical_market_breath_source_enriched_rows_v1.csv`

or

`data/research/historical_market_breath_source_enrichment_v1/historical_market_breath_source_enriched_rows_v1.jsonl`

Used fields:

- `symbol`
- `venue`
- `interval_code`
- `asof_ts_utc`
- `market_breath_phase`
- `market_breath_state`
- `market_breath_confidence`
- `momentum_score`
- `relative_strength_score`
- `btc_alignment_score`
- `breadth_alignment_score`

When `--enriched-market-breath-rows` is provided, the builder prefers enriched rows for:

- `breath_phase`
- `breath_alignment`
- `market_regime`
- `btc_context`
- `symbol_regime`
- `relative_strength_bucket`
- `momentum_bucket`
- `quality_state`
- `confidence_bucket`
- `source_refs`

Priority rule:

- keep existing market-breath fallback behavior when the arg is absent
- do not override a known value with `UNKNOWN` from the enriched source
- prefer conservative `UNKNOWN` over invented values

### 2. Optional A+ enrichment

Primary source:

latest file matching:

`data/research/aplus_canonical_table1_v1/*.jsonl`

Used fields:

- `token`
- `prediction_ts_utc`
- `strategic_bias`
- `structural_role`
- `phase`

### 3. Missing lanes in v1

These are emitted as `UNKNOWN` unless a future builder version wires them explicitly:

- `fibo_context`
- `martee_context_state`

## Derived label rules in v1

### `breath_phase`

- `EXHALE_EXPANSION` -> `EXPANSION`
- `HOLD_COMPRESSION` -> `CONTRACTION`
- `INHALE_ACCUMULATION` -> `RELOAD`
- `OVERBREATH_EXTENSION` -> `POST_SPIKE`
- `COLLAPSE_RESET` -> `IGNITION`
- otherwise -> `UNKNOWN`

### `breath_alignment`

- `CONFIRMED` -> `ALIGNED`
- `EARLY`, `FORMING` -> `EARLY`
- `LATE` -> `LATE`
- `RESET` -> `INCOHERENT`
- otherwise -> `UNKNOWN`

### `market_regime`

If explicit regime labels are not present, V1 derives them from breath/breadth scores:

- hard BTC weakness -> `BTC_DAMAGE`
- negative momentum + weak breadth -> `RISK_OFF`
- strong momentum + strong relative strength -> `ALT_STRENGTH`
- positive momentum + non-negative BTC alignment -> `RISK_ON`
- otherwise -> `MIXED` or `UNKNOWN`

### `btc_context`

- severe BTC misalignment -> `BTC_DAMAGE_HARD`
- mild BTC weakness -> `BTC_DAMAGE_CAUTION`
- non-negative BTC alignment -> `BTC_OK`
- missing source -> `UNKNOWN`

### `symbol_regime`

- strong relative strength -> `REL_STRENGTH`
- weak relative strength -> `LAGGARD`
- extreme momentum magnitude -> `HIGH_BETA`
- very low momentum magnitude -> `LOW_BETA`
- missing source -> `UNKNOWN`

## Join contract

The builder itself emits context rows only. Later runners should join to them using:

- join by `symbol`
- join by exact `interval` where possible
- nearest `asof_ts_utc <= event_ts_utc`
- max staleness threshold by interval:
  - `15m` -> `8h`
  - `1h` -> `24h`
  - `4h` -> `48h`
  - `1d` -> `7d`
- missing rows must produce `UNKNOWN` context buckets
- strict mode may drop missing context, but default mode must not

## CLI

```bash
python -m src.research.run_historical_breath_regime_context_builder_v1 \
  --symbols WLD,NEAR,HYPE,TAO,FET,ALGO,XLM \
  --venue bitvavo \
  --interval 4h \
  --enriched-market-breath-rows data/research/historical_market_breath_source_enrichment_v1/historical_market_breath_source_enriched_rows_v1.csv \
  --write-files \
  --output summary
```

Optional synthetic time spine:

```bash
python -m src.research.run_historical_breath_regime_context_builder_v1 \
  --symbols WLD,NEAR \
  --interval 4h \
  --start-ts 2026-05-01T00:00:00Z \
  --end-ts 2026-05-03T00:00:00Z \
  --write-files \
  --output json
```

## Output files

When `--write-files` is set:

```text
data/research/historical_breath_regime_context_builder_v1/
  historical_breath_regime_context_rows_v1.csv
  historical_breath_regime_context_rows_v1.jsonl
  manifest_v1.json
```

## Notes

V1 is intentionally conservative:

- it preserves symbol identity
- it keeps provenance visible in `source_refs`
- it emits `UNKNOWN` instead of fabricating missing context
- it does not treat context labels as executable signals
- it reuses the live-semantics-compatible canonical mappings from the builder/enrichment helpers

## Recommended next batch

Use this file output as the context dependency for:

`symbol_reaction_profile_by_context_v1`
