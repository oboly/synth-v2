# context_event_coverage_gap_audit_v1

**Type:** Research-only diagnostic audit
**Status:** Research, no execution
**Safety:** `research_only=true`, no DB writes, no broker calls, no orders

---

## Purpose

Audit why event-level reaction rows have low historical context coverage. Produces a
per-event classification explaining the root cause of missing or unknown context, and
recommends the next remediation action before any broad context backfill.

---

## Input

| Source | Default path |
|---|---|
| Event-level rows (CSV) | `data/research/event_level_symbol_reaction_profile_by_context_v1/event_level_symbol_reaction_profile_by_context_rows_v1.csv` |
| Context rows (CSV) | `data/research/historical_breath_regime_context_builder_v1/historical_breath_regime_context_rows_v1.csv` |
| Recompute rows (CSV, optional) | `data/research/historical_market_breath_source_recompute_v1/historical_market_breath_source_recomputed_rows_v1.csv` |

---

## Issue classifications

| Classification | Meaning |
|---|---|
| `USABLE_CONTEXT` | Nearest context row is within staleness limit and has at least one known field |
| `CONTEXT_ROW_UNKNOWN` | Nearest context row is within staleness limit but all value fields are UNKNOWN |
| `STALE_CONTEXT` | Nearest context row is older than `MAX_STALENESS` (7 days) but event is not past range end |
| `PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE` | Event timestamp is beyond context range end + staleness, or before range start |
| `MISSING_CONTEXT_ROW` | No context rows exist for this symbol at all |
| `INTERVAL_MISMATCH` | Context row interval differs from event interval |
| `SYMBOL_MISMATCH` | No context rows match the event symbol |
| `UNKNOWN` | Fallback — should not appear in practice |

---

## Output columns (per event)

| Column | Description |
|---|---|
| `symbol` | Asset symbol |
| `event_ts_utc` | Event timestamp |
| `event_interval` | Event candle interval |
| `issue_classification` | Root cause label (see table above) |
| `issue_detail` | Human-readable detail string |
| `nearest_context_asof_ts_utc` | Timestamp of nearest context row (or null) |
| `nearest_context_age_hours` | Hours between nearest context and event |
| `nearest_recompute_asof_ts_utc` | Timestamp of nearest recompute row (or null) |
| `nearest_recompute_age_hours` | Hours between nearest recompute and event |
| `context_range_start` | Earliest context row for this symbol |
| `context_range_end` | Latest context row for this symbol |
| `recompute_range_start` | Earliest recompute row for this symbol |
| `recompute_range_end` | Latest recompute row for this symbol |
| `context_known_fields` | Context fields with non-UNKNOWN values |
| `context_unknown_fields` | Context fields that are UNKNOWN |
| `research_only` | Always True |

---

## CLI

```
python -m src.research.run_context_event_coverage_gap_audit_v1 \
  --event-level-rows <path>     # default: event_level_symbol_reaction_profile_by_context_v1/...csv
  --context-rows <path>         # default: historical_breath_regime_context_builder_v1/...csv
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
| `manifest_v1.json` | Run metadata, issue distribution, recommended next action |

---

## Recommended next actions

| Action | When |
|---|---|
| `rerun_context_builder_with_wider_date_range` | Most events are PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE or STALE_CONTEXT |
| `rerun_recompute_with_wider_date_range_or_accept_unknown` | Most events are CONTEXT_ROW_UNKNOWN |
| `fix_symbol_interval_join_or_extend_context_builder` | Most events are MISSING_CONTEXT_ROW |
| `no_action` | 90%+ events are USABLE_CONTEXT |

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
| `historical_breath_regime_context_builder_v1` | Context source being audited |
| `historical_market_breath_source_recompute_v1` | Supplementary context source being audited |
| `symbol_reaction_profile_from_event_level_context_v1` | Downstream aggregate — benefits from improved coverage |
