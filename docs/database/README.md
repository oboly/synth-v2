Core tables:
- obs_market_candle (raw market data)
- candle_feat (features)

Pipeline:
- signal
- advice
- selection
- decision
- risk
- portfolio

New:
- position_lot
- trade_lot
- strategy_version
- portfolio_target

Notes:
- DB is source of truth
- schema via DBeaver export



# Schema Explanation

## V1 tables

### asset
Master table for all known assets.

Stores:
- symbol
- name
- sector
- enabled flag
- portfolio flag
- core sensor flag

### market_candle
Stores raw OHLCV market data.

### candle_feat
Stores derived features such as EMA / RSI / ATR and relative strength.

### strategy_signal
Stores the output of strategy modules.
This is not the final decision yet.

### decision_log
Stores the final reasoning layer.
Shows what the bot wanted to do and what blocked it.

### position_snapshot
Stores portfolio holdings snapshots.
Useful for dashboard and later analytics.

### breathline_compass
Stores weekly-or-larger compass reflections and predictions.
Must be append-only by prediction timestamp.

## Design notes

- store timestamps in UTC
- keep enums stable in code/config
- prefer append-only logs where possible
- execution tables come later

# Portfolio and execution views

Latest portfolio and execution snapshots are exposed through:

- `v_portfolio_state_latest`
- `v_portfolio_state_latest_with_symbol`
- `v_portfolio_board`

- `v_execution_intent_latest`
- `v_execution_intent_latest_with_symbol`
- `v_execution_board`

Optional combined board:
- `v_synth_execution_live_board`

These views are used for:
- terminal summaries
- dashboarding
- inspection of current portfolio targets
- inspection of paper execution intents
