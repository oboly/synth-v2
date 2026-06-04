# symbol_reaction_profile_from_event_level_context_v1

**Type:** Research-only aggregate
**Status:** Research, no execution
**Safety:** `research_only=true`, no DB writes, no broker calls, no orders

---

## Purpose

Rebuild aggregate symbol reaction profiles from event-level rows already joined with
historical context. Solves the context-collapse problem in the original aggregate pipeline:
grouping before joining caused known context to be merged into UNKNOWN buckets.

This runner reads the output of `event_level_symbol_reaction_profile_by_context_v1` (which
preserves per-event context at join time) and groups those rows into aggregate buckets.
Known context buckets are kept strictly separate from UNKNOWN buckets.

---

## Input

| Source | Default path |
|---|---|
| Event-level rows (CSV) | `data/research/event_level_symbol_reaction_profile_by_context_v1/event_level_symbol_reaction_profile_by_context_rows_v1.csv` |

The event-level rows must have been produced by
`run_event_level_symbol_reaction_profile_by_context_v1.py`.

---

## Grouping key

Each aggregate row represents a unique combination of:

- `symbol`
- `breath_phase`
- `breath_alignment`
- `market_regime`
- `btc_context`
- `symbol_regime`
- `fibo_context`
- `context_quality_state`

UNKNOWN values in any field remain as their own bucket dimension.
Known values are never merged into UNKNOWN-keyed buckets.

---

## Output columns

| Column | Description |
|---|---|
| `symbol` | Asset symbol |
| `breath_phase` | Bucket key |
| `breath_alignment` | Bucket key |
| `market_regime` | Bucket key |
| `btc_context` | Bucket key |
| `symbol_regime` | Bucket key |
| `fibo_context` | Bucket key |
| `context_quality_state` | Bucket key |
| `event_count` | Events in this bucket |
| `context_quality_tier` | `BREATH_CONTEXT` / `SYMBOL_REGIME_CONTEXT` / `MARKET_ONLY_CONTEXT` / `UNKNOWN_CONTEXT` |
| `known_context` | True if any of breath_phase / breath_alignment / symbol_regime is non-UNKNOWN |
| `avg_mfe_pct` | Average max favorable excursion |
| `median_mfe_pct` | Median max favorable excursion |
| `avg_mae_pct` | Average max adverse excursion |
| `median_mae_pct` | Median max adverse excursion |
| `mfe_mae_ratio` | avg_mfe / abs(avg_mae) |
| `avg_drawdown_pct` | Average drawdown after event |
| `fakeout_rate` | % events with fakeout flag |
| `reaction_zone_touch_rate` | % events touching reaction zone |
| `avg_retrace_to_entry_low_pct` | Average retrace to entry zone low |
| `avg_retrace_to_entry_mid_pct` | Average retrace to entry zone mid |
| `avg_retrace_to_entry_high_pct` | Average retrace to entry zone high |
| `avg_forward_return_{horizon}` | Average forward return per horizon |
| `positive_rate_{horizon}` | % events with positive forward return per horizon |
| `sample_quality` | INSUFFICIENT / LOW / MEDIUM / HIGH |
| `research_only` | Always True |

---

## CLI

```
python -m src.research.run_symbol_reaction_profile_from_event_level_context_v1 \
  --event-level-rows <path>     # default: event_level/.../rows_v1.csv
  --symbols WLD,NEAR,...        # optional symbol filter
  --min-events 1                # minimum events to include bucket
  --write-files                 # write CSV, JSONL, manifest
  --output summary|json
  --output-dir <path>
```

---

## Output files

| File | Description |
|---|---|
| `symbol_reaction_profile_from_event_level_context_rows_v1.csv` | Aggregate rows |
| `symbol_reaction_profile_from_event_level_context_rows_v1.jsonl` | Aggregate rows (JSONL) |
| `manifest_v1.json` | Run metadata, counts, safety markers |

---

## Safety constraints

- No DB writes
- No broker calls
- No order creation
- No BUY_READY signals
- No execution planner calls
- `research_only=True` on every output row and in manifest

---

## Relationship to other reports

| Report | Role |
|---|---|
| `event_level_symbol_reaction_profile_by_context_v1` | **Upstream** — provides event-level rows with preserved context |
| `symbol_reaction_profile_by_context_v1` | Original aggregate (has context-collapse issue) |
| `historical_breath_regime_context_builder_v1` | Context source for the event-level join |
| `historical_market_breath_source_recompute_v1` | Supplementary context source |

---

## Known limitations

- Aggregate rows with UNKNOWN context are preserved as-is; they reflect events where no
  context row was within `MAX_STALENESS` of the event timestamp.
- Metrics are only computed from event-level fields that are present; missing fields yield
  `None` rather than invented values.
- No profile label is assigned — this report is a data layer, not a trading signal.
