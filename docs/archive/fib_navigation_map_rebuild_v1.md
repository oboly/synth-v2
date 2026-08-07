Status: Archived historical record
Active ownership: none
Current work: see canonical documentation / GitHub Issues
Archived by: docs/TODO cleanup Batch 4A

Implementation: `src/market_data/fib_navigation_map_v1.py`
Tests: `tests/test_fib_navigation_map_v1.py`, `tests/test_fib_navigation_map_exhaustion_rebuild_v1.py`

---

# TODO: Fib navigation map rebuild v1

**Status: IMPLEMENTED** — branch `feature/fib-navigation-map-rebuild-v1`. Candle-driven rebuild is the primary path; anchor-only is the fallback.

Fix the fib-map lifecycle issue where exhausted/legacy targets cause cards to show no usable fib levels, even while recent candles clearly contain a fresh breakout/impulse.

## Core rule

Target lifecycle and fib-map lifecycle are separate.

A completed/exhausted target list means:
- old target lifecycle is complete
- old map may be EXHAUSTED
- new navigation map should be attempted from fresh candles

It does not mean:
- no levels
- no context
- no navigation

## Safety

Do not:
- deploy to Odroid
- restart services
- write to /var/www/html
- overwrite live dashboards
- push unless explicitly requested

Only:
- create a feature branch
- implement locally
- run local tests
- update docs
- report results

## Architecture

Fib navigation belongs in a market-only layer.

Forbidden in fib builder:
- account state
- balances
- open orders
- decision_gate
- execution_planner
- executor
- agents
- dashboard rendering

Dashboard displays the map. It does not build the map.

## Required states

Support:
- FRESH
- STALE
- EXHAUSTED
- FALLBACK
- EMERGENCY_REBUILT
- NO_DATA
- LOW_CONFIDENCE

## Required rebuild triggers

Support:
- MAP_MISSING
- MAP_STALE
- MAP_EXHAUSTED
- PRICE_ABOVE_TOP_TARGET
- PRICE_BELOW_INVALIDATION
- NEW_HIGH_WITH_VOLUME_EXPANSION
- NEW_LOW_WITH_VOLUME_EXPANSION
- IMPULSE_MOVE_GT_ATR_MULTIPLE
- ALL_TARGETS_PASSED

Volume may increase confidence, but lack of volume must not block navigation if the price impulse is clear enough.

## SXT expected case

Input:
- low: 0.006571
- high: 0.010127
- current: 0.009588

Expected retracement supports:
- 23.6: 0.009288
- 38.2: 0.008768
- 50.0: 0.008349
- 61.8: 0.007930
- 78.6: 0.007332
- 100: 0.006571

Expected extension targets:
- 1.272: 0.011094
- 1.414: 0.011599
- 1.618: 0.012325
- 2.000: 0.013683
- 2.272: 0.014650
- 2.414: 0.015155
- 2.618: 0.015881
- 3.000: 0.017239
- 4.236: 0.021635

Expected behavior:
- old/legacy map marked EXHAUSTED
- new map attempted from fresh 15m candles
- map_state is EMERGENCY_REBUILT or FALLBACK
- card must not collapse to “No upcoming levels”
- trading action may remain NAVIGATION_ONLY or MANUAL_REVIEW

## Tests required

Add targeted tests for:
1. SXT bullish emergency rebuild.
2. All targets passed triggers rebuild attempt.
3. No candles or stale candles returns NO_DATA or STALE.
4. Bearish mirror calculation.
5. Architecture guard: fib builder imports no account/order/execution/dashboard modules.

## Deliverable report

Report:
- branch name
- files changed
- tests run
- SXT emergency rebuild pass/fail
- whether UI preview page was added
- confirmation that no deploy/restart/webroot change was done
- final verification commands
