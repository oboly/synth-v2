# BTC ↔ RENDER Breathline relationship study v1.0.3

Issue: #418

Status: pre-analysis architecture clarification. No BTC↔RENDER relationship statistic has been inspected when this amendment is committed.

## Purpose

`SHARED_EXTENSION` is evaluated on completed maximum-overlap paired BTC/RENDER cycles. That pairing requires realized cycle ends and therefore belongs to retrospective Lane A. It may establish holdout association, but it cannot create point-in-time predictive authority.

v1.0.3 makes that boundary explicit before outcome inspection.

## Frozen authority rule

```text
PHASE_LOCK           -> Lane A structural only
LEADING / LAGGING    -> Lane A structural only
CONVERGING/DIVERGING -> Lane A structural only
DETACHED / RELOCK    -> Lane A structural only
SHARED_EXTENSION     -> Lane A association only
ROTATION_CANDIDATE   -> Lane B PIT predictive test
```

Overall verdict:

```text
ROTATION_CANDIDATE supported
    -> POSITIVE_RESEARCH_EVIDENCE

any Lane A hypothesis supported, including SHARED_EXTENSION
    -> STRUCTURAL_EVIDENCE_ONLY

otherwise
    -> UNRELATED
```

`SHARED_EXTENSION` therefore reports `SUPPORTED_ASSOCIATION`, not `SUPPORTED_PREDICTIVE`.

## Unchanged

No hypotheses, symbols, split, test statistic, null family, minimum support, permutation count, seed, Holm correction or PIT anti-leakage rule changes.

```text
reference = BTC
alt = RENDER
venue = bitvavo
interval = 4h
discovery_fraction = 0.70
null_permutations = 2000
random_seed = 418001
alpha = 0.05
multiple_comparison_method = holm_bonferroni
```

All outputs remain research-only and carry no selection, decision, execution, broker, order or runtime authority.
