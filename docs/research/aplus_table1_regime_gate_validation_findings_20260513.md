# A+ Table 1 Regime-Gate Validation Findings — 2026-05-13

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

## Input

A+ canonical Table 1 snapshot:

    data/aplus_raw/2026-05-13_1915_table1_canonical_breathline.txt

Regime-gated Breath Curve preview rows:

    data/research/breath_curve_regime_gated_policy_preview_v1/breath_curve_regime_gated_policy_preview_v1_20260513T204910Z_policy_rows.csv

Runner:

    src/research/run_aplus_table1_regime_gate_validation_v1.py

## A+ Table 1 buckets

Derived buckets:

| bucket | tokens |
|---|---|
| APLUS_CANONICAL_CORE | AAVE, BTC, ETH, FET, INJ, NOT, POL, QNT, RED, RENDER, TAO, XRP |
| APLUS_ANCHOR_CONTEXT | DOT, HBAR, LDO, LTC, XLM |
| APLUS_AVOID | ADA, ALGO, CRV, FIL, FLOKI, HNT, HOT, HYPE, IOST, MOG, PEPE, WAL, WLD, XPL |
| APLUS_CAUTION | CC, ICP, NEAR, ONDO, SOL, SUI |
| APLUS_OTHER | DEEP, RLC, VET |

## Primary result

A+ canonical core strongly improves interpretation of the regime-gated Breath Curve candidates.

Best APLUS_CANONICAL_CORE results:

| gate | win real | win rand | win edge | win worst | fail real | fail rand | fail edge | separation | read |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| gate_05_minus8_core_bear_volume | 4 | 10 | +14.4291 | +2.5578 | 2 | 11 | -5.7502 | +20.1793 | APLUS_REGIME_GATE_CANDIDATE |
| gate_03_minus8_core_volume_expansion | 4 | 10 | +14.4291 | +2.5578 | 3 | 15 | -5.2674 | +19.6965 | APLUS_REGIME_GATE_CANDIDATE |
| gate_07_minus8_alt_core_bear_volume_or_rsi | 7 | 10 | +9.8698 | +2.5578 | 2 | 16 | -0.3263 | +10.1961 | APLUS_REGIME_GATE_CANDIDATE |
| gate_04_minus8_core_rsi_mid_high | 9 | 19 | +10.8386 | +4.9075 | 2 | 29 | +1.5354 | +9.3032 | APLUS_REGIME_GATE_CANDIDATE |
| gate_01_minus8_core_symbols | 10 | 43 | +7.9030 | +2.5578 | 4 | 55 | -0.0413 | +7.9443 | APLUS_REGIME_GATE_CANDIDATE |
| gate_08_early_band_core_bear_or_volume | 12 | 106 | +6.6697 | +2.5578 | 5 | 104 | -0.4000 | +7.0697 | APLUS_REGIME_GATE_CANDIDATE |
| gate_02_minus8_core_btc_eth_bear | 10 | 37 | +7.9832 | +2.5578 | 3 | 40 | +0.9999 | +6.9833 | APLUS_REGIME_GATE_CANDIDATE |

## Interpretation

A+ canonical core is not just decorative metadata. It appears to separate cleaner Breath Curve candidates from weaker regime contexts.

The strongest clean candidates remain:

1. gate_03_minus8_core_volume_expansion
2. gate_05_minus8_core_bear_volume
3. gate_04_minus8_core_rsi_mid_high
4. gate_01_minus8_core_symbols

## Important exception: FIL

FIL is the critical conflict case.

A+ Table 1 labels FIL as:

    APLUS_AVOID

Raw A+ state:

    late / low coherence / compression / distorted / laggard / weak / weak / avoid

But Breath Curve regime-gated results show FIL repeatedly as a strong winner inside volume-expansion gates.

Example:

| gate | regime | source | bucket | symbol | eligible | avg1000 | worst1000 |
|---|---|---|---|---|---:|---:|---:|
| gate_03_minus8_core_volume_expansion | WINNING_REGIME | real | APLUS_AVOID | FIL | 3 | +15.6420 | +15.6420 |
| gate_05_minus8_core_bear_volume | WINNING_REGIME | real | APLUS_AVOID | FIL | 3 | +15.6420 | +15.6420 |
| gate_08_early_band_core_bear_or_volume | WINNING_REGIME | real | APLUS_AVOID | FIL | 3 | +15.6420 | +15.6420 |

This means A+ avoid must not automatically become a hard blocker.

Better interpretation:

    A+ canonical core = clean structural candidate
    A+ avoid + Breath Curve -8 + volume expansion = dirty pulse / overshoot candidate

FIL currently belongs to the dirty-pulse category.

## Architecture decision

Do not move this into selection_engine yet.

Do not use A+ Table 1 as live trade permission.

Do not use A+ avoid as a universal block rule.

Correct next step:

1. keep A+ Table 1 as research overlay
2. add Table 2 harmonic/offset overlay when available
3. validate whether Table 2 confirms or rejects dirty-pulse cases like FIL
4. after repeated snapshots, propose a market-only selection modifier
5. only after selection validation should decision_gate/execution_planner be considered

## Current read

A+ Table 1 improves regime interpretation.

Best current labels:

    APLUS_CANONICAL_CORE = clean regime-gated Breath Curve candidate support
    APLUS_AVOID + VOLUME_EXPANSION = dirty pulse candidate, not automatic rejection

Not production logic yet.
