# Breathline harmonic-family falsification v1.0.1 amendment

Status: pre-analysis correction to the Issue #533 preregistration.

No real #533 outcome analysis had been executed when this correction was made.
The immutable #534 RENDER/TAO source evidence had already been collected, but no
#533 Lane A/Lane B result artifacts existed. This amendment therefore corrects a
methodological inconsistency before outcome inspection rather than tuning a
hypothesis after seeing results.

## Supersedes only the Lane A phase-null significance metric

Registry v1.0.0 correctly froze the candidate duration family, phase markers,
splits, baselines, seed, permutation count and Holm-Bonferroni correction, but
its phase-null wording combined:

```text
shifted observed phase position modulo 1
```

with an unwrapped marker such as:

```text
extension = 1.272
```

That makes the null statistic for the extension marker incomparable with the
observed statistic.

Registry v1.0.1 keeps the original unwrapped descriptive outputs unchanged:

```text
node_timing_residual_days
phase_position_residual
```

For Lane A phase-null significance only, both observed and shifted-null values
now use one identical circular representation:

```text
a = observed_phase_position mod 1
b = marker_ratio mod 1
d = abs(a - b)
circular_phase_distance = min(d, 1 - d)
```

Each permutation still applies one deterministic seeded `U[0,1)` circular shift
to all observed node positions within a cycle, preserving relative node spacing.
The seed remains `533001`, permutation count remains `2000`, and the seven marker
p-values remain corrected together with Holm-Bonferroni at alpha `0.05`.

## Everything else remains frozen

Unchanged from v1.0.0:

```text
duration family = 3,6,9,12,21,42,63,105,126,147d
phase markers = .236,.382,.5,.618,.786,1,1.272
HALF_PHASE_SPLIT = 10.5d separate
per-asset chronological discovery/holdout = 70/30
PIT historical rule = outcome_as_of_ts < checkpoint feature_as_of_ts
asset prior-history minimum = 8 completed cycles
pooled prior-history minimum = 12 completed cycles
baselines = fixed21, asset prior median, pooled prior median
binary null = within-asset outcome permutation
duration null = within-asset future-duration permutation
seed = 533001
permutations = 2000
multiple-comparison method = Holm-Bonferroni
alpha = 0.05
Lane A retrospective only
Lane B point-in-time predictive only
```

No #417 tracker behavior, market source, architecture boundary, production code,
selection logic, account policy, execution behavior or runtime activation changes.
