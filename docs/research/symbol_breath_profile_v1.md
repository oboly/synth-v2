# Symbol Breath Profile V1

## Purpose

`symbol_breath_profile_v1` classifies symbol behavior from historical interaction summaries produced by `rotation_destination_regime_interaction_audit_v1`.

This lane is descriptive research only. It does not create trade advice and does not tune live logic.

## Inputs

The runner reads these files from one local interaction-audit run directory:

- `summary_symbol_curve_regime_v1.csv`
- `summary_symbol_confidence_regime_v1.csv`
- `summary_symbol_included_regime_v1.csv`

## Scope And Boundaries

- research-only
- file input only
- no DB
- no broker
- no account
- no orders
- no dashboard
- no `selection_engine`
- no `decision_gate`
- no `execution_planner`
- no `executor`
- no live logic tuning
- no trade advice

Generated outputs are written under ignored run directories:

```text
data/research/symbol_breath_profile_v1/run_<YYYYMMDDTHHMMSSZ>/
```

## Terminology

- `breath` means rhythm, phase, or waveform context.
- `participation` is preferred language for cross-asset participation context.
- `confidence_bucket` is legacy naming retained for backward compatibility.
- `measurement_coverage_score` is coverage or measurement availability only.
- `measurement_coverage_score` is not trend confidence.
- `measurement_coverage_score` is not phase stability.

## CLI

```bash
python -m src.research.run_symbol_breath_profile_v1 --help
```

Arguments:

- `--interaction-run-dir`
- `--min-events`
- `--write-files` / `--no-write-files`
- `--output-root`

Default:

- `--min-events 10`

## Output Files

- `symbol_breath_profile_v1.csv`
- `symbol_breath_profile_v1.jsonl`
- `profile_evidence_v1.csv`
- `manifest_v1.json`

## Suggested Profile Labels

- `REBOUND_RESPONDER`
- `DAMAGE_REBOUND_RESPONDER`
- `CONFIRMED_CONTINUATION`
- `LATE_EXPANSION_TRAP`
- `REGIME_SENSITIVE`
- `INCOHERENT`
- `INSUFFICIENT_SAMPLE`

## Heuristic Intent

The runner uses grouped historical interaction summaries to describe recurring symbol behavior.

Examples:

- positive response during weak curve states may map to `REBOUND_RESPONDER`
- positive response during damage states may map to `DAMAGE_REBOUND_RESPONDER`
- positive response under `CURVE_UP_CONFIRMED` plus stronger legacy continuation buckets may map to `CONFIRMED_CONTINUATION`
- mixed outcomes across multiple discovered regimes may map to `REGIME_SENSITIVE`
- weak or contradictory evidence stays `INCOHERENT`
- low event count stays `INSUFFICIENT_SAMPLE`

These labels are research summaries only.

## Smoke Example

```bash
python -m src.research.run_symbol_breath_profile_v1 \
  --interaction-run-dir data/research/rotation_destination_regime_interaction_audit_v1/run_20260524T060422Z \
  --min-events 10 \
  --write-files \
  --output table
```
