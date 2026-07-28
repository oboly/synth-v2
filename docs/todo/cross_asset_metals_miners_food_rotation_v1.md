# Cross-Asset Metals, Miners and Food Rotation v1

## Status

```text
historical umbrella specification
active ownership split
no independent cross-lane priority
```

## Canonical owners

Public-data sourcing, provenance, neutral instrument identity, provider feasibility, and candle-ingest boundaries:

```text
docs/todo/external_research/cross_asset_public_data_and_instrument_registry_v1.md
```

Market-only normalization, rotation classification, replay, and feature-promotion research:

```text
docs/todo/market_intelligence/cross_asset_rotation_research_v1.md
```

## Standing architecture

```text
public source
-> provider adapter and neutral instrument registry
-> canonical observations
-> market-only rotation research
-> read-only reporting
-> optional human manual trade outside Synth runtime
```

Forbidden shortcut:

```text
research or reporting -> broker call
```

V1 contains no authenticated broker integration, account observation, execution intent, order handling, or automated trading.

Any future IBKR API work requires a separate proposal spanning the proper account, `decision_gate`, `execution_planner`, executor, and reconciliation layers. It may not reuse the public-data collector as an execution shortcut.

## Compatibility

This file remains only to preserve historical context and existing links. Status, priority, and implementation acceptance are owned by the canonical split TODOs and the top-level board.