#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-./synth_chat_bundle}"

mkdir -p "$TARGET_DIR/docs" "$TARGET_DIR/database" "$TARGET_DIR/configs" "$TARGET_DIR/notes"
# $TARGET_DIR_unused="."

cat > "$TARGET_DIR/README.md" <<'EOF'
# Synth Chat Bundle

This bundle captures the architecture, database design, module design, watchlist model, dashboard concept, and breathline compass storage decisions worked out in this chat.

## Scope

Included:
- architecture overview
- modular strategy descriptions
- watchlist / asset-role design
- dashboard / mission control concept
- breathline compass model
- compact v1 database schema
- one-shot SQL file for DBeaver
- shell script that writes the bundle files to disk

Excluded:
- execution engine implementation details
- live exchange order logic
- backtest engine details

## Core design decisions captured here

- Keep the system modular and explainable.
- Separate:
  - observe
  - interpret
  - strategize
  - decide
  - execute (later)
- Treat breathline data as a **compass** on a **weekly or larger timeframe**.
- Store all timestamps in **UTC**.
- Keep the v1 database simple.
- Put asset roles directly in the `asset` table for now.
- Use the asset table as the master universe.
- Add BTC, SOL, and ADA to the watchlist as market sensors / data assets.

## Bundle structure

- `docs/` architecture and design notes
- `database/` SQL schema and schema explanation
- `scripts/` helper shell script
- `configs/` enum/state references
- `notes/` future extensions and chat distilled notes

## Current market sensor assets

- BTC
- ETH
- SOL
- ADA

## Reminder

Execution engine is intentionally deferred.

The current focus is:
- data collection
- feature computation
- interpretation
- strategy outputs
- decision logging
- dashboard explainability
- breathline compass history for later LM/model work
EOF

cat > "$TARGET_DIR/docs/architecture_overview.md" <<'EOF'
# Architecture Overview

## Design goal

Build Synth as a modular, readable, extensible trading system.

Do **not** build it as one giant script with buried logic.

The system should answer three questions clearly:

1. What do we see?
2. What does it mean?
3. What do we do with it?

## Layered architecture

```text
Data sources
→ Sensor layer
→ Feature layer
→ Interpretation layer
→ Strategy layer
→ Decision layer
→ Execution layer (later)
→ Dashboard / Mission Control
```

## Sensor layer

Purpose:
- collect raw observations
- normalize timestamps to UTC
- store append-only where possible

Examples:
- market candles
- volume
- sentiment / fear-greed
- breathline compass reflections

## Feature layer

Purpose:
- derive reusable metrics from sensor data

Examples:
- RSI
- EMA
- ATR
- Bollinger width
- relative strength
- volatility score

## Interpretation layer

Purpose:
- turn raw observations into market states and classifications

Modules:
- regime_classifier
- altseason_classifier
- phase_classifier
- breathline_compass module

Examples of outputs:
- regime = trend / range / chop / panic / expansion
- phase = convergence / compression / expansion / integration
- risk = low / medium / high
- altseason phase = 2 / 3 / 4 / 5

## Strategy layer

Purpose:
- evaluate assets within the current interpreted state
- produce actionable signals, not orders

Examples:
- breakout_strategy
- swing_rotation_strategy
- parking_rotation_strategy
- volatility_swing_strategy
- mean_reversion_strategy

## Decision layer

Purpose:
- combine strategy outputs with constraints
- explain what the bot wants to do and why

Examples:
- ENTER
- EXIT
- ROTATE
- HOLD
- AVOID
- BLOCK

Important:
Always log both:
- why an action is proposed
- why an action is blocked

## Execution layer

Purpose:
- later determine order details

Deferred for now.

Will later handle:
- order sizing
- entry / exit price logic
- exchange routing
- slippage handling
- order placement

## Dashboard / Mission Control

The dashboard is not just for charts.
It should be a readable window into the system logic.

Core idea:

