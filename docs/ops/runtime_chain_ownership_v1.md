# Runtime Chain Ownership v1

## Core Rule

Dashboard is a read-only consumer.

Dashboard rendering must never own canonical market intake, candle ETL, feature
calculation, `signal_state` calculation, selection refresh, or broker/account
refresh.

## Canonical Ownership

- devlap is the sole public market-data database writer host; Odroid is a
  persisted-state consumer and publisher
- public prices are owned by
  `synth-market-price-snapshot-writer.timer` on devlap
- multi-interval candles are owned by
  `synth-market-candle-freshness-writer.timer` on devlap
- native SHORT map evaluation, scope-status projection, and map-level status
  projection are owned by the existing devlap 4h market chain; no
  second native SHORT timer or dashboard-side writer is permitted
- rotation-pressure persistence remains owned by its devlap writer; Odroid
  owns only the read-only publisher
- `feat_candle` is owned by the feature chain
- `signal_state` is owned by the signal chain / 4h chain
- downstream strategy and selection snapshots are owned by their chain runners
- dashboard only reads latest complete snapshots or DB state and renders
  visibility

## Allowed Dashboard-Side Behavior

- render HTML
- read DB or snapshot files
- display freshness status
- fail closed or show stale
- optionally read precomputed lightweight presentation snapshots

## Disallowed Anti-Patterns

- dashboard render triggers candle intake
- account/render orchestration writes public prices
- a stale-data check starts a repair writer instead of failing closed
- dashboard render recomputes `signal_state`
- dashboard render silently writes operational context
- failed refresh leaves stale data looking live
- strategy proposals shown without `input_context_run_id` or freshness status

## Freshness Contract

Every dashboard page or card must show:

- latest market timestamp
- latest signal timestamp
- account or order snapshot timestamp when account-aware
- data age
- stale or fresh status
- `run_id` or `snapshot_id` where available

## Agent / LLM Bridge Boundary

- signal dashboard shows facts
- strategy layer interprets signals
- LLM bridge may produce strategy proposals only
- proposals must include `strategy_id`, `input_context_run_id`, `created_ts`,
  and `expiry_ts`
- no broker writes
- no order submission
- no executor access

## Runtime Principle

- pipelines must keep running even if dashboard rendering fails
- dashboard failure must not stop data collection or signal computation
- data collection or signal computation failure must be visible in dashboard

## Reference

For repo-wide runtime and dashboard boundary rules, also see:

- `AGENTS.md`
- `docs/ops/synth_runtime_runners_v1.md`
- `docs/ops/public_market_data_runtime_owners_v1.md`
