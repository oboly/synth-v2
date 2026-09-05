# Fast Rotation C1 History Contract v1

Status: implementation contract, runtime activation not granted
Issue: #733
Upstream evidence owner: #593
Generic horizon semantics owner: #243
Downstream read-only consumers: #297 reporting, #591 horizon-aware interpretation

## 1. Decision

#593 discovery, validation, and frozen final holdout reproduced C1 out of sample.
The retained candidate is therefore persisted as raw market evidence without
changing its formula, sign, weights, thresholds, horizon meaning, or model
identity.

Frozen decision:

```text
C1 -> RETAIN_FOR_PERSISTENCE_DESIGN
C2 -> REJECT_BEFORE_FINAL_HOLDOUT
C3 -> INSUFFICIENT_DATA
```

C1 final-holdout evidence is recorded on #593 comment `5538185919`:

```text
coverage = 0.217125
raw forward IC:
  15m = -0.037217  Holm=true
  1h  = -0.034402  Holm=true
  4h  = -0.023647  Holm=true
  24h = -0.012149  Holm=true
lead median vs B1 = -5 x 15m samples
chop = 0.915882
```

The negative score/forward-response relationship is historical validated
evidence. Persistence does not flip sign or reinterpret positive/negative C1
scores into conventional directional trade semantics.

## 2. Existing-storage audit

The existing Rotation stores are not safe containers for C1:

- `market_rotation_snapshot_v1` / `market_rotation_observation_v1` are the
  append-only 24h/168h 1h-candle source/history lane;
- `market_rotation_pressure_snapshot_v1` /
  `market_rotation_pressure_observation_v1` are the separately promoted
  broad/regime Rotation Pressure V1 model with its own 24h/7d source ids,
  component scores, pressure states, and phase states;
- the canonical Rotation Pressure V1 promotion contract explicitly excludes
  #593 C1/C2/C3 from that V1 authority.

Reusing either schema would collapse distinct model/horizon semantics. #733
therefore adds the smallest additive storage owner:

```text
fast_rotation_c1_observation_v1
```

No generic signal-history framework is introduced.

## 3. Frozen C1 identity

Per #243, timing concepts remain distinct:

```text
candidate_id           = C1
rotation_model         = multi_horizon_rotation_relative_flow
rotation_model_version = 1.0.0-c1
input_interval         = 15m
lookback_horizon       = current_15m_plus_previous_8_completed_15m_windows
effective_horizon      = VERY_SHORT
observed_lifecycle     = UNMEASURED
source_provenance      = obs_market_candle:15m:close_price+volume_base;owner=public_candle_freshness_writer
```

`effective_horizon=VERY_SHORT` is the reviewed C1 producer declaration from
#593. It is not inferred from the 15m input interval. `observed_lifecycle`
remains explicitly `UNMEASURED` and is not inferred from either field.

Frozen validation provenance:

```text
replay_source_sha256 = 843475d2d44ae29d7393f369dcf876aa98a89b1c1941969a5c57db57192ce949
final_holdout_implementation_fingerprint = 657ae08b479daa63b8454e3b8198b64a872681ae57af3d4adc1cfd7be787186c
final_holdout_manifest = e5f00d7f1903f071a33a30eb91ac1f7a510c1b92e251d42059fc40f7ccc86c0f
final_holdout_source_composite = 6873bdc01846adb9115bccf84b87017d8c0b370b0db6ba49f2b78ed2e4dd3107
```

The manual materializer verifies the exact frozen replay-source SHA before
reading market data. Source drift therefore fails closed rather than writing
new rows under the old C1 model version.

## 4. Persisted row contract

Each row carries:

```text
venue
asset_id
market
asof_ts_utc
candidate_id
rotation_model
rotation_model_version
input_interval
lookback_horizon
effective_horizon
observed_lifecycle
rotation_score
relative_return_unit
signed_flow_unit
relative_acceleration_unit
cohort_size
evaluated_universe_size
coverage_ratio
freshness_state
data_quality
reason_code
source_provenance
frozen_replay_source_sha256
frozen_final_holdout_fingerprint
```

Logical identity is unique on:

```text
venue + market + rotation_model + rotation_model_version
+ effective_horizon + asof_ts_utc
```

Writes are idempotent. Existing logical rows are never overwritten with new
semantics.

Both `COMPLETE` and `INSUFFICIENT_DATA` C1 observations may be persisted so
coverage/data-quality history remains replayable rather than being silently
reconstructed from only successful rows. A `COMPLETE` row must carry all
three primitive units plus the raw `rotation_score`; an
`INSUFFICIENT_DATA` row may not carry a score.

### 4.1 Immutable coverage semantics

Coverage is persisted at evaluation time, not reconstructed later from the
current tradeable universe:

```text
cohort_size             = count of assets with complete C1 window primitives
evaluated_universe_size = exact canonical tradeable input universe evaluated at this as-of
coverage_ratio           = cohort_size / evaluated_universe_size
```

The materialization batch must contain exactly one result for every member of
that evaluated universe. `evaluated_universe_size <= 0`,
`cohort_size > evaluated_universe_size`, or result-count/denominator mismatch
fails closed.

Persisting the denominator is required because the tradeable universe may
change after the historical as-of. A later consumer can therefore replay the
coverage that was actually evaluated rather than accidentally dividing an
old cohort by today's universe size.

This operational per-as-of coverage is distinct from the aggregate #593
final-holdout `coverage=0.217125` validation statistic. The latter remains
frozen research evidence and is not copied into every live history row.

## 5. Computation and persistence boundary

Canonical flow for this slice:

```text
canonical obs_market_candle 15m history
-> frozen #593 C1 evaluator
-> #733 C1 contract validation/materialization
-> fast_rotation_c1_observation_v1
-> read-only downstream consumers
```

#733 does not fork or duplicate the C1 formula. The materializer consumes the
frozen evaluator result and performs only identity validation + persistence
mapping.

No score sign transformation, thresholding, directional classification,
ranking, aggregation, or conviction calculation is allowed in this layer.

## 6. Runtime state

`src/features/run_fast_rotation_c1_history_v1.py` is manual and dry-run by
default. It materializes exactly one explicit 15m-grid `--asof-ts` per run.
There is no `latest` fallback.

Database mutation requires a separate operations-owned writer authorization
for capability:

```text
fast_rotation_c1_history
```

#733 does not register/grant that capability and does not add a timer,
service, deployment, or production activation. Runtime activation, cadence,
retention cleanup, and any backfill execution remain separately reviewed
operations work.

The table supports the issue's >=30d operator-history target; this contract
does not silently delete historical evidence. A future retention job must
preserve the frozen #593 research evidence separately from live operational
retention.

## 7. Downstream ownership

```text
fast_rotation_c1_observation_v1 -> #297 reporting
```

#297 may render numeric history, freshness, coverage, and data quality. It may
not recompute C1 or invent score thresholds/colors that alter market truth.

```text
fast_rotation_c1_observation_v1 -> #591 horizon-aware interpretation
```

#591 may consume C1 under #243 semantics but may not mutate the primitive C1
score or collapse horizons into an opaque average.

## 8. Explicit non-goals and safety

This slice does not:

- change existing Rotation Pressure V1 tables or semantics;
- persist/promote C2;
- promote C3 beyond `INSUFFICIENT_DATA`;
- change #243 semantics;
- change `selection_engine`;
- add account awareness or decision permission;
- change `decision_gate`;
- create execution intent in `execution_planner`;
- touch executor/agents;
- make broker/private calls;
- submit orders;
- activate a runtime service/timer.

```text
market_only=1
account_awareness=0
selection_engine_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
production_activation=0
```