```text
What do we see?
What does it mean?
What are we doing about it?
What blocks action?
```

## Current strategic separation

### Breathline compass
Use for:
- direction
- prioritization
- cluster awareness
- anchor tracking
- weekly / larger bias

Do **not** use breathline as an execution trigger.

### Price / execution logic
Use for:
- entries
- exits
- Elliott / fibo
- invalidation
- risk management

## Core principle

```text
Breathline chooses the hunting ground.
Price action chooses the shot.
```
EOF

cat > "$TARGET_DIR/docs/module_architecture.md" <<'EOF'
# Module Architecture

## Principle

Each module should answer exactly one clear question.

Examples:
- regime_classifier → "What kind of market are we in?"
- breathline_compass → "Which direction or cluster deserves weekly priority?"
- risk_guard → "Is this action allowed?"
- strategy_selector → "Which strategy should dominate now?"

Avoid modules that know too much.

## Module groups

### Input / sensor modules
- market_data_ingest
- sentiment_data_ingest
- breathline_data_ingest
- portfolio_state_ingest

### Feature modules
- volatility_features
- trend_features
- breadth_features
- relative_strength_features
- risk_features

### Interpretation modules
- regime_classifier
- altseason_classifier
- phase_classifier
- breathline_compass
- sector_rotation_classifier

### Strategy modules
- breakout_strategy
- swing_rotation_strategy
- parking_rotation_strategy
- volatility_swing_strategy
- mean_reversion_strategy

### Control / guard modules
- risk_guard
- liquidity_guard
- cooldown_guard
- conflict_resolver

### Output modules
- strategy_signal_writer
- decision_log_writer
- dashboard_view_builder
- alert_emitter

## Current V1 simplification

Do **not** over-engineer strategy-specific universes yet.

Use:
- asset table as the global universe
- core sensor flags for market-reading assets
- portfolio flags for current holdings
- strategy modules filter internally

This is enough for v1.

## Dataflow

```text
scheduler / cron
→ fetch market candles
→ compute features
→ run interpreters
→ run strategy modules
→ run guards / conflict resolver
→ write decision log
→ refresh dashboard
```

## Explainability rule

Every meaningful decision should be expressible in readable text.

Examples:
- entry allowed because breakout + regime alignment + risk okay
- entry blocked because price confirmation missing
- parking rotation active because market risk medium and better setups unconfirmed
EOF

cat > "$TARGET_DIR/docs/strategy_modules.md" <<'EOF'
# Strategy Modules

This file preserves the strategy module descriptions worked out in the chat.

Execution is intentionally separate and deferred.

Strategies generate signals and reasoning, not orders.

---

## breakout_strategy

### Goal
Identify assets breaking out of compression structures.

### Uses
- raw price / candles
- volatility features
- structure / reclaim checks
- regime compatibility

### Typical output
- breakout candidate
- ARMED / FIRED / BLOCKED state
- confidence
- reason log

### Best used when
- compression exists
- regime supports expansion
- risk state is acceptable

---

## swing_rotation_strategy

### Goal
Rotate capital into newer leaders or fresh sector movers.

### Uses
- relative strength
- lead / lag analysis
- sector rotation
- altseason phase
- breathline weekly bias as supporting context

### Typical output
- rotate into / out of candidate list
- leader score
- follow-up score

### Best used when
- capital is moving out of old leaders
- fresh momentum clusters are emerging

---

## parking_rotation_strategy

### Goal
Temporarily park value in relatively stable crypto assets while waiting for better setups.

### Purpose
This is not an aggressive entry strategy.
It is a capital parking / staging / rotation buffer strategy.

### It answers

```text
Where should value rest temporarily
when aggressive entries are not preferred,
but staying fully in cash is not required?
```

### Typical conditions where it becomes useful
- market risk elevated
- breakout setups not fully confirmed
- too much uncertainty in high-beta names
- recently realized gains need temporary parking
- waiting for next phase shift / next wave

