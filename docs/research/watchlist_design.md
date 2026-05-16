               3# Watchlist / Asset Role Design


## Current V1 decision

Keep it simple.

Do **not** create many separate watchlist universes yet.

## Tradable universe

In v1:

```text
tradable universe = all enabled assets
```

So a separate `tradable_universe` watchlist is not necessary.

Strategies can filter internally.

...

For now, avoid overengineering.

## Asset participation flags

Synth v2 now uses a minimal flag model for assets:

- `is_enabled`
- `is_tradeable`
- `is_portfolio`

### Definitions

- `is_enabled`: asset participates in ETL and the full signal pipeline
- `is_tradeable`: asset may result in actual trade decisions
- `is_portfolio`: asset belongs to the active portfolio focus set

### Notes

Older flags such as:
- `is_watch`
- `is_core_sensor`

are deprecated and should no longer be used in code or new schema logic.

## Research/watchlist candidate staging

When a user wants a token tracked before venue support is confirmed, add it as
metadata only:

- `is_enabled = 0`
- `is_tradeable = 0`
- `is_portfolio = 0`

This keeps the asset visible as a research/watchlist candidate without pulling it
into ETL, selection, advice, decision, execution planning, or order handling.
Only after a venue market is verified and candle/ticker ingestion is available
should a later migration consider enabling the asset.

### 2026-05-16 pending candidates

| Symbol | Name | Status | Reason |
|---|---|---|---|
| APT | Aptos | RESEARCH_CANDIDATE_NOT_TRADEABLE | No local Bitvavo candle/ticker evidence found yet; inserted with `is_enabled=0`, `is_tradeable=0`. |
| SXT | Space and Time | RESEARCH_CANDIDATE_NOT_TRADEABLE | No local Bitvavo candle/ticker evidence found yet; inserted with `is_enabled=0`, `is_tradeable=0`. |
| BILL | unknown | NEEDS_SYMBOL_DISAMBIGUATION | Ambiguous ticker/project/venue support unknown; do not insert as active asset until exact crypto asset and venue market are verified. |

These rows are not trading advice and do not create `BUY_READY`,
decision-gate permission, execution plans, broker writes, or order submission.
