# Multi-Horizon Rotation C1 Final Holdout Evaluation Gate v1

Issue: #593
Status: frozen before final-holdout outcomes are inspected

The final holdout evaluates C1 only, using the already-frozen metric semantics from `multi_horizon_rotation_validation_v1` and the bounded streaming implementation from `multi_horizon_rotation_validation_streaming_v1`.

Required evidence remains:

- coverage / missingness;
- raw forward IC at 15m, 1h, 4h, 24h;
- incremental utility versus B0 Rotation V1;
- incremental utility versus B1 comparable momentum;
- persistence and chop;
- lead/lag versus B1 turns;
- B0 regime stability;
- effect size, confidence interval, and sample count.

Because model selection has already reduced the confirmatory family to preregistered C1, C2/C3 may not be inspected or used to alter the final decision.

No arbitrary effect-size threshold is introduced. Promotion requires the validation-supported C1 behavior to remain directionally and operationally coherent out of sample, including incremental information beyond both B0 and B1 and no material coverage/chop failure.

No score sign inversion, recalibration, threshold adjustment, formula change, or post-holdout candidate rescue is allowed.
