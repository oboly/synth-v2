# Multi-Horizon Rotation Final Holdout Selection v1

Issue: #593
Status: frozen before final-holdout inspection

## Selection

```text
C1 -> ADVANCE_TO_FINAL_HOLDOUT
C2 -> REJECT_BEFORE_FINAL_HOLDOUT
C3 -> INSUFFICIENT_DATA
```

## Rationale

C1 reproduced its discovery behavior through validation with stable sign, stable lead/lag, stable chop, improved coverage, and incremental utility versus both Rotation V1 (B0) and comparable momentum (B1) across the primary short horizons.

C2 retained useful turn timing but failed to reproduce its nominal 1h forward relationship and its validation 1h incremental utility versus B0 collapsed to approximately zero. It is rejected before holdout and may not be resurrected from final-holdout results.

C3 remained too sparse for a defensible promotion decision and is not opened in the final holdout.

## Anti-overfitting lock

No candidate formula, sign, threshold, baseline, eligibility rule, forward horizon, or multiple-comparison family may change between this selection and final-holdout evaluation.

The final holdout is therefore a confirmatory test of C1 only.
