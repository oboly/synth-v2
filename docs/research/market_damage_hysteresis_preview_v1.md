# Market Damage Hysteresis Preview V1

## Status

Read-only research diagnostic.

## Purpose

Preview current `MARKET_DAMAGE_RISK` hard-threshold behavior against proposed BTC prior-24h caution/hysteresis bands before changing production setup-filter behavior.

Current production behavior hard-fails setup candidates when:

```text
btc_prior_24h < -0.015
```

Latest runtime diagnostics showed HYPE as the only `WATCHLIST` setup candidate, blocked by `MARKET_DAMAGE_RISK` with BTC prior 24h just below that threshold. This suggests threshold flapping risk around normal BTC chop.

## Proposed preview bands

```text
btc_prior_24h >= -0.015
  -> normal current path

-0.025 <= btc_prior_24h < -0.015
  -> caution band / not necessarily hard fail

btc_prior_24h < -0.025
  -> hard MARKET_DAMAGE_RISK

btc_prior_24h >= -0.010
  -> clear / recovery threshold if stateful hysteresis is introduced later
```

## Runner

```bash
python -m src.research.run_market_damage_hysteresis_preview_v1 --venue bitvavo --output table
```

## Boundary

```text
No trade_setup_filter production behavior change.
No selection_engine changes.
No decision_gate changes.
No execution_planner changes.
No executor changes.
No broker calls.
No broker writes.
No order submission.
No database writes.
```

This diagnostic is measurement only. Production changes require a separate reviewed patch.
