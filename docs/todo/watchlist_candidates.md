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

Status: research-watchlist-ready.

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

- Verify KITE exists in local `asset` metadata and Bitvavo market data universe. Done.
- If missing locally, add only through the normal asset/universe process. Done as market-data / analysis ingestion metadata.
- Check whether `KITE-EUR` candles are available in `obs_market_candle`. Done.
- Generate `feat_candle` and `signal_engine_state` for APT/KITE/SXT where snapshot alignment allows it. Done.
- Run sparse candle diagnostics for APT/KITE/SXT. Done.
- Check liquidity, spread, candle history length, and minimum order constraints before any research promotion.
- Keep KITE out of selection/advice/decision/execution until market-only validation exists.
- If validated later, classify as `MOONSHOT_ASYMMETRY` or another explicit horizon bucket, not as a raw asset rank.

Latest local status:

```text
report=data/research/kite_watchlist_candidate_check_v1/kite_watchlist_candidate_check_v1.json
feature_signal_status=docs/research/watchlist_feature_signal_status_v1.md
recommendation=RESEARCH_WATCHLIST_READY
asset_flags=is_enabled=1,is_tradeable=0,is_portfolio=0
candles=1h/4h/1d present through 2026-05-17 00:00:00 UTC
runtime_allowed=false
```

Related watchlist intake spot checks:

```text
APT: enabled for market-data / analysis ingestion only; non-tradeable; non-portfolio; 1h/4h/1d candles present; research-watchlist-ready from data coverage; daily strong, lower-timeframe reset/lagging.
KITE: enabled for market-data / analysis ingestion only; non-tradeable; non-portfolio; 1h/4h/1d candles present; strongest current watchlist read; low-liquidity/sparse caution.
SXT: enabled for market-data / analysis ingestion only; non-tradeable; non-portfolio; 1h/4h/1d candles present; reset/lagging and sparse-sensitive; 1h signal unavailable due to sparse candle snapshot alignment.
ASX: not in scope; user clarified it is not of interest.
```

Sparse candle status:

```text
APT 1h: NO_TRADE_GAP; 4h/1d: HEALTHY.
KITE 1h: NO_TRADE_GAP; 4h: HEALTHY; 1d: SHORT_HISTORY.
SXT 1h: ILLIQUID_MARKET; 4h: NO_TRADE_GAP; 1d: DATA_GAP / window-context review.
```

Reproducibility note:

```text
APT/KITE/SXT asset metadata changes are current local DB state.
If this must be reproducible on a fresh environment, create a separate reviewed migration/seed task.
```

Initial research questions:

- Is KITE liquid enough on Bitvavo to exit during a pump?
- Does KITE have enough candle history for basic Market Breath / momentum / volatility analysis?
- Is the asymmetry thesis driven by market structure, narrative, supply, liquidity, or speculative rotation?
- Does KITE belong in short-term spike watchlist, moonshot asymmetry, or both as separate candidates?
- Should sparse/no-trade candles remain gaps, or should a separate reviewed synthetic no-trade gap policy be designed?
- Should the signal runner support asset-specific latest snapshot fallback for sparse assets?

## Related design docs

```text
docs/research/strategy_candidate_horizon_buckets_v1.md
docs/research/watchlist_feature_signal_status_v1.md
docs/todo/strategy_candidates.md
docs/todo/deploy_runtime.md
```

## Non-goals

- No live trading.
- No direct buy/sell advice.
- No order placement.
- No broker writes.
- No runtime promotion from this file.
