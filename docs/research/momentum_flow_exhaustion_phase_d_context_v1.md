# Momentum / Flow Exhaustion Phase D Regime Interaction v1

Status: interaction diagnostic complete; context coverage insufficient for conclusion
Issue: #306
Scope: research-only, market-only, account-agnostic

## Decision

`REGIME_INTERACTION_INCONCLUSIVE_CONTEXT_COVERAGE`

Phase D adds a strict point-in-time join between Phase C exhaustion rows and existing `regime_selector_backtest_observation_v1` history. The join is deterministic and fail-closed: same symbol and interval, latest regime observation at or before the exhaustion as-of, explicit maximum context age, UNKNOWN when missing/stale. Future context is never used.

The existing regime-selector history is too sparse in time to support a reliable exhaustion-by-regime conclusion.

## Coverage

Existing regime source:
- 222,924 observations
- 4h only
- 32 distinct days
- 2026-03-21 through 2026-05-14

Against the 20,184 Phase C exhaustion observations:

| Max context age | Known context rows | Coverage |
|---|---:|---:|
| 4h | 896 | 4.44% |
| 12h | 1,283 | 6.36% |
| 24h | 1,660 | 8.22% |

The 4h rule is the primary truthful join. 12h and 24h are sensitivity checks only and are not promoted context semantics.

## 70+ interaction samples

At 4h max age there are only 6 buyer-score-70+ and 5 seller-score-70+ observations with known global regime context. These counts are inadequate for calibration.

The sensitivity runs remain small and change cohort composition. That instability is evidence that coverage must be improved before interpreting regime interaction.

## Architecture consequence

Do not modify the exhaustion formula based on these sparse regime slices.

Next required foundation is a reproducible historical context dataset with materially deeper coverage across the same replay window, using existing historical context builder/source semantics rather than inventing a new regime classifier.

Correct flow:

```text
historical market/breath/regime source rows
-> canonical research context builder/backbone
-> PIT context coverage audit
-> #306 side-specific regime interaction replay
-> discovery/validation split
-> optional promotion proposal only if supported
```

No selection, reporting truth, decision, execution, broker, or account behavior is authorized by this work.
