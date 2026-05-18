# Trade Setup Fail Reason Diagnostic V1

## Status

Read-only diagnostic for latest market-only setup-filter state. It recomputes the current `trade_setup_filter_v1` engine result from latest selection candidates and BTC context, then joins available paper advice display context.

## Purpose

Fresh 4h paper advice snapshots can show many `SETUP_FAILED`, `WAIT`, or `NO EDGE` rows. This diagnostic explains which setup-filter guard is responsible before any production logic is changed.

## Layer Ownership

- `selection_state`: market candidate and priority rank.
- `trade_setup_filter_v1`: market-only setup eligibility.
- `paper_advice_policy_v1`: paper advice display and policy interpretation.
- lifecycle badges: dashboard path state from candle ranges.
- `decision_gate`: account-aware permission; not touched here.

`WATCHLIST` can coexist with setup `FAIL`: selection can mark a market as interesting while the setup filter blocks the current setup.

## Rank Sweet Spot Correction

The old rank `4..10` hard fail was inverted relative to intent. Rank `1..3` should not fail purely because it is top ranked.

Current production behavior uses rank `1..10` for setup eligibility. If a top-ranked candidate is risky, that must be supported by explicit overextension, chase-risk, lifecycle, momentum, or market-state metrics rather than rank alone.

## Runner

```bash
python -m src.research.run_trade_setup_fail_reason_diagnostic_v1 \
  --venue bitvavo \
  --interval 4h \
  --limit 80 \
  --output table
```

Focused symbol check:

```bash
python -m src.research.run_trade_setup_fail_reason_diagnostic_v1 \
  --venue bitvavo \
  --interval 4h \
  --symbol HYPE \
  --output table
```

## Output

The runner reports per symbol:

- rank and selection state
- recomputed setup-filter state
- fail primary reason and failed guard detail
- advice state, policy decision, confidence, and reason codes when available
- zone values when available from paper advice context

## Dashboard Display

The static paper advice dashboard now exposes the setup-filter primary fail reason when available. A row can show both the generic `SETUP FAILED` badge and the specific market-only guard, for example `MARKET_DAMAGE_RISK`.

`MARKET_DAMAGE_RISK` is separate from the old rank sweet spot issue. After the rank eligibility correction, HYPE can be rank-eligible at rank `1` while still failing setup because BTC prior 24h breached the configured market damage threshold.

The dashboard also appends the setup fail reason to the visible Reasons column, for example:

```text
SELECTION_WATCHLIST, SETUP_FAIL, MARKET_DAMAGE_RISK, APLUS_UNKNOWN, WATCHLIST_NO_FULL_PERMISSION
```

## Boundaries

This diagnostic does not write to the database, recompute zones, change policy, enable paper/live execution, call brokers, submit orders, or touch decision/execution layers.

## Recommended Use

Use this runner after each setup-filter change or 4h chain refresh to confirm whether failures are caused by selection state, rank range, BTC market context, or asset suitability. If reason detail is insufficient, add richer reason persistence in a separate reviewed patch.