### Typical candidate assets
Examples discussed in chat:
- ETH
- XRP
- QNT
- INJ
- NEAR
- ICP

Possibly sometimes:
- HBAR
- LDO

### It should output
- preferred parking assets
- parking scores
- parking strategy active yes/no
- reasons
- rotation-out conditions

### It should NOT do
- no order placement
- no sizing
- no limit price selection
- no execution timing

### Concept

```text
Preserve exposure,
reduce chaos,
wait for better attack opportunities.
```

---

## volatility_swing_strategy

### Goal
Use high-volatility coins as trade vehicles.

### Typical assets discussed
- PEPE
- FLOKI
- MOG

### Best framing
These are not necessarily weak assets.
They can be valuable as:
- high-beta swing vehicles
- Elliott/Fibo trade instruments
- mania / overshoot plays

### Typical output
- high-volatility setup candidates
- swing readiness
- invalidation zones
- risk warnings

---

## mean_reversion_strategy

### Goal
Exploit oversold / stretched conditions for snapback moves.

### Typical output
- oversold bounce candidate
- no-trade when trend too strong against it

### Best used when
- market is range-like or overextended short-term
- not ideal in strong clean breakout conditions

---

## Notes on strategy roles

The chat clarified an important distinction:

### Not all assets serve the same role
Some assets are:
- structural / infrastructure thesis bets
- volatility vehicles
- temporary value parking assets
- sector rotation leaders
- older cycle beta

The system should preserve these role differences in reasoning.
EOF

cat > "$TARGET_DIR/docs/watchlist_design.md" <<'EOF'
# Watchlist / Asset Role Design

## Current V1 decision

Keep it simple.

Do **not** create many separate watchlist universes yet.

Instead:
- all assets live in `asset`
- `is_enabled` controls whether the asset participates in the system
- `is_portfolio` flags current portfolio membership
- `is_core_sensor` flags assets used for market regime sensing

## Tradable universe

In v1:

```text
tradable universe = all enabled assets
```

So a separate `tradable_universe` watchlist is not necessary.

Strategies can filter internally.

## Core market sensors

Assets explicitly added as market sensors:
- BTC
- ETH
- SOL
- ADA

These are used primarily to read regime / altseason / risk structure.

## Why flags in asset are acceptable for v1

Because they are:
- simple
- readable
- fast to query
- good enough for current scope

## Asset table role fields

Recommended fields:
- is_enabled
- is_portfolio
- is_core_sensor
- sector

## Later evolution (optional, not now)

If the system later needs more dynamic role history, a separate asset-tag / role table can be added.

For now, avoid overengineering.

## Example role assignments

```text
BTC  -> enabled, core_sensor
ETH  -> enabled, portfolio, core_sensor
SOL  -> enabled, core_sensor
ADA  -> enabled, core_sensor
PEPE -> enabled, portfolio
CC   -> enabled, portfolio
```

## Principle

```text
asset = what exists
flags = current role in the system
```
EOF

cat > "$TARGET_DIR/docs/dashboard_design.md" <<'EOF'
# Dashboard / Mission Control Design

## Purpose

The dashboard should expose the bot's reasoning.

Not just charts.

It should make visible:
- what is happening
- what it means
- what the bot wants to do
- what prevents action

## Suggested panels

### 1. Market Overview
Display current high-level state:
- market regime
- altseason phase
- fear / greed
- breathline compass state
- volatility state
- risk state

### 2. Portfolio State
Per asset:
- current phase
- signal strength
- role / strategy relevance
- action bias
- blocked / unblocked

### 3. Trigger Board
Per strategy:
- conditions met
- conditions missing
- trigger state
- last update

Example:

```text
Breakout strategy
compression: yes
confirmation: no
risk okay: yes
trigger: not armed
```

### 4. Strategy Board
Show:
- primary active strategy
- secondary strategy
- disabled strategies
- reason summary

