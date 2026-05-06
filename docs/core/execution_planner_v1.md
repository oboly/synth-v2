# Execution Planner v1

## Doel

Zet decision output om naar execution_plan + capital reservation.

---

## Flow

decision → plan → reservation → sleeve update

---

## Wat hij doet

- insert execution_plan
- insert capital_reservation
- update portfolio_sleeve:
  - reserved += amount
  - available -= amount

---

## Intent mapping

PREPARE_PLAN:
- plan_state = IDLE

PLACE_PASSIVE_LIMIT:
- plan_state = PLANNED

---

## Belangrijk

Planner doet GEEN:

- permission checks
- marktlogica
- execution



## Contract preview ladder support

Status: preview-only.

The execution planner contract preview supports ladder-shaped plans without touching runtime execution.

Supported intent mapping:

| Intent type | Side | Plan type | Meaning |
|---|---:|---|---|
| `PLACE_PASSIVE_LIMIT` | `BUY` | `PASSIVE_ENTRY` | Single passive entry leg |
| `EXIT_PASSIVE_LIMIT` | `SELL` | `PASSIVE_EXIT` | Single passive exit leg |
| `PLACE_LADDER` | `BUY` | `PASSIVE_ENTRY_LADDER` | Multi-leg passive buy ladder |
| `EXIT_LADDER` | `SELL` | `PASSIVE_EXIT_LADDER` | Multi-leg passive sell / exit ladder |

Explicit restriction:

- `PLACE_LADDER` is currently BUY-only.
- SELL ladders must use `EXIT_LADDER`.
- `asset_exit_profile_hint` is metadata only.
- Contract preview does not write to DB.
- Contract preview does not call executor.
- Contract preview does not create reservations.
- Contract preview does not call broker/live order APIs.

### Ladder validation rules

Ladder levels are passed as comma-separated `price:fraction` pairs.

Example:

`13.00:0.25,15.00:0.35,18.00:0.40`

Validation:

- fractions must sum to `1.0`
- all prices must be greater than zero
- all fractions must be greater than zero
- BUY ladder prices must be descending or equal
- SELL ladder prices must be ascending or equal

### Passive price convention

Single passive leg pricing:

- BUY: `best_bid + 1 tick`
- SELL: `best_ask - 1 tick`

Ladder leg pricing:

- explicit ladder prices are quantized down to tick size
- per-leg quantity is calculated from `quantity_base * target_fraction` when `quantity_base` is provided
- BUY ladder notional allocation is not yet modeled per leg

### Example: passive BUY preview

Command:

`python -m src.execution_planner.run_execution_planner_contract_preview_v1 --account-id 1 --sleeve-code SWING_STRUCTURAL --asset-id 1 --symbol LINK --venue bitvavo --side BUY --intent-type PLACE_PASSIVE_LIMIT --max-notional-eur 100 --decision-state EXECUTION_ALLOWED --decision-reason CONTRACT_PREVIEW_SINGLE_BUY --reference-price-eur 12.500 --best-bid-eur 12.490 --best-ask-eur 12.510 --tick-size 0.001 --spread-bps 16 --volatility-bucket MID --regime-label TREND_UP --output table`

Expected passive price:

`12.490 + 0.001 = 12.491`

### Example: passive BUY ladder preview

Command:

`python -m src.execution_planner.run_execution_planner_contract_preview_v1 --account-id 1 --sleeve-code SWING_STRUCTURAL --asset-id 1 --symbol LINK --venue bitvavo --side BUY --intent-type PLACE_LADDER --max-notional-eur 100 --decision-state EXECUTION_ALLOWED --decision-reason CONTRACT_PREVIEW_BUY_LADDER --reference-price-eur 12.500 --best-bid-eur 12.490 --best-ask-eur 12.510 --tick-size 0.001 --spread-bps 16 --volatility-bucket MID --regime-label TREND_UP --ladder-levels "12.40:0.50,12.20:0.30,12.00:0.20" --output table`

Expected plan type:

`PASSIVE_ENTRY_LADDER`

### Example: passive SELL exit ladder preview

Command:

`python -m src.execution_planner.run_execution_planner_contract_preview_v1 --account-id 1 --sleeve-code SWING_STRUCTURAL --asset-id 1 --symbol LINK --venue bitvavo --side SELL --intent-type EXIT_LADDER --quantity-base 10 --decision-state EXECUTION_ALLOWED --decision-reason CONTRACT_PREVIEW_EXIT_LADDER --reference-price-eur 12.500 --best-bid-eur 12.490 --best-ask-eur 12.510 --tick-size 0.001 --spread-bps 16 --volatility-bucket MID --regime-label TREND_UP --asset-exit-profile-hint CONTROLLED_3X4X_TOP_HEAVY --ladder-levels "13.00:0.25,15.00:0.35,18.00:0.40" --output table`

Expected plan type:

`PASSIVE_EXIT_LADDER`

Expected quantities when `quantity_base = 10`:

| Leg | Fraction | Quantity |
|---:|---:|---:|
| 1 | `0.25` | `2.50` |
| 2 | `0.35` | `3.50` |
| 3 | `0.40` | `4.00` |

### Layer boundary

Fib/pro/exit profile research must not create orders directly.

Correct path:

asset_exit_profile candidate
-> decision_gate validates actual position / sleeve / permission
-> execution_planner builds passive / urgent / ladder plan
-> executor places / monitors orders only

Executor must not interpret fib/pro/profile logic.
