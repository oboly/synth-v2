# Forecast Confluence PIT Incremental-Value Analysis v1

Analysis version: `forecast_confluence_pit_incremental_value/v1`
Period: 2026-07-31T00:00:00Z to 2026-08-18T00:00:00Z (venue=bitvavo)

## Canonical ledger digests

- forecast: `862fb3a2df8611e1382447da5e3ecadfcda68de7086a98caa4b729e4ebb7692b`
- baseline: `85a01b801b7936daed5ba58e3110dd58b3078db1ddab4231fee47c8daef5d1de`
- enriched: `10fccecebd7d812c57264e0e33d3f4c7eec16ab47a3bae7b836e2d5da15f8e85`
- identity_guard: canonical_only_count=0 reconstructed_only_count=0

## Overall

- baseline: {'sample_count': 8081, 'direction_hit_rate': 0.4931, 'mean_forward_return_pct': -1.6349, 'median_forward_return_pct': -0.0267, 'positive_return_rate': 0.4931, 'mean_mfe_pct': 3.445, 'mean_mae_pct': 5.7613}
- enriched: {'sample_count': 7844, 'direction_hit_rate': 0.4884, 'mean_forward_return_pct': -1.6983, 'median_forward_return_pct': -0.0432, 'positive_return_rate': 0.4884, 'mean_mfe_pct': 3.4356, 'mean_mae_pct': 5.8442}

## Strict paired comparison

Paired identity contract: `['venue', 'market', 'forecast_as_of_utc', 'map_id', 'horizon_hours', 'endpoint_close_ts_utc']`

- paired_outcome_count: 7667
- mean_return_delta_pct: 0.0
- median_return_delta_pct: 0.0
- direction_hit_delta_rate: 0.0
- mean_mfe_delta_pct: 0.0
- mean_mae_delta_pct: 0.0
- improved_count: 0
- worsened_count: 0
- unchanged_count: 7667

Aggregate unpaired counts alone are not treated as evidence of incremental value; the paired comparison above is the primary evidence.

## Coverage

- rotation_pressure: {'available_count': 4485, 'unavailable_count': 3596, 'available_rate': 0.555}
- sector_rotation: {'available_count': 4260, 'unavailable_count': 3821, 'available_rate': 0.5272}

## Confidence semantics

- baseline HIGH behaves as: **expected-return quality**
- enriched HIGH behaves as: **expected-return quality**

## Independent value

- rotation_pressure: no_independent_value_detected
- sector_rotation: no_independent_value_detected

## Time-split stability

- stable: True
- first_half paired: {'paired_outcome_count': 2163, 'mean_return_delta_pct': 0.0, 'median_return_delta_pct': 0.0, 'direction_hit_delta_rate': 0.0, 'mean_mfe_delta_pct': 0.0, 'mean_mae_delta_pct': 0.0, 'improved_count': 0, 'worsened_count': 0, 'unchanged_count': 2163}
- second_half paired: {'paired_outcome_count': 5504, 'mean_return_delta_pct': 0.0, 'median_return_delta_pct': 0.0, 'direction_hit_delta_rate': 0.0, 'mean_mfe_delta_pct': 0.0, 'mean_mae_delta_pct': 0.0, 'improved_count': 0, 'worsened_count': 0, 'unchanged_count': 5504}

## Bootstrap (paired mean return delta, 95% CI)

- ci_95: [0.0, 0.0] (seed=1234, resamples=2000, n=7667)

## Future-leakage assertion

- {'asserted': True, 'join_operator': 'feature_asof <= forecast_asof', 'freshness_hours': 4, 'later_feature_rows_used': 0, 'current_state_substitution': False, 'breathline_used': False}

## Recommendation

**KEEP_RESEARCH_ONLY**

paired mean_return_delta_pct=0.0 with bootstrap 95% CI=[0.0, 0.0] does not exclude zero; effect is not distinguishable from noise on the fixed cohort

