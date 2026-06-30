# Breathline V2 Canonical Campaign Result V1

## 1. Campaign Identity

| Field | Value |
|---|---|
| Run timestamp | 2026-06-30T07:01:08Z |
| Git commit | 657187cb251b1204e5f09b4fd019a84a95dd3b87 |
| Input path | `/home/gurk/projects/synth-v2-breathline-baseline-replay/data/research/breathline_backtest_campaign_v1/canonical_28_anchor_replay_20260627T124411Z/partial_to_full/breath_curve_partial_to_full_v1_20260627T124411Z.jsonl` |
| Input SHA256 | `5b4be7a17a81138a3d9a156e02032ab50c4cb948e66aa58a231283ba3d30b6d5` |
| Output archive | `data/research/breathline_lattice_shift_calibration_v2/breathline_v2_canonical_28_anchor_8_asset_20260630T065259Z/` |
| Assets (8) | BTC, ETH, FIL, HBAR, PEPE, RENDER, TAO, XLM |
| Anchor count | 28 |
| Residual modes | STRICT (12h), NORMAL (18h), MAX (24h) |
| Candle source | `db_read_only_obs_market_candle` |
| DB-read count | 8 (one per symbol) |
| DB writes | 0 |
| Broker calls | 0 |

## 2. Completeness Checks

### Expected vs actual row counts

| Dimension | Expected | Actual |
|---|---|---|
| Symbols | 8 | 8 |
| Anchors | 28 | 28 |
| Modes | 3 | 3 |
| Total top-candidate rows (8 × 28 × 3) | 672 | 672 |
| Total shift candidate rows (22 shifts × 8 × 28 × 3) | 14 784 | 14 784 |
| Total base marker rows (14 784 × 6) | 88 704 | 88 704 |
| Input JSONL rows accepted (status=OK) | 448 | 448 |
| Input JSONL rows skipped | 0 | 0 |

All 28 anchors are present for all 8 symbols across all three modes. No missing data.

### Anchor date range

First anchor: 2024-10-13T00:00:00Z
Last anchor: 2026-05-03T00:00:00Z

## 3. Winner and Tie Summary

All epochs: 28 per (symbol, mode).

| Symbol | Mode | Unique | Tied | Unique rate | Tie rate |
|---|---|---|---|---|---|
| BTC | STRICT | 8 | 20 | 28.6% | 71.4% |
| BTC | NORMAL | 9 | 19 | 32.1% | 67.9% |
| BTC | MAX | 11 | 17 | 39.3% | 60.7% |
| ETH | STRICT | 11 | 17 | 39.3% | 60.7% |
| ETH | NORMAL | 11 | 17 | 39.3% | 60.7% |
| ETH | MAX | 11 | 17 | 39.3% | 60.7% |
| FIL | STRICT | 15 | 13 | 53.6% | 46.4% |
| FIL | NORMAL | 15 | 13 | 53.6% | 46.4% |
| FIL | MAX | 16 | 12 | 57.1% | 42.9% |
| HBAR | STRICT | 18 | 10 | 64.3% | 35.7% |
| HBAR | NORMAL | 18 | 10 | 64.3% | 35.7% |
| HBAR | MAX | 21 | 7 | 75.0% | 25.0% |
| PEPE | STRICT | 13 | 15 | 46.4% | 53.6% |
| PEPE | NORMAL | 14 | 14 | 50.0% | 50.0% |
| PEPE | MAX | 16 | 12 | 57.1% | 42.9% |
| RENDER | STRICT | 15 | 13 | 53.6% | 46.4% |
| RENDER | NORMAL | 16 | 12 | 57.1% | 42.9% |
| RENDER | MAX | 19 | 9 | 67.9% | 32.1% |
| TAO | STRICT | 15 | 13 | 53.6% | 46.4% |
| TAO | NORMAL | 15 | 13 | 53.6% | 46.4% |
| TAO | MAX | 19 | 9 | 67.9% | 32.1% |
| XLM | STRICT | 14 | 14 | 50.0% | 50.0% |
| XLM | NORMAL | 16 | 12 | 57.1% | 42.9% |
| XLM | MAX | 20 | 8 | 71.4% | 28.6% |

