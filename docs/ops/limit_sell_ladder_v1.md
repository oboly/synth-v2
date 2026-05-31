# Limit Sell Ladder V1

## Purpose

`src/execution/limit_sell_ladder_v1.py` is reusable execution plumbing for
manual passive limit `SELL` ladder construction.

It is intended for custom or loose scripts that already know:

- the token or market
- the TP or ladder reference levels
- the offset percentages
- the quantity percentages

## Scope

This module does:

- compute offset passive limit prices
- validate ladder level inputs
- build `BitvavoOrderRequest` objects
- preview those orders as serializable rows
- optionally place those orders through `BitvavoClient.place_order()`

This module does not:

- generate TP levels
- parse FFGRV inputs
- make strategy decisions
- read the database
- read account balances
- create market orders
- create `BUY` orders in v1

## Safety Boundary

Build and preview functions do not place broker orders.

Real placement happens only if:

1. `place_limit_sell_ladder_orders()` is called
2. `confirm_real_orders=True`
3. the existing `BitvavoClient` broker write permission env gate is explicitly
   enabled

That keeps the final broker write under the existing fail-closed Bitvavo client
permission boundary.

## Supported Order Shape

V1 supports only passive limit `SELL` orders with:

- `side=sell`
- `order_type=limit`
- `post_only=True`
- `time_in_force=GTC`

## Price Rule

For each ladder level:

```text
limit_price = level_price * (1 - offset_pct / 100)
```

This means the order is placed slightly below the supplied level when
`offset_pct > 0`.

## Quantity Rule

For each ladder level:

```text
amount = available_qty * quantity_pct / 100
```

The sum of `quantity_pct` across all levels must stay at or below `100`.

## Quantization

If the caller provides:

- `price_quantize`
- `amount_quantize`

then the builder quantizes those values before creating
`BitvavoOrderRequest` objects.

The caller is responsible for choosing quantization values that match the
exchange market precision they want to enforce.