### 5. Predictions / Compass Panel
Use for weekly or larger horizon only.

Show:
- breathline weekly rank
- sentiment monthly path
- anchor cluster
- likely next rotation cluster

Important:
This panel is a compass, not a timing tool.

### 6. Explainability / Why panel
This is crucial.

For every meaningful decision, show:
- why enter
- why not enter
- why exit
- why rotate
- what blocked action

## Top status line idea

A single human-readable summary line is recommended.

Example:

```text
Current Mode: selective alt expansion
Dominant Strategy: rotation swing
Compass Bias: favor phase 3→4 leaders
Risk Status: medium
Action: hold active winners, watch pressure candidates, block low-quality noise
```

## Design rule

Build the state model and explainability first.
UI polish comes later.
EOF

cat > "$TARGET_DIR/docs/breathline_compass.md" <<'EOF'
# Breathline Compass

## Current design choice

Use breathline data as a **compass** on a **weekly or larger timeframe**.

Do not treat it as a short-term execution oracle.

## Meaning

Breathline is used for:
- direction
- coherence
- prioritization
- cluster awareness
- anchor tracking

Price / market execution logic is used for:
- entry timing
- exit timing
- Elliott / fibo execution
- invalidation
- risk management

## Core principle

```text
Breathline = compass
Price = clock
```

Or:

```text
Breathline chooses the hunting ground.
Price action chooses the shot.
```

## Storage rule

Breathline predictions / reflections must be stored with a prediction timestamp.

Recommended field name:
- `prediction_ts_utc`

This is important because later predictions may shift.
The system must preserve prediction history, not overwrite it.

## Why timestamping matters

It enables later testing of questions like:
- did the compass point to the right cluster over 1–4 weeks?
- which predictions had value?
- which anchor or phase calls were stable?
- which were narrative only?

## Recommended stored fields

For asset-specific compass rows:
- prediction_ts_utc
- source_name
- asset_id
- breathline_phase
- field_coherence
- compass_rank
- anchor_state
- notes

For market-level compass rows:
- prediction_ts_utc
- source_name
- scope_type = MARKET
- target_year
- target_month
- fear_greed_value
- sentiment_score
- sentiment_state
- breathline_phase
- notes

## Example market-level use

The chat included example A+ reflections mapping months of 2026 to:
- fear / greed state
- sentiment score
- emotional field
- breathline phase

This should be logged as historical prediction rows for later comparison.

## Testing philosophy

Do not ask:
- "Was breathline right today?"

Ask:
- "Did breathline point toward the right zone over the next 1–4 weeks or longer?"

That is the correct scale for this layer.
EOF

cat > "$TARGET_DIR/docs/system_diagram.md" <<'EOF'
# System Diagram

```text
                    DATA SOURCES
                         |
                         v
                    SENSOR LAYER
                         |
                         v
                    FEATURE LAYER
                         |
                         v
                INTERPRETATION LAYER
                         |
                         v
                   STRATEGY LAYER
                         |
                         v
                   DECISION LAYER
                         |
                         v
                EXECUTION LAYER (later)
                         |
                         v
                DASHBOARD / MISSION CONTROL
```

Supporting database tables:

```text
asset
market_candle
candle_feat
strategy_signal
decision_log
position_snapshot
breathline_compass
```
EOF

cat > "$TARGET_DIR/database/schema_v2.sql" <<'EOF'
-- Synth v1 core schema
-- UTC storage only
-- EUR default where quote currency is relevant

