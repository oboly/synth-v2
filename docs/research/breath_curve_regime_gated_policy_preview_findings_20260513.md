# Breath Curve Regime-Gated Policy Preview Findings — 2026-05-13

## Status

Research-only finding.

Scope remains:

- market-only
- account-agnostic
- no selection_engine changes
- no decision_gate changes
- no execution_planner changes
- no executor/order logic
- no broker calls
- no broker writes
- no order submission

## Implementation correction

The preview runner was corrected so is_minus8() only matches the exact policy:

    0618_selected_minus8_v1

It must not also match selected_band == -8.

Reason: multiple policy families can share the same selected band. Matching selected_band directly double-counted rows and inflated eligibility counts.

After correction, sample sizes normalized as expected:

| gate | before | after |
|---|---:|---:|
| gate_01_minus8_core_symbols win_real | 26 | 13 |
| gate_02_minus8_core_btc_eth_bear win_real | 26 | 13 |
| gate_03_minus8_core_volume_expansion win_real | 14 | 7 |
| gate_05_minus8_core_bear_volume win_real | 14 | 7 |

## Clean regime classification

| run | class | target edge | real eligible |
|---|---|---:|---:|
| breath_curve_broader_history_v1_20260513T173451Z | WINNING_REGIME | +6.9376 | 13 |
| breath_curve_broader_history_v1_20260513T180717Z | FAILING_REGIME | -0.6804 | 4 |

## Corrected regime-gated preview comparison

| gate | status | win real | win rand | win edge | win worst | fail real | fail rand | fail edge | separation |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| gate_05_minus8_core_bear_volume | REGIME_GATE_CANDIDATE_SAMPLE_THIN | 7 | 11 | +12.1991 | +2.5578 | 2 | 15 | -4.9865 | +17.1856 |
| gate_03_minus8_core_volume_expansion | REGIME_GATE_CANDIDATE | 7 | 12 | +11.7508 | +2.5578 | 3 | 20 | -4.9042 | +16.6550 |
| gate_07_minus8_alt_core_bear_volume_or_rsi | REGIME_GATE_CANDIDATE_SAMPLE_THIN | 10 | 18 | +10.4357 | +2.5578 | 2 | 24 | +0.3719 | +10.0638 |
| gate_04_minus8_core_rsi_mid_high | REGIME_GATE_CANDIDATE_SAMPLE_THIN | 12 | 28 | +10.2687 | +4.9075 | 2 | 38 | +1.1903 | +9.0784 |
| gate_08_early_band_core_bear_or_volume | REGIME_GATE_CANDIDATE | 15 | 149 | +7.5752 | +2.5578 | 5 | 139 | -0.8493 | +8.4245 |
| gate_01_minus8_core_symbols | REGIME_GATE_CANDIDATE | 13 | 59 | +6.9376 | +2.5578 | 4 | 74 | -0.6804 | +7.6180 |
| gate_02_minus8_core_btc_eth_bear | REGIME_GATE_CANDIDATE | 13 | 51 | +7.0251 | +2.5578 | 3 | 54 | +0.3184 | +6.7067 |
| gate_06_minus8_alt_core_participation_proxy | REGIME_GATE_CANDIDATE_SAMPLE_THIN | 10 | 38 | +7.8404 | +2.5578 | 2 | 54 | +1.4355 | +6.4049 |

## Interpretation

The strongest separation is in volume- and bear-volume-gated variants.

Primary research candidates:

1. gate_03_minus8_core_volume_expansion
   - strongest clean candidate with explicit candidate status
   - strong winning edge
   - negative failing edge
   - sample is still small, but not marked sample-thin by current thresholds

2. gate_05_minus8_core_bear_volume
   - strongest separation
   - still marked sample-thin
   - should remain diagnostic until more data is available

3. gate_01_minus8_core_symbols
   - best baseline control gate
   - confirms that the original minus8_core_symbols_v1 signal remains regime-dependent

Secondary candidates:

- gate_08_early_band_core_bear_or_volume
- gate_07_minus8_alt_core_bear_volume_or_rsi

The preview supports the hypothesis that Breath Curve selected -8 recognition is regime-dependent.

It does not support unconditional promotion into selection or execution layers.

## Architectural decision

Do not move this into selection_engine.

Do not connect this to decision_gate.

Do not connect this to execution_planner.

Do not create order behavior.

Correct next step:

1. keep as research-only preview
2. add more A+ Table 1 and Table 2 snapshots
3. validate A+ transitions against these regime-gated candidates
4. rerun broader-history and non-overlap validation as more snapshots are available
5. only after repeated validation consider a market-only selection modifier proposal

## Current read

Breath Curve selected -8 plus regime gating is promising, but not production strategy logic.

Best current label:

    research validation candidate

Not:

    live strategy