**Cross-mode totals (224 epochs per mode):**

| Mode | Unique | Tied | Unique rate | Tie rate |
|---|---|---|---|---|
| STRICT | 109 | 115 | 48.7% | 51.3% |
| NORMAL | 114 | 110 | 50.9% | 49.1% |
| MAX | 133 | 91 | 59.4% | 40.6% |

Avg matched base marker count: 6/6 across all modes (all six base markers matched for every candidate, as all 4 928 base marker slots were filled with matched entries per mode).

## 4. Shift Distribution

Selected shifts for unique winners only. All observations span the full grid range [-10.5, +10.0].

| Symbol | Mode | Unique count | Most common shift | Min | Max |
|---|---|---|---|---|---|
| BTC | STRICT | 8 | 7.0 (×1) | -9.0 | 7.0 |
| BTC | NORMAL | 9 | 5.0 (×2) | -9.0 | 7.0 |
| BTC | MAX | 11 | 5.0 (×3) | -9.0 | 7.0 |
| ETH | STRICT | 11 | 1.0 (×2) | -10.5 | 9.0 |
| ETH | NORMAL | 11 | 1.0 (×2) | -10.5 | 9.0 |
| ETH | MAX | 11 | 1.0 (×2) | -10.5 | 9.0 |
| FIL | STRICT | 15 | -9.0 (×3) | -10.5 | 10.0 |
| FIL | NORMAL | 15 | -9.0 (×3) | -10.5 | 10.0 |
| FIL | MAX | 16 | -9.0 (×3) | -10.5 | 10.0 |
| HBAR | STRICT | 18 | -10.5 (×2) | -10.5 | 7.0 |
| HBAR | NORMAL | 18 | -10.5 (×2) | -10.5 | 7.0 |
| HBAR | MAX | 21 | 1.0 (×3) | -10.5 | 10.0 |
| PEPE | STRICT | 13 | -3.0 (×2) | -10.5 | 10.0 |
| PEPE | NORMAL | 14 | -3.0 (×2) | -10.5 | 10.0 |
| PEPE | MAX | 16 | -3.0 (×2) | -10.5 | 10.0 |
| RENDER | STRICT | 15 | 5.0 (×2) | -10.5 | 10.0 |
| RENDER | NORMAL | 16 | -3.0 (×2) | -10.5 | 10.0 |
| RENDER | MAX | 19 | 10.0 (×3) | -10.5 | 10.0 |
| TAO | STRICT | 15 | 7.0 (×3) | -10.5 | 10.0 |
| TAO | NORMAL | 15 | 7.0 (×3) | -10.5 | 10.0 |
| TAO | MAX | 19 | 7.0 (×3) | -10.5 | 10.0 |
| XLM | STRICT | 14 | 10.0 (×2) | -10.5 | 10.0 |
| XLM | NORMAL | 16 | 10.0 (×3) | -10.5 | 10.0 |
| XLM | MAX | 20 | 10.0 (×3) | -10.5 | 10.0 |

Most symbols produce a wide spread of selected shifts across the 28-anchor window. No single shift value dominates across all symbols or anchors, indicating that tied outcomes account for the majority of epochs under STRICT and NORMAL (51.3% and 49.1% tie rate respectively).

## 5. Effective Cycle Spacing

Computed for consecutive unique-winner pairs per (symbol, mode). `effective_cycle_spacing_days = raw_anchor_spacing_days + raw_shift_delta_days`. The raw anchor spacing is always 21d between consecutive anchors.

