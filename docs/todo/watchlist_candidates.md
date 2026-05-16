# TODO — Watchlist Candidates

## Status

Open watchlist / research intake lane.

This file tracks user-thesis candidates and asymmetric watchlist ideas before they become validated strategy candidates.

## Boundary

Watchlist candidate does not mean signal.

```text
watchlist candidate != buy signal
watchlist candidate != selection_engine modifier
watchlist candidate != advice_engine output
watchlist candidate != decision_gate permission
watchlist candidate != execution intent
watchlist candidate != order
```

Allowed:

- track candidate thesis
- verify venue availability
- inspect liquidity, spread, and candle history
- decide whether to add to asset metadata / research universe
- later validate through market-only research reports

Forbidden:

- direct BUY_READY
- direct order logic
- broker write
- executor activation
- decision_gate bypass

## P2 — KITE moonshot asymmetry candidate

Status: open.

User thesis:

```text
KITE is Bitvavo-listed.
User expects strong asymmetry and potential strong upside.
Treat as part of the user's high-asymmetry watchlist thesis.
```

Classification:

```text
symbol=KITE
venue=bitvavo
candidate_bucket=MOONSHOT_ASYMMETRY
source_type=USER_THESIS
validation_state=UNVALIDATED_WATCHLIST_CANDIDATE
runtime_allowed=false
```

Tasks:

- Verify KITE exists in local `asset` metadata and Bitvavo market data universe.
- If missing locally, add only through the normal asset/universe process.
- Check whether `KITE-EUR` candles are available in `obs_market_candle`.
- If candles are missing, decide whether Bitvavo candle ingestion should include KITE.
- Check liquidity, spread, candle history length, and minimum order constraints before any research promotion.
- Keep KITE out of selection/advice/decision/execution until market-only validation exists.
- If validated later, classify as `MOONSHOT_ASYMMETRY` or another explicit horizon bucket, not as a raw asset rank.

Initial research questions:

- Is KITE liquid enough on Bitvavo to exit during a pump?
- Does KITE have enough candle history for basic Market Breath / momentum / volatility analysis?
- Is the asymmetry thesis driven by market structure, narrative, supply, liquidity, or speculative rotation?
- Does KITE belong in short-term spike watchlist, moonshot asymmetry, or both as separate candidates?

## Related design docs

```text
docs/research/strategy_candidate_horizon_buckets_v1.md
docs/todo/strategy_candidates.md
docs/todo/deploy_runtime.md
```

## Non-goals

- No live trading.
- No direct buy/sell advice.
- No order placement.
- No broker writes.
- No runtime promotion from this file.
