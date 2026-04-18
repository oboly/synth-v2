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
