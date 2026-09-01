# CQ v1 temporal population v1

Issue: #651
Parent: #568

This research-only runner builds the immutable multi-date point-in-time feature population for the already-frozen CQ v1 family. It consumes the frozen sampling contract from #646 / PR #647 and therefore uses exactly 45 UTC as-of timestamps from 2026-07-18 through 2026-08-31.

The selection/CQ-v0 inputs are reconstructed from `asset_interval_quality` and `signal_engine_state` using `MAX(timestamp) <= frozen_asof` per asset, venue and interval. The existing `selection_engine_v2` ranking logic and existing `entry_quality_shadow_v1` CQ-v0 logic are reused unchanged. Market Rotation Pressure uses the canonical aggregate and per-asset v1 tables with both observation and parent snapshot bounded to `<= frozen_asof`.

The builder never substitutes current/latest truth. Missing quality/signal evidence remains represented by the existing blocked/default selection semantics. Missing MRP stays unavailable. Historical sector context is always `UNAVAILABLE_HISTORICAL_MEMBERSHIP` because Phase A proved that canonical membership history is absent. PPP is always unavailable unless a separate canonical historical PIT artifact is supplied; this runner does not invent PPP.

No CQ v1 candidate scores or forward outcomes are calculated here. `obs_market_candle` is not directly consumed by frozen CQ v1 feature reconstruction in this slice; later candles remain reserved for the forward-label slice.

The Selection Engine v2 config is frozen by both path and SHA-256. A run fails closed if the configured path or file contents differ from the pinned contract. The selection-config SHA-256 is recorded in checkpoint, summary, manifest, every observation, and the deterministic `observation_id` identity alongside `asset_id`, `venue`, frozen `asof_ts_utc`, evidence-key hash, CQ model version, frozen model-family version and frozen coverage-artifact hash.

Output is restricted to `data/research/` and consists of `population.jsonl`, `summary.json`, `manifest.json`, plus `checkpoint.json` while the run is active or resumable. A clean SIGINT/SIGTERM writes `terminal_state=INTERRUPTED`, preserves the last committed per-as-of checkpoint, records a resumable summary, and exits 130. Resume requires the same frozen contract/config identity and truncates any uncheckpointed JSONL tail before continuing. Final `FINISHED` artifacts carry the population SHA-256. The runner performs database reads only and never writes reconstructed history into `research_entry_quality_shadow`.

Safety boundary:

```text
research_only=1
market_only=1
account_awareness=0
outcomes_read=0
db_writes=0
model_retuning=0
production_ranking_changes=0
decision_gate=none
execution_planner=none
executor=none
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
runtime_activation=0
```

Example on gurkdb after merge:

```bash
cd ~/projects/synth-v2
git pull --ff-only
python3 -m src.research.run_cq_v1_temporal_population_v1 \
  --venue bitvavo \
  --output-dir data/research/cq_v1_temporal_population_v1/20260831T180000Z
```

After interruption, resume the same output directory with `--resume`. The run is acceptable only if `summary.json` reports `terminal_state=FINISHED` and `unique_asof_count=45`. Outcome statistics must not be opened in this slice.
