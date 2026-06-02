# Synth v2.15 Runtime Signal Ownership v1

## Purpose

Remove the runtime ownership ambiguity between `signal_state` and
`signal_engine_state` before building any new advice route or signal inventory
matrix.

## Canonical Live Signal Table

Canonical live signal table:

- `signal_engine_state`

Confirmed by active runtime code paths:

- `src/signal_engine/run_signal_state_etl.py`
- `src/engine/write_signal_engine_state.py`
- `src/advice/run_advice_engine.py`
- `src/ranking/run_ranking_engine.py`
- `src/selection/run_selection_engine_v2.py`

The live 1h / 4h / 1d chain runs `src.signal_engine.run_signal_state_etl`, and
that runner writes only to `signal_engine_state`.

## Status of `signal_state`

`signal_state` is legacy and not the canonical live runtime signal table.

Current repo evidence:

- active chain runners call `run_signal_state_etl`, but that module writes
  `signal_engine_state`
- active advice, ranking, and selection readers join `signal_engine_state`
- the runtime freshness audit sees `signal_state` as stale and only partially
  populated
- no active runtime ownership path was found that refreshes `signal_state` as
  the live downstream input for advice or selection

Operational interpretation:

- `signal_state` should be treated as legacy or historical carryover
- runtime freshness gates for live signals should check `signal_engine_state`
- new advice-route work should not depend on `signal_state`

## Writer Ownership

Writer module:

- `src/engine/write_signal_engine_state.py`

Writer entrypoint used by the live chain:

- `src/signal_engine/run_signal_state_etl.py`

Chain owner:

- `scripts/run_chain_4h.sh` for 4h
- `scripts/run_chain_1h.sh` for 1h
- `scripts/run_chain_1d.sh` for 1d

## Why 4h Can Look One Step Behind

The signal runner does not blindly use the newest raw 4h candle boundary.

`fetch_snapshot_ts()` in `src/signal_engine/run_signal_state_etl.py` selects the
latest `feat_candle.close_ts_utc` snapshot that passes an enabled-asset
coverage gate:

- `min_snapshot_rows = 20` for `1h`, `4h`, and `1d`
- only enabled assets count toward that gate
- if the newest feature snapshot is incomplete, the runner falls back to the
  latest earlier eligible snapshot

Implication:

- raw `obs_market_candle` may already show `12:00Z`
- `feat_candle`, `signal_engine_state`, `advice_state`, and `ranking_state` may
  still remain on `08:00Z` until the `12:00Z` feature snapshot is sufficiently
  complete

This is expected completed-snapshot behavior if the newest 4h feature snapshot
is still under-covered at chain run time.

It becomes a runtime lag only if:

- the `12:00Z` feature snapshot is already complete enough, but signals still do
  not advance
- or the chain misses the next eligible completed cycle

## Freshness Interpretation

For 4h runtime health:

- `PASS` when `signal_engine_state` is at the latest completed eligible 4h
  snapshot
- `WARN` when the newest raw 4h candle exists but the signal chain is still on
  the previous completed eligible snapshot
- `FAIL` when the chain misses a completed eligible cycle or falls materially
  beyond expected chain timing

This means a newer raw candle timestamp alone is not enough to mark live signal
state as failed.

## Runtime Gate Rule

For live-signal ownership and freshness checks:

- use `signal_engine_state`
- do not use `signal_state` as the canonical runtime gate

## Remaining Non-Ownership Issues

This ownership clarification does not by itself fix:

- dashboard-side refresh coupling
- incomplete 4h feature coverage for the newest snapshot
- stale legacy `signal_state` rows still present in the database

Those remain separate runtime cleanup items.
