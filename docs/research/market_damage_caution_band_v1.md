# Market Damage Caution Band V1

## Status

Production-behavior proposal, market-only setup-filter layer.

## Purpose

Replace the overly sharp BTC 24h hard-fail boundary with a two-step market damage model.

Previous behavior:

```text
btc_prior_24h < -0.015
  -> MARKET_DAMAGE_RISK
  -> setup_filter_state = FAIL
```

New proposed behavior:

```text
btc_prior_24h < -0.025
  -> MARKET_DAMAGE_RISK
  -> setup_filter_state = FAIL

-0.025 <= btc_prior_24h < -0.015
  -> MARKET_DAMAGE_CAUTION
  -> setup_filter_state = FAIL

btc_prior_24h >= -0.015
  -> normal setup path
```

## Rationale

The preview diagnostic showed HYPE as the only current WATCHLIST setup candidate. It was blocked by MARKET_DAMAGE_RISK with BTC prior 24h only slightly below the old hard boundary.

The new caution band does not promote the setup to PASS. It only distinguishes mild BTC market pressure from hard market damage.

## Boundary

```text
market-only setup-filter behavior only
no selection_engine shortcut
no decision_gate change
no execution_planner change
no executor change
no broker calls
no broker writes
no order submission
```

## Follow-up

A later reviewed patch may decide whether MARKET_DAMAGE_CAUTION should remain a setup FAIL, become a separate CAUTION state, or feed a downstream paper-policy WATCH_ONLY rule after validation.

