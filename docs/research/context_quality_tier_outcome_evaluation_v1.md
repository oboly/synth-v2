# context_quality_tier_outcome_evaluation_v1

**Type:** Research-only outcome evaluation
**Status:** Research, no execution
**Safety:** `research_only=true`, no DB writes, no broker calls, no orders

---

## Purpose

Evaluate whether `context_quality_tier` has measurable outcome value before any strategy
or advice use. Aggregates event-level reaction outcomes by tier and surfaces whether
higher-tier events (BREATH_CONTEXT) differ materially from lower-tier events
(MARKET_ONLY_CONTEXT) on MFE, MAE, forward returns, and fakeout rate.

This runner does not promote any tier to a strategy signal. It is a diagnostic layer only.

---

## Input

| Source | Default path |
|---|---|
| Event-level rows (CSV) | `data/research/event_level_symbol_reaction_profile_by_context_v1_event_range/.../rows_v1.csv` |

---

## Tier definitions (from event-level field)

| Tier | Condition |
|---|---|
| `BREATH_CONTEXT` | `breath_phase` or `breath_alignment` is known |
| `SYMBOL_REGIME_CONTEXT` | `symbol_regime` known; breath fields UNKNOWN |
| `MARKET_ONLY_CONTEXT` | `market_regime` or `btc_context` known; breath and symbol_regime UNKNOWN |
| `UNKNOWN_CONTEXT` | all context fields UNKNOWN |
| `ALL` | synthetic baseline row covering all events |

---

## Output rows

### Tier rows (`context_quality_tier_outcome_rows_v1.csv`)

One row per tier plus one `ALL` baseline row.

| Column | Description |
|---|---|
| `context_quality_tier` | Tier label or `ALL` |
| `event_count` | Events in this tier |
| `symbol_count` | Distinct symbols with events in this tier |
| `avg_mfe_pct` | Average max favorable excursion |
| `avg_mae_pct` | Average max adverse excursion |
| `mfe_mae_ratio` | avg_mfe / abs(avg_mae) |
| `avg_drawdown_pct` | Average drawdown after event |
| `fakeout_rate` | % events with fakeout flag |
| `reaction_zone_touch_rate` | % events touching reaction zone |
| `avg_return_{h}_pct` | Average forward return per horizon (15m/30m/1h/4h/24h) |
| `positive_rate_{h}` | % events with positive forward return per horizon |
| `sample_quality` | INSUFFICIENT / LOW / MEDIUM / HIGH |
| `research_only` | Always True |

### Per-symbol tier rows (`context_quality_tier_symbol_rows_v1.csv`)

One row per (symbol, tier) combination.

| Column | Description |
|---|---|
| `symbol` | Asset symbol |
| `context_quality_tier` | Tier label |
| `event_count` | Events for this symbol in this tier |
| `avg_mfe_pct` | Average max favorable excursion |
| `avg_mae_pct` | Average max adverse excursion |
| `mfe_mae_ratio` | avg_mfe / abs(avg_mae) |
| `avg_return_4h_pct` | Average 4h forward return |
| `avg_return_24h_pct` | Average 24h forward return |
| `fakeout_rate` | % events with fakeout flag |
| `sample_quality` | INSUFFICIENT / LOW / MEDIUM / HIGH |
| `research_only` | Always True |

---

## CLI

```
python -m src.research.run_context_quality_tier_outcome_evaluation_v1 \
  --event-level-rows <path>     # default: event_level_symbol_reaction_profile_by_context_v1_event_range/...
  --symbols WLD,NEAR,...        # optional symbol filter
  --min-events 5                # minimum events for sample_quality thresholds
  --write-files                 # write CSV rows and manifest
  --output summary|json
  --output-dir <path>
```

---

## Output files

| File | Description |
|---|---|
| `context_quality_tier_outcome_rows_v1.csv` | Per-tier aggregate rows |
| `context_quality_tier_symbol_rows_v1.csv` | Per-(symbol, tier) aggregate rows |
| `manifest_v1.json` | Run metadata, tier counts, sample quality, usable tiers |

---

## Rules

- Uses only available event-level fields; missing metrics are null, not invented.
- No tiers are promoted to strategy signals.
- No BUY_READY flags.
- UNKNOWN context remains UNKNOWN; not relabelled.
- Sample quality is INSUFFICIENT when event count < min_events.

---

## Safety constraints

- No DB writes
- No broker calls
- No order creation
- No BUY_READY signals
- No execution planner or decision gate calls
- `research_only=True` on every output row and in manifest

---

## Relationship to other reports

| Report | Role |
|---|---|
| `event_level_symbol_reaction_profile_by_context_v1` | **Upstream** — provides event-level rows with `context_quality_tier` |
| `breath_phase_unknown_diagnostic_v1` | Explains why BREATH_CONTEXT events are sparse |
| `context_event_coverage_gap_audit_v1` | Confirms coverage before this evaluation |
| `symbol_reaction_profile_from_event_level_context_v1` | Aggregate bucket profile, complementary view |
