# Research Candidate Candle Ingestion V1

## Purpose

This lane fetches public OHLCV candles for disabled research/watch candidates
such as APT and SXT without adding them to the normal Synth runtime universe.

It exists for market-data coverage checks, sparse-candle diagnostics, and later
research diagnostics only.

## Boundary

APT and SXT remain research/watch candidates:

- `is_enabled = 0`
- `is_tradeable = 0`
- `is_portfolio = 0`

Those flags prevent normal ETL, selection, advice, decision, execution planning,
and order handling participation. This runner does not update asset flags.

The runner uses public market-data endpoints only. It does not use private broker
API calls, broker writes, order submission, paper/live branching, selection
boosts, advice actions, decision permissions, execution plans, or A+ inputs.

## How This Differs From `run_chain_4h`

The normal Bitvavo candle ETL loads enabled assets from `asset WHERE
is_enabled = 1`. Research candidates are intentionally disabled, so they are not
included in `run_chain_4h` or the standard enabled-asset chain.

`run_research_candidate_candles_etl_v1.py` accepts explicit symbols and only
fetches candles for those symbols. Writes are off by default and require
`--write-db`.

## Market Availability

For each requested symbol, the runner checks the public Bitvavo market metadata
for `{SYMBOL}-{QUOTE}`.

Statuses:

- `ASSET_MISSING`: the symbol is not present in the local `asset` table.
- `MARKET_NOT_AVAILABLE`: the public venue metadata does not include the market.
- `DRY_RUN_OK`: market exists and candles were fetched, but no DB write occurred.
- `WRITTEN`: market exists and candles were upserted into `obs_market_candle`.
- `NO_CANDLES`: market exists but no candles were returned for the requested window.
- `FETCH_ERROR`: public metadata or candle fetch failed.

Unavailable markets do not fail the whole run.

## Manual Commands

Dry run:

```bash
python -m src.research.run_research_candidate_candles_etl_v1 \
  --venue bitvavo \
  --symbols APT SXT \
  --quote EUR \
  --interval 4h \
  --start 2026-01-01T00:00:00Z \
  --output table
```

Write research candles:

```bash
python -m src.research.run_research_candidate_candles_etl_v1 \
  --venue bitvavo \
  --symbols APT SXT \
  --quote EUR \
  --interval 4h \
  --start 2026-01-01T00:00:00Z \
  --write-db \
  --output table
```

For a small bounded validation window, prefer a recent start timestamp such as
30 days before the run.

## Verification

Confirm candidate flags:

```sql
SELECT
    asset_id,
    symbol,
    is_enabled,
    is_tradeable,
    is_portfolio
FROM asset
WHERE symbol IN ('APT', 'SXT')
ORDER BY symbol;
```

Confirm candle coverage:

```sql
SELECT
    a.symbol,
    c.venue,
    c.interval_code,
    COUNT(*) AS candles,
    MIN(c.close_ts_utc) AS first_close_ts_utc,
    MAX(c.close_ts_utc) AS latest_close_ts_utc
FROM asset a
LEFT JOIN obs_market_candle c
  ON c.asset_id = a.asset_id
 AND c.venue = 'bitvavo'
 AND c.interval_code = '4h'
WHERE a.symbol IN ('APT', 'SXT')
GROUP BY a.symbol, c.venue, c.interval_code
ORDER BY a.symbol;
```

The expected post-ingestion flag state is still:

- `is_enabled = 0`
- `is_tradeable = 0`
- `is_portfolio = 0`

## Downstream Path

```text
research candles
-> quality check
-> research diagnostics
-> later explicit decision before enabling in the normal chain
```

There is no runtime promotion in V1. Enabling assets for the standard chain,
selection, advice, decision, or execution requires a separate explicit change.

## Safety Markers

- `broker_calls = 0` / public market data only
- `broker_writes = 0`
- `order_submission = 0`
- `live_orders = 0`
- `selection_engine_changes = 0`
- `advice_engine_changes = 0`
- `decision_gate_changes = 0`
- `execution_planner_changes = 0`
- `executor_changes = 0`