| Mode | Consecutive pairs | Min spacing (d) | Median spacing (d) | Max spacing (d) | Exceeds 3d alert |
|---|---|---|---|---|---|
| STRICT | 101 | 0.5 | 34.0 | 208.0 | 77 (76.2%) |
| NORMAL | 106 | 0.5 | 32.8 | 208.0 | 84 (79.2%) |
| MAX | 125 | 0.5 | 29.0 | 137.0 | 101 (80.8%) |

The median effective cycle spacing is above 21d for all modes, driven by shift changes from epoch to epoch. The continuity-alert threshold (3d shift delta) is exceeded for the majority of consecutive pairs. This reflects the wide spread of selected shifts across the grid rather than a stable shift trajectory within any given symbol.

Long spacing gaps (e.g. 208d) arise when several consecutive epochs are tied (no selected shift), so consecutive pairs skip multiple anchors. The minimum of 0.5d is theoretically possible when shift changes from +10.5→-10.5 across adjacent anchors (not observed here; 0.5d minimum arises from e.g. anchor spacing 21d + shift delta -20.5d from -10.5 to +10.0 → 0.5d).

## 6. Base Marker Evidence

All base markers are fully matched across all candidates and all modes. No unmatched base marker slot exists in any of the 88 704 base marker rows.

| Marker | Mode | Matched | Unmatched | Median residual (h) | Max residual (h) |
|---|---|---|---|---|---|
| FIRST_LIFT_HIGH | STRICT | 4 928 | 0 | 0.0 | 10.9 |
| FIRST_DIP_LOW | STRICT | 4 928 | 0 | 0.0 | 11.5 |
| SECOND_PEAK_RETEST_HIGH | STRICT | 4 928 | 0 | 0.0 | 12.0 |
| SECOND_DIP_HIGHER_LOW | STRICT | 4 928 | 0 | 0.0 | 11.5 |
| IGNITION_PRE_SPIKE | STRICT | 4 928 | 0 | 0.0 | 11.9 |
| MAIN_PULSE_TP_HIGH | STRICT | 4 928 | 0 | 0.0 | 12.0 |
| FIRST_LIFT_HIGH | NORMAL | 4 928 | 0 | 0.0 | 13.1 |
| FIRST_DIP_LOW | NORMAL | 4 928 | 0 | 0.0 | 12.5 |
| SECOND_PEAK_RETEST_HIGH | NORMAL | 4 928 | 0 | 0.0 | 12.0 |
| SECOND_DIP_HIGHER_LOW | NORMAL | 4 928 | 0 | 0.0 | 12.5 |
| IGNITION_PRE_SPIKE | NORMAL | 4 928 | 0 | 0.0 | 12.1 |
| MAIN_PULSE_TP_HIGH | NORMAL | 4 928 | 0 | 0.0 | 12.0 |
| FIRST_LIFT_HIGH | MAX | 4 928 | 0 | 0.0 | 22.9 |
| FIRST_DIP_LOW | MAX | 4 928 | 0 | 0.0 | 23.5 |
| SECOND_PEAK_RETEST_HIGH | MAX | 4 928 | 0 | 0.0 | 24.0 |
| SECOND_DIP_HIGHER_LOW | MAX | 4 928 | 0 | 0.0 | 23.5 |
| IGNITION_PRE_SPIKE | MAX | 4 928 | 0 | 0.0 | 23.9 |
| MAIN_PULSE_TP_HIGH | MAX | 4 928 | 0 | 0.0 | 24.0 |

All 14 784 candidates match all 6 base markers in every mode. The median residual is 0.0 across every marker and mode, meaning the majority of expected marker timestamps fall within the daily candle interval and incur zero residual. Max residuals reach the tolerance ceiling under STRICT (≤12h), are slightly above that for NORMAL (reflecting that some candles match at residuals 12–13h, within the 18h tolerance), and reach up to 24.0h under MAX.

