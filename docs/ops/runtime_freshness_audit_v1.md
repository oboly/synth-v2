# Runtime Freshness Audit v1

## Purpose

`src/operations/run_runtime_freshness_audit_v1.py` is a read-only runtime
freshness audit for the live-like market chain and dashboard support stages.

It does not call brokers.
It does not write the database.
It does not change strategy, decision, execution, or dashboard behavior.

## Scope

V1 checks the runtime stages that should stay fresh independently of dashboard
rendering, with focus on:

- `obs_market_candle` `4h`
- `feat_candle` `4h`
- `signal_state` `4h`
- `signal_engine_state` `4h`
- `paper_advice_observation` `4h`
- `selection_state`
- `obs_market_candle` `15m`
- `market_price_snapshot`
- existing account snapshot tables if present
- `strategy_runtime_snapshot` for `run_chain_4h`

## Output

The runner emits:

- `FRESH`
- `STALE`
- `MISSING`
- `UNKNOWN`

Per stage it reports:

- latest timestamp
- latest age
- row count
- per-asset coverage when possible
- worst stale or missing symbols when possible

`UNKNOWN` is used when a table or required schema shape cannot be identified
cleanly.

## Usage

Table output:

```bash
python -m src.operations.run_runtime_freshness_audit_v1 \
  --venue bitvavo \
  --output table
```

JSON output:

```bash
python -m src.operations.run_runtime_freshness_audit_v1 \
  --venue bitvavo \
  --output json
```

## Boundary

This runner is an audit surface only.

It must not become:

- a catch-up writer
- a timer owner
- a broker/account refresher
- a dashboard renderer

If a stage is stale, the fix belongs in the owning runtime chain or timer, not
inside the audit runner.