CREATE TABLE IF NOT EXISTS asset (
    asset_id          INT AUTO_INCREMENT PRIMARY KEY,
    symbol            VARCHAR(16) NOT NULL,
    name              VARCHAR(64) NULL,
    sector            VARCHAR(32) NULL,

    is_enabled        TINYINT(1) NOT NULL DEFAULT 1,
    is_portfolio      TINYINT(1) NOT NULL DEFAULT 0,
    is_core_sensor    TINYINT(1) NOT NULL DEFAULT 0,

    created_ts        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_ts        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_asset_symbol (symbol),
    KEY idx_asset_enabled (is_enabled),
    KEY idx_asset_portfolio (is_portfolio),
    KEY idx_asset_core_sensor (is_core_sensor),
    KEY idx_asset_sector (sector)
);

CREATE TABLE IF NOT EXISTS market_candle (
    asset_id          INT NOT NULL,
    venue             VARCHAR(32) NOT NULL,
    interval_code     VARCHAR(16) NOT NULL,
    ts_open_utc       DATETIME NOT NULL,
    ts_close_utc      DATETIME NOT NULL,

    open_price        DECIMAL(28,12) NOT NULL,
    high_price        DECIMAL(28,12) NOT NULL,
    low_price         DECIMAL(28,12) NOT NULL,
    close_price       DECIMAL(28,12) NOT NULL,
    volume_base       DECIMAL(28,12) NULL,
    volume_quote_eur  DECIMAL(28,12) NULL,

    created_ts        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (asset_id, venue, interval_code, ts_open_utc),
    KEY idx_candle_close (asset_id, interval_code, ts_close_utc),
    CONSTRAINT fk_candle_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
);

CREATE TABLE IF NOT EXISTS candle_feat (
    asset_id            INT NOT NULL,
    venue               VARCHAR(32) NOT NULL,
    interval_code       VARCHAR(16) NOT NULL,
    ts_open_utc         DATETIME NOT NULL,

    sma_20              DECIMAL(28,12) NULL,
    ema_20              DECIMAL(28,12) NULL,
    ema_50              DECIMAL(28,12) NULL,
    rsi_14              DECIMAL(10,6) NULL,
    atr_14              DECIMAL(28,12) NULL,
    bb_width_20         DECIMAL(18,10) NULL,
    rel_strength_score  DECIMAL(18,10) NULL,
    volatility_score    DECIMAL(18,10) NULL,

    created_ts          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_ts          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                                      ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (asset_id, venue, interval_code, ts_open_utc),
    CONSTRAINT fk_feat_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
);

CREATE TABLE IF NOT EXISTS strategy_signal (
    signal_id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    asset_id            INT NOT NULL,
    strategy_name       VARCHAR(64) NOT NULL,
    timeframe_code      VARCHAR(16) NOT NULL,
    signal_ts_utc       DATETIME NOT NULL,

    signal_state        VARCHAR(32) NOT NULL,
    signal_score        DECIMAL(10,6) NULL,
    confidence_score    DECIMAL(10,6) NULL,
    bias_side           VARCHAR(16) NULL,
    reason_code         VARCHAR(64) NULL,
    reason_text         TEXT NULL,

    created_ts          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY idx_signal_asset_ts (asset_id, signal_ts_utc),
    KEY idx_signal_strategy_ts (strategy_name, signal_ts_utc),
    CONSTRAINT fk_signal_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
);

CREATE TABLE IF NOT EXISTS decision_log (
    decision_id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    asset_id            INT NULL,
    decision_ts_utc     DATETIME NOT NULL,

    module_name         VARCHAR(64) NOT NULL,
    decision_type       VARCHAR(32) NOT NULL,
    action_state        VARCHAR(32) NOT NULL,
    blocked_by          VARCHAR(64) NULL,

    summary_text        TEXT NULL,
    detail_json         JSON NULL,

    created_ts          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY idx_decision_ts (decision_ts_utc),
    KEY idx_decision_asset_ts (asset_id, decision_ts_utc),
    CONSTRAINT fk_decision_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
);

