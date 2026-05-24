# Rotation Destination Regime Interaction Audit V1

## Purpose

`rotation_destination_regime_interaction_audit_v1` joins:

- destination-dedup rotation replay events from `rotation_destination_historical_replay_audit_v2`
- discovered regimes from `market_regime_discovery_v1`

The join key is `sample_ts_utc`.

The goal is to measure destination outcomes by:

- symbol
- curve sanity state
- legacy `confidence_bucket`
- included/excluded state
- discovered regime

## Scope And Boundaries

- research-only
- file input only
- no DB required
- no DB writes
- no broker
- no account
- no orders
- no dashboard
- no `selection_engine`
- no `decision_gate`
- no `execution_planner`
- no `executor`
- no label tuning
- no destructive column renames

Generated outputs are written under ignored run directories:

```text
data/research/rotation_destination_regime_interaction_audit_v1/run_<YYYYMMDDTHHMMSSZ>/
```

## Inputs

Rotation replay input:

```text
data/research/rotation_destination_historical_replay_audit_v2/run_<RUN>/event_table_dedup_destination_historical_replay_v2.csv
```

Discovered regime input:

```text
data/research/market_regime_discovery_v1/run_<RUN>/discovered_regime_samples_v1.csv
```

## Terminology

- `confidence_bucket` is legacy bucket naming retained for backward compatibility.
- `measurement_coverage_score` is coverage or measurement availability only.
- `measurement_coverage_score` is not trend probability.
- `measurement_coverage_score` is not phase stability.
- `breath` means rhythm, phase, or waveform context.
- `participation` is preferred language for cross-asset participation context.

## CLI

```bash
python -m src.research.run_rotation_destination_regime_interaction_audit_v1 --help
```

Arguments:

- `--rotation-run-dir`
- `--regime-run-dir`
- `--write-files` / `--no-write-files`
- `--output-root`

## Outputs

- `summary_symbol_curve_regime_v1.csv`
- `summary_symbol_confidence_regime_v1.csv`
- `summary_curve_regime_v1.csv`
- `summary_confidence_regime_v1.csv`
- `summary_included_regime_v1.csv`
- `summary_symbol_included_regime_v1.csv`
- `manifest_v1.json`

## Summary Metrics

Each summary output reports grouped destination outcomes with:

- event count
- included count
- excluded count
- average `measurement_coverage_score`
- average and median 24h return
- 24h positive rate
- average 48h return
- average forward max 24h return
- average forward min 24h return

Included/excluded state is derived from `excluded_reason`:

- empty `excluded_reason` -> `INCLUDED`
- non-empty `excluded_reason` -> `EXCLUDED`

## Smoke Example

```bash
python -m src.research.run_rotation_destination_regime_interaction_audit_v1 \
  --rotation-run-dir data/research/rotation_destination_historical_replay_audit_v2/run_20260524T042242Z \
  --regime-run-dir data/research/market_regime_discovery_v1/run_20260524T034432Z \
  --write-files \
  --output table
```
