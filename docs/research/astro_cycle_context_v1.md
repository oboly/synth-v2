# Astro Cycle Context V1

## Purpose

`astro_cycle_context_v1` builds an external lunar and solar cycle feature dataset from timestamps only.

This dataset is for research joins only. It is **not** a trading signal and must not be promoted into market decision logic from this v1.

## Scope And Boundaries

- research-only
- external context only
- no market decision logic
- no `selection_engine` changes
- no `decision_gate` changes
- no `execution_planner` changes
- no `executor` changes
- no broker, account, order, or dashboard inputs
- no DB writes

The runner is DB-free. It uses only the requested timestamp range and interval.

Generated outputs are written under ignored run directories:

```text
data/research/astro_cycle_context_v1/run_<YYYYMMDDTHHMMSSZ>/
```

## Features

Per `sample_ts_utc` the runner emits:

- `moon_phase_fraction`
- `moon_age_days`
- `moon_illumination_pct`
- `days_to_new_moon`
- `days_to_full_moon`
- `lunar_quarter`
- `solar_day_of_year`
- `seasonal_phase_fraction`
- `equinox_solstice_phase`

## Notes

- Lunar values use deterministic astronomical approximations from timestamps only.
- Seasonal phase is a normalized yearly cycle anchored around the March equinox.
- This v1 is an external context dataset, not validated alpha and not a runtime signal.

## CLI

```bash
python -m src.research.run_astro_cycle_context_v1 --help
```

Arguments:

- `--start-ts`
- `--end-ts`
- `--interval`
- `--write-files` / `--no-write-files`
- `--output-root`

## Output Files

- `astro_cycle_context_v1.csv`
- `astro_cycle_context_v1.jsonl`
- `manifest_v1.json`

## Smoke Example

```bash
python -m src.research.run_astro_cycle_context_v1 \
  --start-ts 2026-04-01T00:00:00Z \
  --end-ts 2026-05-23T23:59:59Z \
  --interval 4h \
  --write-files \
  --output table
```
