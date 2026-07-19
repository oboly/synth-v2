# Runtime Chain Ownership v1

## Core Rule

Dashboard is a read-only consumer.

Dashboard rendering must never own canonical market intake, candle ETL, feature
calculation, `signal_state` calculation, selection refresh, or broker/account
refresh.

## Canonical Ownership

Host ownership is governed by the explicit per-capability contract in
`docs/ops/writer_capability_host_ownership_contract_v1.md` and the registry
`deploy/ownership/writer_capability_ownership_v1.json`. Each public
market-data writer capability has exactly one `production_runtime_owner`,
assigned only by explicit host selection plus acceptance (`UNASSIGNED` until
then). The retired "devlap sole public market-data writer host" claim does not
apply; devlap is a candidate/acceptance host, and gurkDB is a preferred
candidate, not a proven owner. The capability-level structural rules below are
independent of which host is selected:

- exactly one production owner per writer capability; no consumer, reporting,
  or account runtime may run a public market-data writer or repair path
- the `public_price_snapshot` capability owns
  `synth-market-price-snapshot-writer.timer`
- the `public_candle_freshness` capability owns
  `synth-market-candle-freshness-writer.timer`
- native SHORT map evaluation, scope-status projection, and map-level status
  projection are owned by the single `native_short_4h_chain` capability; no
  second native SHORT timer or dashboard-side writer is permitted. This chain is
  host-evaluated separately from the light DB writers (CPU/repository/
  publication/artifact dependencies) and not auto-moved with them
- the 4h chain reads persisted public prices and candles through SELECT-only
  fail-closed validators before Native SHORT publication
- the 4h chain does not refresh public prices or candles and does not render or
  remotely transport dashboard output
- rotation-pressure persistence is owned by the `market_rotation_pressure`
  writer capability (the one capability with a recorded host acceptance, devlap
  per PR #100/#101); Odroid owns only the read-only publisher
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
- dashboard or linked-profile render reconstructs or publishes Native SHORT
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