The sensitivity consistency is therefore not what distinguishes modes: the winner/tie rate differences arise from the shift ranking (which shifts produce a strict ranking victory vs equal-ranked ties), not from whether individual markers are matched or unmatched.

## 7. Base Shape Validity

| Symbol | Mode | Unique winners | All rules passed | All-pass rate | Min rules passed |
|---|---|---|---|---|---|
| BTC | STRICT | 8 | 8 | 100% | 8 |
| BTC | NORMAL | 9 | 9 | 100% | 8 |
| BTC | MAX | 11 | 10 | 91% | 7 |
| ETH | STRICT | 11 | 9 | 82% | 6 |
| ETH | NORMAL | 11 | 9 | 82% | 6 |
| ETH | MAX | 11 | 10 | 91% | 7 |
| FIL | STRICT | 15 | 12 | 80% | 7 |
| FIL | NORMAL | 15 | 12 | 80% | 7 |
| FIL | MAX | 16 | 15 | 94% | 7 |
| HBAR | STRICT | 18 | 15 | 83% | 7 |
| HBAR | NORMAL | 18 | 15 | 83% | 7 |
| HBAR | MAX | 21 | 17 | 81% | 7 |
| PEPE | STRICT | 13 | 10 | 77% | 6 |
| PEPE | NORMAL | 14 | 12 | 86% | 6 |
| PEPE | MAX | 16 | 15 | 94% | 6 |
| RENDER | STRICT | 15 | 9 | 60% | 6 |
| RENDER | NORMAL | 16 | 11 | 69% | 7 |
| RENDER | MAX | 19 | 15 | 79% | 7 |
| TAO | STRICT | 15 | 12 | 80% | 7 |
| TAO | NORMAL | 15 | 13 | 87% | 7 |
| TAO | MAX | 19 | 17 | 89% | 7 |
| XLM | STRICT | 14 | 14 | 100% | 8 |
| XLM | NORMAL | 16 | 15 | 94% | 7 |
| XLM | MAX | 20 | 18 | 90% | 7 |

Overall all-rules-passed counts: STRICT 89/109 (81.7%), NORMAL 96/114 (84.2%), MAX 117/133 (88.0%).

Most common failed rules across unique winners (STRICT mode):

| Shape rule | Fails / total |
|---|---|
| first_lift_above_origin_reference | 7 / 109 |
| pulse_above_ignition | 5 / 109 |
| pulse_above_second_peak | 4 / 109 |
| second_dip_higher_than_first_dip | 3 / 109 |
| ignition_above_second_dip | 3 / 109 |
| first_dip_below_first_lift | 1 / 109 |

MAIN_PULSE_TP_HIGH not above SECOND_PEAK_RETEST_HIGH (pulse_above_second_peak fails):
- STRICT: 4 / 109
- NORMAL: 5 / 114
- MAX: 6 / 133

SECOND_DIP_HIGHER_LOW not above FIRST_DIP_LOW (second_dip_higher_than_first_dip fails):
- STRICT: 3 / 109
- NORMAL: 3 / 114
- MAX: 4 / 133

All counts refer to scheduled marker slots and observed candle prices at those slots. Shape rules are structural comparisons between observed prices at the assigned scheduled slots; they do not validate semantic market phases.

## 8. Extension Evidence

Extension markers are evaluated only for unique base-shift winners. They are not used in base ranking.

| Extension | Mode | Observed / total | Median residual (h) | Max residual (h) |
|---|---|---|---|---|
| EXTENSION_1.272 | STRICT | 109 / 109 | 0.0 | 0.0 |
| EXTENSION_1.618 | STRICT | 109 / 109 | 0.0 | 0.0 |
| EXTENSION_2.618 | STRICT | 108 / 109 | 0.0 | 0.0 |
| EXTENSION_1.272 | NORMAL | 114 / 114 | 0.0 | 0.0 |
| EXTENSION_1.618 | NORMAL | 114 / 114 | 0.0 | 0.0 |
| EXTENSION_2.618 | NORMAL | 113 / 114 | 0.0 | 0.0 |
| EXTENSION_1.272 | MAX | 133 / 133 | 0.0 | 0.0 |
| EXTENSION_1.618 | MAX | 133 / 133 | 0.0 | 0.0 |
| EXTENSION_2.618 | MAX | 131 / 133 | 0.0 | 0.0 |

