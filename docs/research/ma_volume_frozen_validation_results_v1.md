# MA / Volume Frozen Validation Results v1

Issue: #310

Status: completed empirical disposition for the frozen #661/#684 temporal substrate.

## Frozen inputs

- population rows: 19,520
- population as-ofs: 45
- population SHA256: `61bab264b2921b93a25a22ec0d12cbc031ad0ef234fa989b2ea43c894bc263b4`
- outcomes rows: 58,560
- outcomes SHA256: `2c1b3b9e17e6e06eec3831ac47b48bfd91944730cf9c6e75929979a795727500`
- horizons: 1h, 4h, 24h
- runner merge commit: `1c31fa532ca352fa400a124db733f2499af5120b`

## Runtime gates

- bounded candle query EXPLAIN used `ix_market_candle_lookup`, range scan, `Using index condition`
- one-observation ADA smoke: PASS
- 25-observation smoke: PASS
- SIGINT interruption + exact-scope `--resume`: PASS
- full 19,520-row / 45-asof frozen run: PASS
- DB writes: 0
- full-run candidate artifact SHA256: `01eca1ec56adaa9d4e10599b2e210dd0628c33d7d3ff8c0dbeb273b90f429c4b`
- validation rows SHA256:
  - 1h: `b691c58bad2e137c0b4051ac6e340cf23b83a7453e23bd59995d80f1432c5343`
  - 4h: `5b52d6f740e0d1b2348946ab80e3c7cb26d8b3dbec698f7b6752f09c513da54f`
  - 24h: `7ed5c50a8524dbca6092b4d8e255b06eb075ee0927b25bedab3a08064b2c6d15`

## Historical availability

Candidate status counts across the frozen population:

- AVAILABLE: 6,636
- INSUFFICIENT_CANDLE_HISTORY: 3,061
- MISSING_EXACT_ASOF_CANDLE: 533
- NONCONTIGUOUS_CANDLE_HISTORY: 9,290

Only 34.0% of frozen observations were feature-available. Historical 4h gaps are therefore a material limitation and must not be hidden by imputation or denominator changes.

## Split-stability result

The MA distance and slope family does not generalize consistently across chronological splits.

Validation split correlations are strongly positive for several MA features, but discovery and holdout are mostly negative or near zero. Examples using baseline-controlled partial Spearman:

- `close_vs_sma50_pct`, 4h: discovery -0.088, validation +0.292, holdout -0.232
- `close_vs_sma150_pct`, 4h: discovery -0.080, validation +0.279, holdout -0.189
- `close_vs_sma200_pct`, 4h: discovery -0.088, validation +0.269, holdout -0.139
- `sma50_slope_pct_6b`, 4h: discovery -0.041, validation +0.315, holdout -0.212

This sign reversal is incompatible with promotion as a stable predictive ranking feature.

`bullish_ma_stack` is weak/inconsistent across horizons and splits and does not justify a predictive threshold contract.

`volume_ratio_20` is the only candidate with notable holdout signal, especially at 24h:

- 24h discovery: -0.031
- 24h validation: +0.084
- 24h holdout: +0.292

Because discovery is negative and the effect is horizon/time dependent, this is not promotion-grade evidence. It remains a separate research candidate.

## Disposition

| Candidate | Disposition | Reason |
| --- | --- | --- |
| `close_vs_sma50_pct` | REJECT | split-sign instability |
| `close_vs_sma150_pct` | REJECT | split-sign instability |
| `close_vs_sma200_pct` | REJECT | split-sign instability |
| `sma50_slope_pct_6b` | REJECT | split-sign instability |
| `sma150_slope_pct_6b` | REJECT | weak/inconsistent holdout |
| `sma200_slope_pct_6b` | REJECT | weak/inconsistent holdout |
| `bullish_ma_stack` | REJECT | weak/inconsistent predictive evidence |
| `volume_ratio_20` | RESEARCH_FURTHER | horizon-/regime-dependent holdout signal |

## Architecture consequence

No MA candidate from this run is promoted into `selection_engine`.

No deterministic predictive stoplight/classification thresholds are defined from this dataset because the underlying MA feature family failed chronological split stability. Defining thresholds anyway would convert an empirical negative result into presentation-driven authority.

MA breadth may remain useful as descriptive market context, but this run does not validate SMA150/SMA200/bullish-stack breadth as predictive ranking evidence. Any future breadth/reporting work must remain market-only and account-agnostic and must not inherit predictive authority from this result.

`volume_ratio_20` follow-up, if pursued, belongs in a separate research issue focused on horizon/regime conditioning and independent replication. It must not modify #310's frozen result.

## Safety

```text
research_only=1
market_only=1
db_writes=0
production_ranking_changes=0
selection_engine=none
decision_gate=none
execution_planner=none
executor=none
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
live_activation=0
```
