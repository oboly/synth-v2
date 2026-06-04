# context_event_coverage_gap_audit_v1

**Type:** Research-only diagnostic audit
**Status:** Research, no execution
**Safety:** `research_only=true`, no DB writes, no broker calls, no orders
**Version:** 1.1

---

## Purpose

Audit event-level context coverage and explain gaps. Produces a per-event classification
explaining the root cause of missing or partial context, and recommends the next
remediation action before any broad context backfill.

**Primary signal** reads embedded context fields from the event-level rows
(already joined by `event_level_symbol_reaction_profile_by_context_v1`).
Event-range rows that already carry market_regime / btc_context / symbol_regime
are never reclassified as `PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE`.

**Secondary signal** runs a staleness/range lookup against `--context-rows` as a
diagnostic — it does not override the primary classification.

---

## Input

| Source | Default path |
|---|---|
| Event-level rows (CSV) | `data/research/event_level_symbol_reaction_profile_by_context_v1/.../rows_v1.csv` |
| Context rows (CSV, optional) | `data/research/historical_breath_regime_context_builder_v1/.../rows_v1.csv` |
| Recompute rows (CSV, optional) | `data/research/historical_market_breath_source_recompute_v1/.../rows_v1.csv` |

---

## Coverage definitions

### Event-level (primary — from embedded fields)

| Label | Condition |
|---|---|
| `BREATH_CONTEXT` | `breath_phase` or `breath_alignment` is known |
| `SYMBOL_REGIME_CONTEXT` | `symbol_regime` known; breath is UNKNOWN |
| `MARKET_ONLY_CONTEXT` | `market_regime` or `btc_context` known; breath and symbol_regime UNKNOWN |
| `UNKNOWN_CONTEXT` | all context fields UNKNOWN |

Aggregate properties (non-mutually-exclusive, reported in manifest counts):

| Property | Fields counted |
|---|---|
| `ANY_CONTEXT` | any of market_regime, btc_context, symbol_regime, breath_phase, breath_alignment, fibo_context |
| `MATERIAL_CONTEXT` | any of breath_phase, breath_alignment, symbol_regime |

### Context-range (secondary — staleness/range lookup)

| Label | Meaning |
|---|---|
| `USABLE_CONTEXT` | Nearest context row within staleness limit with at least one known field |
| `CONTEXT_ROW_UNKNOWN` | Nearest context row within staleness but all value fields UNKNOWN |
| `STALE_CONTEXT` | Nearest context row older than `MAX_STALENESS` (7 days) |
| `PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE` | Event past context range end + staleness, or before range start |
| `MISSING_CONTEXT_ROW` | No context rows for this symbol |
| `INTERVAL_MISMATCH` | Context interval differs from event interval |

---

## Output columns (per event)

| Column | Description |
|---|---|
| `symbol` | Asset symbol |
| `event_ts_utc` | Event timestamp |
| `event_interval` | Event candle interval |
| `issue_classification` | **Primary** — event-level coverage label |
| `is_any_context` | True if any context field is known |
| `is_material_context` | True if breath or symbol_regime is known |
| `event_level_known_fields` | List of known context fields on the event row |
| `event_level_unknown_fields` | List of UNKNOWN context fields |
| `context_range_issue` | Secondary — staleness/range diagnostic |
| `context_range_detail` | Human-readable range diagnostic detail |
| `nearest_context_asof_ts_utc` | Timestamp of nearest context row (or null) |
| `nearest_context_age_hours` | Hours between nearest context and event |
| `nearest_recompute_asof_ts_utc` | Timestamp of nearest recompute row (or null) |
| `nearest_recompute_age_hours` | Hours between nearest recompute and event |
| `context_range_start` | Earliest context row for this symbol |
| `context_range_end` | Latest context row for this symbol |
| `context_known_fields` | Fields with known values in the context-range row |
| `context_unknown_fields` | UNKNOWN fields in the context-range row |
| `research_only` | Always True |

---

## CLI

```
python -m src.research.run_context_event_coverage_gap_audit_v1 \
  --event-level-rows <path>     # default: event_level_symbol_reaction_profile_by_context_v1/...csv
  --context-rows <path>         # optional, for range diagnostics
  --recompute-rows <path>       # optional
  --write-files                 # write CSV and manifest
  --output summary|json
  --output-dir <path>
```

---

## Output files

| File | Description |
|---|---|
| `context_event_coverage_gap_rows_v1.csv` | Per-event audit rows |
| `manifest_v1.json` | Run metadata, both coverage distributions, recommended next action |

---

## Recommended next actions

| Action | When |
|---|---|
| `rerun_context_builder_with_wider_date_range` | `unknown_context_events` > 50%, or `any_context_events` < 50% of total |
| `expand_breath_phase_context` | Most events have market/symbol context but <50% have breath |
| `expand_symbol_regime_and_breath_context` | All events have market context but material context < 50% |
| `expand_context_coverage` | Mixed gaps across field types |
| `no_action` | 90%+ events are USABLE / material context, breath >= 50% |

---

## Safety constraints

- No DB writes
- No broker calls
- No order creation
- No BUY_READY signals
- `research_only=True` on every output row and in manifest

---

## Relationship to other reports

| Report | Role |
|---|---|
| `event_level_symbol_reaction_profile_by_context_v1` | **Upstream** — provides event-level rows being audited |
| `historical_breath_regime_context_builder_v1` | Context source (range diagnostics) |
| `historical_market_breath_source_recompute_v1` | Supplementary context source (range diagnostics) |
| `symbol_reaction_profile_from_event_level_context_v1` | Downstream aggregate — benefits from improved coverage |

---

## Version history

| Version | Change |
|---|---|
| 1.0 | Initial — context-range lookup only; primary classification |
| 1.1 | Dual-path: event-level embedded fields primary; context-range secondary diagnostic only |