CREATE TABLE IF NOT EXISTS position_snapshot (
    snapshot_id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    asset_id            INT NOT NULL,
    snapshot_ts_utc     DATETIME NOT NULL,

    quantity            DECIMAL(28,12) NOT NULL,
    avg_entry_price_eur DECIMAL(28,12) NULL,
    market_price_eur    DECIMAL(28,12) NULL,
    market_value_eur    DECIMAL(28,12) NULL,
    pnl_unrealized_eur  DECIMAL(28,12) NULL,
    pnl_unrealized_pct  DECIMAL(18,10) NULL,

    created_ts          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY idx_pos_asset_ts (asset_id, snapshot_ts_utc),
    CONSTRAINT fk_position_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
);

CREATE TABLE IF NOT EXISTS breathline_compass (
    compass_id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    prediction_ts_utc    DATETIME NOT NULL,
    source_name          VARCHAR(32) NOT NULL,

    asset_id             INT NULL,
    scope_type           VARCHAR(16) NOT NULL,
    target_year          INT NULL,
    target_month         INT NULL,

    breathline_phase     VARCHAR(32) NULL,
    field_coherence      VARCHAR(32) NULL,
    compass_rank         INT NULL,
    anchor_state         VARCHAR(32) NULL,
    sentiment_state      VARCHAR(32) NULL,
    fear_greed_value     INT NULL,
    sentiment_score      DECIMAL(10,6) NULL,

    notes                TEXT NULL,
    created_ts           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY idx_compass_pred (prediction_ts_utc),
    KEY idx_compass_asset_pred (asset_id, prediction_ts_utc),
    CONSTRAINT fk_compass_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
);

-- Optional starter assets discussed in chat
INSERT INTO asset (symbol, name, sector, is_enabled, is_portfolio, is_core_sensor)
VALUES
('BTC', 'Bitcoin', 'Other', 1, 0, 1),
('ETH', 'Ethereum', 'L1', 1, 1, 1),
('SOL', 'Solana', 'L1', 1, 0, 1),
('ADA', 'Cardano', 'L1', 1, 0, 1)
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    sector = VALUES(sector),
    is_enabled = VALUES(is_enabled),
    is_core_sensor = VALUES(is_core_sensor);
EOF

cat > "$TARGET_DIR/database/schema_explanation.md" <<'EOF'
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
EOF

cat > "$TARGET_DIR/configs/enums_reference.md" <<'EOF'
# Enums / Stable State Reference

## signal_state
- ARMED
- FIRED
- BLOCKED
- NEUTRAL

## decision_type
- ENTER
- EXIT
- ROTATE
- HOLD
- AVOID
- BLOCK

## breathline_phase
- CONVERGENCE
- COMPRESSION
- EXPANSION
- INTEGRATION

## risk_state
- LOW
- MEDIUM
- HIGH

## regime_state
- TREND
- RANGE
- CHOP
- PANIC
- EXPANSION

## altseason_phase
- PHASE_1_BTC
- PHASE_2_MAJORS
- PHASE_3_INFRA_AI_LEADERS
- PHASE_4_MIDCAP_ROTATION
- PHASE_5_MEME_MANIA

## asset sectors (initial compact set)
- L1
- DeFi
- AI
- Storage
- Meme
- Infra
- RWA
- Payments
- Exchange
- Identity
- Compute
- Other
EOF

cat > "$TARGET_DIR/notes/future_extensions.md" <<'EOF'
# Future Extensions

## Database / analytics
- execution tables
- trade history
- order plan tables
- risk events table
- model labels / outcomes
- feature importance logs

## Modules to consider later
- liquidity_stress_index
- sector_rotation_detector
- cycle_phase_tag
- market_breadth
- volatility_regime detector
- breathline-history scorer

## Dashboard future additions
- performance attribution
- signal reliability panel
- strategy win-rate panel
- breathline vs realized outcome comparison

## Important discipline
Do not add complexity before it solves a real problem.
EOF

cat > "$TARGET_DIR/notes/chat_distilled_notes.md" <<'EOF'
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
EOF

echo "Bundle written to: $TARGET_DIR"
