# Distilled Notes From This Chat

## Portfolio / market interpretation
- Breathline should be used as a compass, not a clock.
- Weekly or larger timeframe is the preferred use for breathline data.
- Price action should handle timing, execution, invalidation, and trade management.
- Breathline observations should be logged over time for later LM/model work.

## Data logging
- Predictions / reflections must include a prediction timestamp.
- Recommended field name: `prediction_ts_utc`.
- Later predictions may shift; do not overwrite history.
- Append-only storage is preferred.

## Watchlist / asset design
- Keep V1 simple.
- All known assets live in `asset`.
- Use flags in `asset` for:
  - `is_enabled`
  - `is_portfolio`
  - `is_core_sensor`
- Add sector in `asset`.
- BTC, SOL, ADA should be included as core sensor / data assets.

## Strategy philosophy
- Different coins may play different roles:
  - structural thesis bets
  - volatility trade vehicles
  - temporary value parking
  - cycle beta
- Parking rotation is a valid strategy role.
- Execution engine comes later and should remain separate.

## Dashboard philosophy
- The dashboard should expose the bot's reasoning.
- Show not just actions, but also blocks and missing conditions.
- Preferred mental model: Mission Control.

## Architecture rule
- Avoid overengineering early.
- Use one global enabled asset universe for v1.
- Let strategies filter internally.

## Close-out summary — structure-state integration

Completed in this cycle:

1. Repaired and stabilized active pipeline usage:
   - `feat_candle`
   - `signal_engine_state`
   - `advice_state`
   - `ranking_state`
   - `selection_state`

2. Added measurement layer v1:
   - table `structure_state`
   - view `vw_structure_state_latest`
   - engine `src/measurement/run_structure_state_engine.py`

3. Implemented timeframe-aware measurement modules:
   - `trend_state`
   - `pullback_state`
   - `reclaim_state`

4. Kept architecture clean:
   - no human interpretation inside measurement / ranking / selection
   - no fake targets or pseudo execution values
   - final advice layer intentionally postponed

5. Integrated measurement layer into selection:
   - `selection_engine` now uses structure-state context
   - selection distribution now reflects structure + ranking + advice together

Important current observations:
- `1h` is mostly useful through `pullback_state`
- `4h` and `1d` reclaim signals are sparse but meaningful
- reclaim v1 is acceptable for downstream use, but later reclaim v2 should become a more explicit multi-candle state machine

Open items not completed in this cycle:
- final advice / human presentation layer
- exit / position-management layer
- additional measurement modules (`breakout_state`, `range_state`, `structure_event_state`, etc.)
- real zone / target / invalidation layer
- potential `selection_state` semantic refinement (e.g. split `AVOID` into `DEFER` vs `REJECT`)
- possible `vw_selection_enriched` technical inspection view