All observed extension residuals are 0.0h. This is mathematically expected: `ratio × cycle_days` for ratios 1.272, 1.618, and 2.618 gives ~26.71d, ~33.98d, and ~54.98d, all of which land at a fractional hour within the daily candle window (24h candle, half-open), so `calculate_candle_residual_hours` returns 0 for all matched extension slots.

Near-perfect observation rates (1 or 2 unobserved per mode across 8 assets × 28 anchors) reflect the high match rate of the base-layer winners. The few unobserved cases at EXTENSION_2.618 occur where the expected timestamp at ~55d out falls beyond the available candle range.

Extension evidence must not be used to influence base shift selection or as standalone evidence for promotion decisions.

## 9. Sensitivity Stability

| Metric | Value |
|---|---|
| Strict unique winners | 109 |
| Normal unique winners | 114 |
| MAX unique winners | 133 |
| Strict winners with same shift in Normal | 107 / 109 (98.2%) |
| Strict winners with same shift in MAX | 99 / 109 (90.8%) |
| Strict ties resolved to unique in Normal | 5 |
| Strict ties resolved to unique in MAX | 24 |
| MAX unique not in Normal (MAX-only gains) | 19 |

The selected shift is highly stable across STRICT→NORMAL: 107 of 109 strict unique winners retain the same shift. 2 strict unique winners produce a different shift under NORMAL, indicating marginal tie-breaking changes at the STRICT/NORMAL boundary.

Across STRICT→MAX, stability drops slightly: 99/109 (90.8%) retain the same shift. 10 strict unique winners change shift under MAX.

24 (symbol, anchor) pairs that tie under STRICT gain a unique winner under MAX. Of these, 19 are MAX-only (not resolved under NORMAL either). Results that appear exclusively under MAX are more tolerance-sensitive and should be weighted accordingly.

No result requires MAX to produce any base marker match; the 100% base marker match rate is consistent across all modes. The mode differences affect only tie-breaking, not marker reachability.

## 10. Limitations and Next Decision

**This campaign does not include random or shifted-anchor controls.**
Without controls, the tie rate and unique winner rate cannot be compared against a baseline. The current rates (STRICT 48.7% unique, MAX 59.4% unique) cannot be evaluated as strong or weak without knowing what a random-anchor campaign of the same structure produces.

**This campaign does not include A+ Table 2 comparison.**
The A+ day-offset comparison runner exists but has not been run against this archive. That comparison is deferred to the next PR.

**No promotion decision is made.**
Breathline V2 remains in research status. Classification is:

```
UNDECIDED_PENDING_CONTROLS
```

Required before any promotion decision:
1. Shifted-anchor control campaign (same 8 assets, same 28-anchor count, shifted by half-cycle)
2. Random-anchor control campaign (same structure, random anchor placement)
3. A+ Table 2 day-offset comparison for matching symbol/anchor pairs
4. Review of whether unique winner rates and shift stability exceed control baselines

**Observation notes (factual, no interpretation):**
- All 14 784 candidate slots match all 6 base markers in all 3 modes. The distinguishing factor between candidates is shift delta ranking, not marker reachability.
- The tie rate under STRICT is 51.3%, meaning more epochs tie than resolve in the strictest mode.
- 19 unique winners appear only under MAX tolerance and not under STRICT or NORMAL. These are tolerance-sensitive and should not be treated as strong evidence without controls.
- Extension markers at 0.0h residual across all modes are a consequence of the 21d cycle arithmetic and do not add discriminating evidence.
