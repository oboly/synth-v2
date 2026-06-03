# HTF Fib Extension Confluence Map V1

## Purpose

`htf_fib_extension_confluence_v1` is a pure-computation research helper that
detects HTF swing ranges and calculates fib extension target zones with
confluence metadata.

It does not:

- submit orders
- write to any database
- read from any database
- call any broker or exchange
- create `decision_gate` permission
- create `execution_planner` intent
- enable `executor`
- reference account state, balances, or positions

## Boundary

This module lives in `src/research/` and is subject to the research boundary:

- future-aware data is permitted in research context
- output must not be promoted into the live selection engine, decision_gate,
  execution_planner, or executor without an explicit gated promotion step
- the module may be used freely in backtest, paper review, and chart annotation

## Module

```
src/research/htf_fib_extension_confluence_v1.py
```

No DB imports. No broker imports. Pure `Decimal` arithmetic on caller-provided
swing anchors.

## Inputs

```python
HtfSwingInput(
    symbol="GENERIC",
    interval_code="1d",
    swing_low=Decimal("0.30"),         # HTF structural low; leg start
    swing_high=Decimal("0.65"),        # previous peak; serves as breakout_gate
    current_price=Decimal("0.68"),
    prior_high_price=Decimal("0.75"),  # optional; prior structural resistance
)
```

## Extension Formula

All extensions are anchored from the swing range. Never `current_price * fib`.

```
leg  = swing_high - swing_low
ext  = swing_low + leg * fib_level
```

Extension levels:

| Label       | fib_level |
|-------------|-----------|
| ext_1_272   | 1.272     |
| ext_1_618   | 1.618     |
| ext_2_000   | 2.000     |

## Outputs

`HtfExtensionConfluenceMap` fields:

| Field                          | Type                               | Notes                                              |
|--------------------------------|------------------------------------|----------------------------------------------------|
| `symbol`                       | str                                |                                                    |
| `interval_code`                | str                                |                                                    |
| `swing_low`                    | Decimal                            |                                                    |
| `swing_high`                   | Decimal                            |                                                    |
| `breakout_gate`                | Decimal                            | == swing_high; the previous structural peak        |
| `leg_size`                     | Decimal                            | swing_high - swing_low                             |
| `current_price`                | Decimal                            |                                                    |
| `targets`                      | tuple[FibExtensionTarget, ...]     | one entry per extension level, ascending by price  |
| `price_band`                   | str                                | where current price sits in the ladder             |
| `ext_1_272_touched_and_rejected` | bool                             | prior_high ≥ ext_1_272 and current < ext_1_272     |
| `retesting_breakout_gate`      | bool                               | near breakout_gate after a prior extension touch   |

`FibExtensionTarget` fields:

| Field                     | Type    | Notes                                                  |
|---------------------------|---------|--------------------------------------------------------|
| `label`                   | str     | "ext_1_272" / "ext_1_618" / "ext_2_000"               |
| `fib_level`               | Decimal |                                                        |
| `price`                   | Decimal |                                                        |
| `pct_above_swing_high`    | Decimal | % above the breakout gate                              |
| `distance_to_current_pct` | Decimal | % distance from current price; positive = above        |
| `round_number_confluence` | bool    | price near a round-step boundary (configurable)        |
| `prior_high_confluence`   | bool    | price within resistance_proximity_pct of prior_high    |

`price_band` values:

- `BELOW_BREAKOUT_GATE`
- `ABOVE_GATE_APPROACHING_1272`
- `BETWEEN_1272_1618`
- `BETWEEN_1618_2000`
- `ABOVE_2000`

## Example

```python
from decimal import Decimal
from src.research.htf_fib_extension_confluence_v1 import HtfSwingInput, build_htf_extension_map

anchor = HtfSwingInput(
    symbol="GENERIC",
    interval_code="1d",
    swing_low=Decimal("0.30"),
    swing_high=Decimal("0.65"),
    current_price=Decimal("0.68"),
)

result = build_htf_extension_map(anchor, round_step=Decimal("1"))

# breakout_gate = 0.65  (previous structural high)
# ext_1_272    ≈ 0.7452 (first extension target)
# ext_1_618    ≈ 0.8663 (stronger spike target)
# ext_2_000    = 1.0000 → round_number_confluence = True
# price_band   = "ABOVE_GATE_APPROACHING_1272"
```

## Confluence Flags

### `round_number_confluence`

True when the extension price lands within `round_threshold_frac` of a
`round_step` boundary. Default `round_step=1`, `round_threshold_frac=0.02`.

Pass `round_step=Decimal("0.5")` for assets with meaningful half-unit levels.

### `prior_high_confluence`

True when the extension price is within `resistance_proximity_pct` (default 2%)
of `prior_high_price`. Requires `prior_high_price` to be provided.

### `ext_1_272_touched_and_rejected`

True when:
- `prior_high_price >= ext_1_272`
- `current_price < ext_1_272`

Indicates the first extension was reached and price has since pulled back below
it — a potential re-entry or re-accumulation context.

### `retesting_breakout_gate`

True when:
- `current_price` is within `gate_retest_proximity_pct` (default 2%) of
  `swing_high`
- `prior_high_price >= ext_1_272` (extension was previously touched)

Indicates price has returned to the breakout gate after an extension excursion —
a common re-test setup.

## Parameters

`build_htf_extension_map` accepts keyword overrides:

| Parameter                  | Default | Purpose                                         |
|----------------------------|---------|-------------------------------------------------|
| `round_step`               | 1       | step size for round-number check                |
| `round_threshold_frac`     | 0.02    | fraction of step considered "near round"        |
| `resistance_proximity_pct` | 2       | % tolerance for prior_high_confluence           |
| `gate_retest_proximity_pct`| 2       | % tolerance for retesting_breakout_gate         |

## Safety

```
broker_writes=0
order_submission=0
db_writes=0
db_reads=0
account_tables_used=false
executor=none
research_only=true
```
