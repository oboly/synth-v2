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
