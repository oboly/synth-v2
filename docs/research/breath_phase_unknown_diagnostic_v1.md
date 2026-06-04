# breath_phase_unknown_diagnostic_v1

**Type:** Research-only diagnostic
**Status:** Research, no execution
**Safety:** `research_only=true`, no DB writes, no broker calls, no orders

---

## Purpose

Diagnose why `breath_phase` and `breath_alignment` remain UNKNOWN for most event-level
rows, before changing any label logic or rerunning builders. Produces a per-event
classification explaining the root cause, plus score distributions for UNKNOWN-breath
rows, so the decision to relabel or accept UNKNOWN can be made from data.

---

## Input

| Source | Default path |
|---|---|
| Event-level rows (CSV) | `data/research/event_level_symbol_reaction_profile_by_context_v1_event_range/.../rows_v1.csv` |
| Recompute rows (CSV) | `data/research/historical_market_breath_source_recompute_v1_event_range/.../rows_v1.csv` |
| Context rows (CSV, optional) | `data/research/historical_breath_regime_context_builder_v1_event_range/.../rows_v1.csv` |

---

## Unknown-reason classification

Mutually exclusive, assigned in priority order:

| Label | Condition |
|---|---|
| `SOURCE_ROW_MISSING` | No recompute row within MAX_STALENESS (7 days) of the event |
| `RAW_PHASE_UNKNOWN` | Recompute row found, but `market_breath_phase_raw` is UNKNOWN or blank |
| `RAW_PHASE_NEUTRAL_TRANSITION` | `market_breath_phase_raw = NEUTRAL_TRANSITION` — market is genuinely ambiguous |
| `RAW_STATE_UNKNOWN` | Raw phase is not NEUTRAL_TRANSITION but `market_breath_state_raw` is UNKNOWN |
| `LIVE_SEMANTICS_CONSERVATIVE` | Raw phase and raw state are both known, but canonical mapper returned UNKNOWN (conservative threshold) |
| `UNKNOWN` | Fallback — should not appear in practice |

---

## Output columns (per event)

| Column | Description |
|---|---|
| `symbol` | Asset symbol |
| `event_ts_utc` | Event timestamp |
| `breath_phase` | Canonical breath phase from event-level row |
| `breath_alignment` | Canonical breath alignment from event-level row |
| `breath_unknown` | True if breath_phase or breath_alignment is UNKNOWN |
| `recompute_asof_ts_utc` | Recompute row timestamp used for classification |
| `raw_phase` | `market_breath_phase_raw` from nearest recompute row |
| `raw_state` | `market_breath_state_raw` from nearest recompute row |
| `market_breath_confidence` | Confidence score from recompute row |
| `unknown_reason` | Root cause label (null for known-breath events) |
| `compression_score` | Score from recompute row |
| `expansion_score` | Score from recompute row |
| `momentum_score` | Score from recompute row |
| `reversal_pressure_score` | Score from recompute row |
| `relative_strength_score` | Score from recompute row |
| `btc_alignment_score` | Score from recompute row |
| `breadth_alignment_score` | Score from recompute row |
| `research_only` | Always True |

---

## CLI

```
python -m src.research.run_breath_phase_unknown_diagnostic_v1 \
  --event-level-rows <path>     # default: event_level_symbol_reaction_profile_by_context_v1_event_range/...
  --recompute-rows <path>       # default: historical_market_breath_source_recompute_v1_event_range/...
  --context-rows <path>         # optional
  --write-files                 # write CSV and manifest
  --output summary|json
  --output-dir <path>
```

---

## Output files

| File | Description |
|---|---|
| `breath_phase_unknown_diagnostic_rows_v1.csv` | Per-event diagnostic rows |
| `manifest_v1.json` | Run metadata, distributions, score stats, expansion verdict |

---

## Expansion verdict

The manifest includes `expansion_verdict` — a textual recommendation on whether the
UNKNOWN breath events should be relabelled, based on the dominant unknown reason:

| Dominant reason | Verdict |
|---|---|
| `RAW_PHASE_NEUTRAL_TRANSITION` | `SHOULD_REMAIN_UNKNOWN` — market is genuinely ambiguous |
| `RAW_PHASE_UNKNOWN` | `SHOULD_REMAIN_UNKNOWN` — raw signal is missing |
| `LIVE_SEMANTICS_CONSERVATIVE` | `REVIEW_LIVE_THRESHOLD` — consider relaxing threshold for research |
| `SOURCE_ROW_MISSING` | `EXTEND_RECOMPUTE_RANGE` — add more source data |

---

## Safety constraints

- Read-only: does not modify any mappings, labels, or thresholds
- No DB writes
- No broker calls
- No order creation
- No BUY_READY signals
- `research_only=True` on every output row and in manifest

---

## Relationship to other reports

| Report | Role |
|---|---|
| `event_level_symbol_reaction_profile_by_context_v1` | **Upstream** — event-level rows being diagnosed |
| `historical_market_breath_source_recompute_v1` | Source of raw phase/state/score data |
| `context_event_coverage_gap_audit_v1` | **Downstream consumer** — feeds breath coverage counts |
| `symbol_reaction_profile_from_event_level_context_v1` | Would benefit from better breath classification |
