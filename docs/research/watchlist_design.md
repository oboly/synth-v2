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
