# BTC ↔ RENDER Breathline relationship study v1.0.4

Issue: #418

Status: pre-analysis statistical correction. No BTC↔RENDER relationship statistic has been inspected when this amendment is committed.

## Problem found during review

The v1.0.1/v1.0.3 LEADING/LAGGING statistic used the mean signed same-event lag:

```text
mean(RENDER_event_ts - BTC_event_ts)
```

while the null permuted BTC event timestamps within the same eligible rows.

That statistic is permutation-invariant:

```text
mean(RENDER) - mean(permuted BTC)
=
mean(RENDER) - mean(BTC)
```

so every timing permutation has the same mean. The null is therefore degenerate and cannot falsify pairing-specific lead/lag structure.

## Frozen correction

Before any relationship outcome inspection, replace the inferential LEADING/LAGGING statistic with:

```text
median signed same-event lag days
```

Per event:

```text
lag_days = (RENDER_event_ts - BTC_event_ts) / 86400
statistic = median(lag_days)
```

Discovery fixes the candidate sign:

```text
median > 0 -> LAGGING candidate
median < 0 -> LEADING candidate
median = 0 -> no direction
```

Holdout null:

1. retain the exact eligible RENDER rows and BTC event timestamps;
2. permute BTC event timestamps within split and event name;
3. recompute the median signed lag;
4. use the preregistered one-sided direction from discovery;
5. Holm-Bonferroni correction remains across recognition, ignition, main_pulse and extension.

The median is directional and pairing-sensitive under this permutation, unlike the mean.

## Unchanged

No other hypothesis, sample minimum, symbol, split, null family, permutation count, seed, Holm correction, PIT feature, baseline, or architecture rule changes.

```text
BTC / RENDER
Bitvavo 4h
70/30 chronological split
2000 permutations
seed 418001
Holm alpha 0.05
```

SHARED_EXTENSION remains Lane A association only. Only PIT ROTATION_CANDIDATE may produce positive predictive research evidence.

All outputs remain research-only and have no selection, decision, execution, broker, order, schema, or runtime authority.
