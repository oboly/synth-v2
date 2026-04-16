# Synth Database Schema Reference (v2)

This document is the **single source of truth** for the Synth v2 database.

It defines:
- canonical table names
- canonical column names
- join contracts
- time alignment rules
- event layer (core alpha)

If anything conflicts with this document → THIS document is leading.

---

# 1. ARCHITECTURE

OBS → FEAT → EVENT → SIGNAL → DECISION → EXECUTION

- obs_* = raw market data
- feat_* = derived features (context)
- feat_*_event = event detection (alpha layer)
- signal_engine_state = interpretation
- decision_log = actions

---

# 2. TRADE TABLE

## tmp_rejected_htf_4h_trades

Primary backtest output.

### Columns

- asset_id (INT)
- symbol (VARCHAR)
- entry_ts_utc (DATETIME)
- exit_ts_utc (DATETIME)
- trade_return (DECIMAL)  ← CANONICAL
- policy_name (VARCHAR)
- selection_state (VARCHAR)
- selection_bias (VARCHAR)
- selection_score (DOUBLE)

### RULES

- ALWAYS use: trade_return
- NEVER use: pnl / pnl_pct / return_pct

---

# 3. FEATURE LAYER

## feat_candle

Primary candle feature table.

### Keys

- asset_id
- venue
- interval_code
- close_ts_utc

### Important Columns

- atr_pct
- volume_zscore_20
- body_pct
- upper_wick_pct
- lower_wick_pct
- wick_reversal_score

### RULE

feat_candle = CONTEXT ONLY  
NOT event detection

---

# 4. EVENT LAYER (CORE ALPHA)

## feat_rejection_event

Defines failed moves (primary edge).

### Keys

- asset_id
- interval_code
- open_ts_utc

### Columns

- is_sweep
- is_reclaim
- sweep_direction
- sweep_distance_atr
- reclaim_strength
- wick_ratio
- close_position
- volume_ratio

### MECHANISM

FAILED_BREAKDOWN = is_sweep = 1 AND is_reclaim = 1

---

## feat_liquidity_event

Liquidity + rejection scoring.

### Keys

- asset_id
- venue
- interval_code
- open_ts_utc

### Columns

- sweep_flag
- rejection_flag
- liquidity_event_score

---

# 5. TIME ALIGNMENT (CRITICAL)

## Trade → Event

trade.entry_ts_utc = event.open_ts_utc

## Trade → Candle Features

trade.entry_ts_utc + interval = feat_candle.close_ts_utc

Example (4h):

entry: 10:00  
candle close: 14:00  

---

# 6. NAMING RULES (STRICT)

## Returns

trade_return → ONLY allowed name

## Features

ret_* → only inside feature tables

## Events

is_* → boolean  
*_score → continuous  
*_strength → intensity  

---

# 7. CORE INSIGHT

The system is NOT:

strategy-driven

The system IS:

event-driven

Primary edge:

Liquidity Sweep → Reclaim → Forced Counterflow

---

# 8. COMMON ERRORS (FIXED)

❌ candle_feat  
✅ feat_candle  

❌ pnl / pnl_pct  
✅ trade_return  

❌ guessing joins  
✅ follow time alignment rules  

❌ trusting labels  
✅ trust event layer  

---

# 9. LEGACY (V1)

Old naming:

- candle_feat → replaced by feat_candle
- market_candle → replaced by obs_market_candle

These should not be used in new development.

---

# 10. FUTURE

Next system upgrade:

signal_engine_event_score

Example:

score = 0

if is_sweep: +1  
if is_reclaim: +2  
if reclaim_strength high: +1  
if liquidity_event_score high: +1  

---

# FINAL RULE

If something is unclear:

→ update THIS file  
→ never solve it only in code or chat


---

# Analysis View Standard

For state-analysis views, prefer these canonical columns:

- entry_ts_utc
- next_ts_utc
- entry_close_price
- next_close_price
- next_return_4h

For reversion-state views, prefer:

- reversion_state_score
- reversion_state_bucket

Avoid ad hoc return naming drift such as:
- next_4h_return_proxy
- score
- return_pct in analysis views

