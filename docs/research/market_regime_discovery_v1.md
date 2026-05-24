# Market Regime Discovery V1

## Purpose

`market_regime_discovery_v1` discovers recurring market regimes from scratch using market-only historical data.

This runner does **not** use:

- existing regime labels as discovery input
- A+ labels as discovery input
- `paper_advice`
- account, broker, order, or dashboard data

V1 is exploratory discovery. It may use the full selected history window to learn clusters. It does **not** claim replay-safe predictive use yet.

## Scope And Boundaries

- research-only
- market-only
- db read-only
- no broker calls
- no broker writes
- no order submission
- no dashboard changes
- no `selection_engine` changes
- no `decision_gate` changes
- no `execution_planner` changes
- no `executor` changes

Generated outputs are written under ignored run directories:

```text
data/research/market_regime_discovery_v1/run_<YYYYMMDDTHHMMSSZ>/
```

## Inputs

Primary input:

- `obs_market_candle` 4h candles

Optional comparison only after clustering:

- existing market-breath labels derived from the same market-only candle history

Those existing labels are joined only after clustering to produce comparison files. They are not used as discovery inputs.

Terminology note:

- if downstream comparison work references `market_breath_confidence`, treat it as coverage or measurement availability only
- do not interpret it as trend probability, phase stability, or forward-return confidence

## Discovery Outline

For each sampled timestamp:

1. Compute market-level candle features.
2. Compute alt breadth features.
3. Compute BTC, ETH, and alt-basket relative features.
4. Compute normalized rolling-window shape features.
5. Cluster recurring patterns into discovered regimes.
6. Measure forward 24h outcomes for BTC, the alt basket, and top/bottom deciles.
7. Compare discovered clusters against existing regime and curve-sanity labels only after clustering.

## CLI

```bash
python -m src.research.run_market_regime_discovery_v1 --help
```

Arguments:

- `--venue`
- `--interval`
- `--start-ts`
- `--end-ts`
- `--lookback-windows`
  - rolling windows in candles
  - accepts spaced values like `6 18 42 84`
  - accepts comma-separated input like `6,18,42,84`
- `--sample-every-n`
- `--max-samples`
  - `0` means unlimited
- `--n-regimes`
- `--write-files` / `--no-write-files`
- `--output-root`

## Output Files

- `discovered_regime_samples_v1.csv`
- `discovered_regime_samples_v1.jsonl`
- `summary_by_discovered_regime_v1.csv`
- `regime_feature_centers_v1.csv`
- `regime_forward_outcomes_v1.csv`
- `regime_transition_matrix_v1.csv`
- `comparison_discovered_vs_existing_regime_v1.csv`
- `comparison_discovered_vs_curve_sanity_v1.csv`
- `manifest_v1.json`

## Sample Fields

Core sample outputs include:

- `sample_ts_utc`
- `discovered_regime_id`
- `discovered_regime_label_auto`
- `cluster_distance`
- `btc_return_24h`
- `btc_return_72h`
- `btc_volatility_7d`
- `alt_breadth_positive_pct`
- `alt_equal_weight_return_24h`
- `alt_dispersion`
- `eth_btc_relative_strength`
- `forward_btc_return_24h`
- `forward_alt_basket_return_24h`
- `forward_top_decile_return_24h`
- `forward_bottom_decile_return_24h`

## Manifest Expectations

`manifest_v1.json` includes:

- `db_writes=0`
- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- exploratory-only notes
- output paths

## Smoke Example

```bash
python -m src.research.run_market_regime_discovery_v1 \
  --venue bitvavo \
  --interval 4h \
  --start-ts 2026-05-01T00:00:00Z \
  --end-ts 2026-05-31T23:59:59Z \
  --lookback-windows 6 18 42 84 \
  --sample-every-n 6 \
  --max-samples 20 \
  --n-regimes 6 \
  --write-files \
  --output table
```

## Interpretation Notes

- Discovered regime IDs are clustering artifacts, not production policy states.
- Auto labels are descriptive summaries of cluster centers, not hand-tuned runtime labels.
- Comparison files are diagnostic only. They help show how discovered clusters overlap with existing regime and curve-sanity labels without using those labels as discovery input.
