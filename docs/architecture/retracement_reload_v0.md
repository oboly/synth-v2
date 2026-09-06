# Retracement Reload v0

Issue #665 defines a market-only heuristic overlay on the canonical Fib navigation map.

The canonical geometry owner remains `src/market_data/fib_navigation_map_v1.py`. That map already provides R0.236, R0.382, R0.500, R0.618 and R0.786. Retracement Reload v0 does not recompute Fib levels.

Inputs:
- canonical Fib navigation map
- immutable source map identity
- prepared continuation-strength state
- prepared invalidation price

The overlay is account-agnostic. It does not read wallet, position, reservation, decision-gate, execution-planner or executor state.

## Heuristic v0 mapping

```text
VERY_STRONG -> R0.236 / R0.382
STRONG      -> R0.382 / R0.500
NORMAL      -> R0.500 / R0.618
WEAKENING   -> R0.618 / R0.786
STRUCTURE_BROKEN -> no reload opportunity
```

These are explicit replaceable estimates, not calibrated probabilities.

## Authority boundaries

`reload_strength_score` is a deterministic ordinal v0 convenience score only. It must not be presented as a hit-rate or calibrated probability.

Preferred reload levels are market guidance. They create no BUY permission. `decision_gate` remains the sole owner of account-aware allocation and permission; execution layers may consume only separately approved intents.

A structure-broken state emits no reload levels. Missing canonical geometry fails closed rather than synthesizing a replacement level.

## Future calibration

Historical research may later replace the v0 state mapping or score values. Any promotion must be separately reviewed and versioned; it must not silently reinterpret stored v0 output.
