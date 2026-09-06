# Momentum / Flow Exhaustion Phase C Calibration v1

Status: research calibration complete; no promotion
Issue: #306
Input model: `momentum_flow_exhaustion_candidate` `1.0-research`
Scope: market-only, account-agnostic, research-only

## Decision

`NO_SYMMETRIC_PROMOTION`

The Phase B `45 / 70` state thresholds remain uncalibrated research labels and must not be promoted into selection, permission, execution, or reporting truth.

A full point-in-time replay over 10 liquid Bitvavo assets produced 20,184 observations. The high buyer-exhaustion bucket shows modest positive reversal evidence, while the high seller-exhaustion bucket does not. A single symmetric production interpretation would therefore be unsupported.

## Reproducible calibration cohort

- venue: Bitvavo
- interval: 4h
- period: 2025-09-01T00:00:00Z through 2026-09-01T00:00:00Z
- assets: BTC, ETH, SOL, ADA, XRP, DOT, LINK, AAVE, NEAR, ARB
- sample cadence: every finalized 4h as-of
- forward horizons: 1, 3, 6 bars
- observations: 20,184
- feature inputs: only finalized candles at or before each as-of
- outcomes: strictly future candles only

The Phase C runner recomputes the Phase B candidate from the minimum sufficient 20-bar historical window. A regression proves that prepending older history does not change the candidate result, so this bounded replay preserves Phase B semantics without future leakage.

## Aggregate score evidence

### Buyer score 70-100

- n = 147
- avg reversal return: +0.417% at 1 bar, +0.577% at 3 bars, +0.615% at 6 bars
- median reversal return: +0.380% at 1 bar, +0.361% at 3 bars, +0.536% at 6 bars

This is directionally consistent with buyer exhaustion, but the sample remains too small and cross-asset dispersion is material.

### Seller score 70-100

- n = 134
- avg reversal return: +0.017% at 1 bar, -0.065% at 3 bars, -0.084% at 6 bars
- median reversal return: +0.059% at 1 bar, -0.228% at 3 bars, +0.097% at 6 bars

This does not establish seller exhaustion. The current symmetric formula/threshold pair is therefore not validated.

### Aggregate active score 70-100

- n = 281
- side-adjusted avg reversal return: +0.226% at 1 bar, +0.271% at 3 bars, +0.281% at 6 bars
- side-adjusted median reversal return: +0.225% at 1 bar, +0.188% at 3 bars, +0.358% at 6 bars

The aggregate is positive because the buyer side contributes the stronger signal. It must not be interpreted as proof that both sides are calibrated.

## Cross-asset check for score 70+

Buyer 6-bar average reversal is positive in 7/10 assets, approximately flat in AAVE, and negative in ETH and SOL. Seller 6-bar average reversal is positive in AAVE, ETH, LINK and SOL, but negative in ADA, ARB, BTC, DOT, NEAR and XRP. Several per-asset counts remain small.

This dispersion rejects a universal side-symmetric production threshold at this stage.

## Architecture consequence

Allowed next work:

1. keep Phase B outputs research-only;
2. split buyer and seller calibration paths in follow-up research;
3. test whether regime/morphology context explains seller-side continuation vs reversal;
4. evaluate incremental value against simpler controls such as volume ratio, wick/rejection geometry and raw directional progress;
5. require discovery/validation separation before any promotion proposal.

Forbidden:

- interpreting `CONFIRMED` as trading permission;
- wiring the current 45/70 labels into `selection_engine` as accepted truth;
- adding penalties/bonuses to Fib Reach from these unvalidated labels;
- computing or reinterpreting the signal in reporting;
- using account state, decision_gate, execution_planner or executor logic.

## Reproduction

The canonical runner is `src/research/run_momentum_flow_exhaustion_phase_c_v1.py`. The full calibration was executed read-only against gurkdb and writes only local research artifacts under `data/research/momentum_flow_exhaustion_phase_c_v1/`.

No production DB rows, runtime state, broker state, orders, or account state were mutated.
