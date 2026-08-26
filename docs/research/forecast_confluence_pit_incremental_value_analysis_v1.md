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

**Retained-call directional effect: zero.** Whenever both modes make a non-neutral call on the same forecast identity + horizon, they agree on direction 100% of the time in this cohort, so return/MFE/MAE deltas among retained calls are exactly zero. This channel provides no evidence of incremental value.

## Abstention / neutralization effect (measured separately)

Rotation Pressure and sector context change some baseline calls to NEUTRAL rather than changing the direction of calls that remain active. This section asks whether those neutralized calls were systematically worse than the calls the enriched mode retains -- the only channel through which this enrichment could plausibly add value, given the zero retained-call effect above.

- baseline_non_neutral_outcome_count: 8081
- retained_outcome_count: 7667
- neutralized_outcome_count: 414
- other_outcome_count: 0
- neutralization_rate: 0.0512
- baseline_non_neutral_unique_forecast_count: 2723
- retained_unique_forecast_count: 2585
- neutralized_unique_forecast_count: 138

- retained_metrics: {'sample_count': 7667, 'direction_hit_rate': 0.4882, 'mean_forward_return_pct': -1.7225, 'median_forward_return_pct': -0.0439, 'positive_return_rate': 0.4882, 'mean_mfe_pct': 3.3942, 'mean_mae_pct': 5.8519}
- neutralized_metrics: {'sample_count': 414, 'direction_hit_rate': 0.5845, 'mean_forward_return_pct': -0.0117, 'median_forward_return_pct': 0.3566, 'positive_return_rate': 0.5845, 'mean_mfe_pct': 4.3857, 'mean_mae_pct': 4.083}
- neutralized_minus_retained: {'direction_hit_rate': 0.0963, 'mean_forward_return_pct': 1.7108, 'median_forward_return_pct': 0.4005, 'positive_return_rate': 0.0963, 'mean_mfe_pct': 0.9915, 'mean_mae_pct': -1.7689}
- bootstrap CI (neutralized - retained mean return): {'a_n': 7667, 'b_n': 414, 'ci_95': [0.8216, 2.5728], 'seed': 1234, 'resamples': 2000}

- by_time_half stable: True
- by_horizon stable: True

- attribution counts: {'both_either_sufficient': 21, 'both_interaction_required': 36, 'rotation_pressure_only': 264, 'sector_rotation_only': 93}
- attribution note: attribution is a counterfactual single-feature ablation via the canonical assess() function (approximate due to weight renormalization by present-feature weight sum), not a persisted ground-truth field

- abstention_effect recommendation: **REJECT_FEATURE_ADDITION**
- neutralized_minus_retained mean_forward_return_pct=1.7108 (bootstrap CI=[0.8216, 2.5728]) shows neutralized calls are not worse than retained calls; enrichment provides no abstention value on this cohort

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

**REJECT_FEATURE_ADDITION**

retained-call effect: paired mean_return_delta_pct=0.0 with bootstrap 95% CI=[0.0, 0.0] does not exclude zero; effect is not distinguishable from noise on the fixed cohort | abstention effect (decisive channel): neutralized_minus_retained mean_forward_return_pct=1.7108 (bootstrap CI=[0.8216, 2.5728]) shows neutralized calls are not worse than retained calls; enrichment provides no abstention value on this cohort

