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
