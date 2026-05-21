# Overbreath by Regime Backtest v1

## Purpose

Research whether Market Breath `OVERBREATH_EXTENSION` behaves differently across macro regimes:

- `SIDEWAYS_MARKET`
- `BULL_MARKET`
- `BEAR_MARKET`
- `CRASH_MARKET`
- `SUPER_BULL_MARKET`
- `LIQUIDITY_ROTATION`

Hypothesis:

Overbreath may not always mean exhaustion. In sideways/bear regimes it may be a reduce/exit warning, while in bull/super-bull regimes it may be continuation/ride context.

## Runner

```bash
python -m src.research.run_overbreath_by_regime_backtest_v1 \
  --venue bitvavo \
  --interval 4h \
  --symbols BTC ETH SOL INJ RENDER HYPE \
  --write-files \
  --output table
```

Default output directory:

```text
data/research/overbreath_by_regime_backtest_v1/
```

## Outputs

- `event_table_v1.csv`
- `event_table_v1.jsonl`
- `summary_by_regime_v1.csv`
- `summary_by_regime_v1.json`
- `overbreath_by_regime_backtest_v1.md`
- `manifest_v1.json`

Generated outputs are ignored by git.

## Provisional Regime Classifier

No canonical long-term regime classifier exists yet. This runner therefore uses a provisional research-only classifier based on:

- BTC 10d / 30d / 60d return
- BTC drawdown from recent high
- BTC volatility spike proxy
- market-wide participation from recent 4h returns
- alt relative strength proxy

The classifier is not wired into runtime and must not be promoted without separate validation.

## Outcome Metrics

For every matching overbreath event, the runner measures:

- forward return after 1d, 3d, 5d, 10d, 21d
- 21d max favorable excursion
- 21d max adverse excursion
- drawdown before continuation
- continuation probability
- sharp reversal probability

## Policy Proxies

The policy comparisons are research proxies only:

- reduce immediately at overbreath
- partial reduce + trail
- hold through overbreath in bull/super-bull
- wait for breakdown confirmation
- short-term breath exit only
- long-term fibo hold only
- 50% long-term fibo bucket + 50% short-term breath trading bucket

These outputs do not create buy/sell rules, decision permissions, execution plans, or orders.

## Safety Boundary

- research-only
- market-only
- account-agnostic
- file-output only
- no decision_gate
- no execution_planner
- no executor
- no broker calls
- no broker writes
- no order submission
- no live orders
- no selection_engine behavior changes
