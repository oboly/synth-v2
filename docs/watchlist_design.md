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
