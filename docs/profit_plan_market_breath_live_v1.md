# Profit Plan Market Breath Live V1

This adds a read-only Market Breath display to the existing Profit Plan / one-card UI.

## Fields

Each Profit Plan symbol JSON row now includes `market_breath` with:

- `availability_state`: `AVAILABLE`, `STALE`, or `UNAVAILABLE`
- `market_breath_phase`: current deterministic phase when available, otherwise `null`
- `market_breath_state`: current maturity/state when available, otherwise `null`
- `market_breath_confidence`: current candle/lookback coverage number when available, otherwise `null`
- `raw_scores`: current `compression`, `expansion`, `momentum`, `reversal_pressure`, and `relative_strength` scores
- `closest_regime_context`: nearest deterministic classifier regime context for diagnostics
- `closest_regime_failed_conditions`: failed conditions for that nearest regime context
- `neutral_reason`: deterministic diagnostic string for neutral rows
- `trajectory_label`: fixed context label derived from phase, or `TRANSITION_UNCLEAR` for neutral, stale, or unavailable data
- `source_candle_ts_utc`: source candle close timestamp used for the symbol
- `resolved_asof_ts_utc`: global candle as-of timestamp for the read model
- `freshness_label`: `FRESH`, `STALE`, or `UNAVAILABLE`
- `freshness_reason`: machine-readable freshness reason
- `warnings`: read-only diagnostics

Trajectory mapping is fixed:

- `INHALE_ACCUMULATION` -> `BUILDING_TOWARD_EXPANSION`
- `HOLD_COMPRESSION` -> `COMPRESSION_WAITING_FOR_BREAK`
- `EXHALE_EXPANSION` -> `EXPANSION_ACTIVE`
- `OVERBREATH_EXTENSION` -> `EXTENSION_COOLDOWN_RISK`
- `COLLAPSE_RESET` -> `RESET_RECOVERY_WATCH`
- `NEUTRAL_TRANSITION`, stale, or unavailable -> `TRANSITION_UNCLEAR`

## Boundaries

- Runtime uses only current market candles, BTC reference candles, and market breadth derived from the same candle snapshot.
- The Profit Plan request path calls a shared pure Market Breath classifier through a reusable reporting read model. It does not shell out to a research CLI.
- No A+ data, calibration labels, or research artifacts are imported at runtime.
- No DB writes, selection changes, decision changes, execution changes, broker changes, or order/account changes are introduced here.
- `market_breath_confidence` is rendered in the UI as data coverage, not classifier confidence.
- `neutral_reason` and `closest_regime_context` are diagnostic context only.
- `trajectory_label` is context only. It is not a forecast, advice signal, or execution recommendation.
- If symbol or BTC inputs are stale or insufficient, the UI must show stale or unavailable status instead of fabricating a current phase.
