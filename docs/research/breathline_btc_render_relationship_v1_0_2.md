# BTC ↔ RENDER Breathline relationship study v1.0.2

Issue: #418

Status: pre-analysis null-implementation clarification. No BTC↔RENDER relationship statistic has been inspected when this amendment is committed.

## Purpose

v1.0.1 froze exact statistics, minimum support and verdict rules. One implementation detail remained ambiguous: a raw permutation of completed BTC cycle identities can destroy wall-clock overlap and therefore change the number of eligible phase rows in the null sample.

That would make the null compare a different support/missingness pattern from the observed statistic. v1.0.2 fixes this before analysis.

## Frozen null implementation

### BTC cycle-pair permutation

For PHASE_LOCK, CONVERGING/DIVERGING and DETACHED/RELOCK:

1. Build the observed eligible paired-cycle rows first.
2. For every row retain the BTC realized-phase measurement vector keyed by the available RENDER phase checkpoints.
3. Within discovery or holdout, permute those retained BTC measurement vectors across RENDER rows.
4. Do not recompute wall-clock overlap after permutation.
5. Recompute the relationship statistic from the permuted BTC vector and unchanged RENDER vector.

This breaks BTC↔RENDER pairing association while preserving split membership, row count, checkpoint support and missingness.

### BTC event-timing permutation

For LEADING/LAGGING, within split and event name permute the retained BTC same-event timestamps across the exact eligible rows.

For ROTATION_CANDIDATE, within the exact split/checkpoint/feature/outcome matched row set permute the retained BTC recency-score values across rows. RENDER outcomes and no-BTC baseline scores stay fixed.

### BTC extension-label permutation

For SHARED_EXTENSION, within split permute BTC `extension_confirmed` labels across the exact paired rows used by the observed statistic.

## Invariant

Every permutation uses the exact observed eligible row set for that statistic:

```text
row count invariant
RENDER outcome invariant
missingness invariant
split membership invariant
only preregistered BTC measurement/timing-score/label assignment changes
```

The original null families, 2000 permutations, seed `418001`, Holm-Bonferroni alpha `0.05`, hypotheses, symbols, split and architecture boundaries are unchanged.
