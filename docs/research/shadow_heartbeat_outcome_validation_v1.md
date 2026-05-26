# Shadow Heartbeat Outcome Validation V1

## Purpose

`run_shadow_heartbeat_outcome_validation_v1.py` is a research-only runner that measures what happened after live-like shadow heartbeat states.

It validates heartbeat cohorts against forward market movement only:

- `ENTRY_CANDIDATE`: candidate-quality cohort
- `WAIT_RETEST`: setup-maturation cohort
- `NO_CANDIDATE`: baseline/noise cohort
- `BLOCKED`: safety/control cohort, not a bearish signal

This is outcome measurement only. It is not paper trading, not live trading, not execution, and not executor enablement.

## Inputs

The runner reads local heartbeat artifacts from:

- `data/research/live_like_shadow_chain_v1/run_*/chain_summary_v1.json`
- `data/research/live_like_shadow_chain_v1/run_*/manifest_v1.json`

When linked run dirs are still present, it also reads:

- candidate: `strategy_candidate_v1.json`
- decision: `decision_preview_v1.json`
- shadow event: `shadow_event_v1.json`

For forward outcomes, it reads market candles from `obs_market_candle` with explicit read-only research queries only.

Defaults:

- `--chain-root`: `data/research/live_like_shadow_chain_v1`
- `--output-dir`: `data/research/shadow_heartbeat_outcome_validation_v1`
- `--event-mode`: `all`
- `--cooldown-minutes`: `30`
- inferred `--symbol` from heartbeat history unless passed explicitly
- inferred `--venue` from heartbeat artifacts unless passed explicitly
- inferred `--interval` from heartbeat artifacts unless passed explicitly
- default interval fallback: `15m`

## Output files

Rows:

```text
data/research/shadow_heartbeat_outcome_validation_v1/outcome_rows_v1.jsonl
```

Summary:

```text
data/research/shadow_heartbeat_outcome_validation_v1/outcome_summary_v1.json
```

## Per-event output

Each event row includes:

- `event_ts`
- `symbol`
- derived cohort `state`
- raw `candidate_state`, `decision_state`, `execution_plan_state`
- `permission_state` when available
- available heartbeat labels such as `entry_state`, `label_state_15m`, `label_state_1h`
- `reference_price`
- future prices and returns at:
  - `15m`
  - `30m`
  - `1h`
  - `2h`
  - `4h`
  - `8h`
  - `24h`
- `max_forward_return_pct`
- `min_forward_return_pct`
- `mfe_pct`
- `mae_pct`
- hit flags for `+0.5%`, `+1.0%`, `-0.5%`, `-1.0%`
- sample completeness flags
- transition metadata from the prior heartbeat cohort for the same symbol

The primary cohort state for filtering is the normalized research cohort `state`, not the raw `candidate_state`, `decision_state`, or `execution_plan_state` fields. Those raw fields remain visible for inspection, but event filtering uses the derived cohort label:

- `ENTRY_CANDIDATE`
- `WAIT_RETEST`
- `NO_CANDIDATE`
- `BLOCKED`

This keeps cohort semantics stable across all event modes.

## Event overlap and modes

The shadow heartbeat can run every 5 minutes while the market context is still based on a 15m lane. That means many adjacent heartbeat rows can represent nearly the same market window, which creates autocorrelation and pseudo-sample-size inflation if every repeated row is treated as independent.

The validator now supports three sampling modes:

- `--event-mode all`
  - current behavior
  - every discovered event is used
- `--event-mode transition-only`
  - uses only events where the normalized cohort `state` changes versus the previous event for the same symbol
  - repeated same-state rows are skipped and reported as `skipped_transition_duplicate`
- `--event-mode cooldown`
  - keeps the first event for a given `symbol + state`
  - skips repeated rows of that same `symbol + state` until `--cooldown-minutes` has elapsed
  - skipped rows are reported as `skipped_cooldown`

Use `all` for raw heartbeat frequency diagnostics. Use `transition-only` or `cooldown` when you want more independent or semi-independent cohort samples.

## Summary output

The summary groups rows by cohort state and shows:

- `event_mode`
- `cooldown_minutes`
- count
- horizon-specific completeness counts:
  - `complete_15m`
  - `complete_30m`
  - `complete_1h`
  - `complete_2h`
  - `complete_4h`
  - `complete_8h`
  - `complete_24h`
- average and median returns per horizon
- average and median `mfe_pct`
- average and median `mae_pct`
- hit rates for `+0.5%`, `+1.0%`, `-0.5%`, `-1.0%`
- transition-aware counts when heartbeat history contains state changes
- discovery/usage diagnostics:
  - input runs discovered
  - events discovered
  - events used
  - events skipped by reason
- state transition count after filtering

Older output exposed only a single `complete` count, which meant `complete_24h`. On a fresh 15m heartbeat lane that often stays at `0` even when shorter horizons already have usable samples.

For this lane, shorter windows such as `15m`, `30m`, `1h`, and `2h` are expected to become informative first. The 24h window remains useful, but it should not hide earlier completeness.

## Safety guarantees

This runner is bounded to research and read-only validation:

- read-only
- no DB writes
- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `executor=none`
- `account_awareness=0`
- no strategy changes
- no decision gate changes
- no execution planner runtime changes
- no paper trading
- no live trading

It does not create orders, permissions, plans, or executor paths.

## Interpretation boundaries

Interpret these cohorts narrowly:

- `ENTRY_CANDIDATE`: measures candidate quality only
- `WAIT_RETEST`: measures setup maturation only
- `NO_CANDIDATE`: measures baseline/noise only
- `BLOCKED`: measures safety/control behavior only

The cohort mapping is derived from raw heartbeat states:

- `candidate_state=ENTRY_CANDIDATE` -> `ENTRY_CANDIDATE`
- `candidate_state` in `WAIT_RETEST`, `SHALLOW_RETEST_ACTIVE`, `NORMAL_RETEST_ACTIVE`, `DEEP_RETEST_ACTIVE`, `IMPULSE_ACTIVE` -> `WAIT_RETEST`
- `candidate_state=NO_CANDIDATE` -> `NO_CANDIDATE`
- `candidate_state` in `INVALIDATED`, `STALE`, or raw `decision_state=BLOCKED`, or raw `execution_plan_state=BLOCKED` -> `BLOCKED`
- everything else currently falls back to `NO_CANDIDATE`

This mapping is for research cohorting only. It is not decision permission, not execution intent, and not a change to runtime policy.

Do not convert the results into strategy rules yet.

This runner is not performance validation in the execution sense. It does not model fills, fees, slippage, sizing, or account constraints.

Non-overlap filtering does not make the study causal or execution-realistic. It only reduces repeated-state overlap in research sampling. This remains research-only and does not enable paper trading, live trading, execution, or executor behavior.

## CLI

Compile:

```bash
python -m py_compile src/research/run_shadow_heartbeat_outcome_validation_v1.py
```

Help:

```bash
python -m src.research.run_shadow_heartbeat_outcome_validation_v1 --help
```

Smoke summary:

```bash
python -m src.research.run_shadow_heartbeat_outcome_validation_v1 \
  --max-events 20 \
  --output summary
```

Smoke summary plus files:

```bash
python -m src.research.run_shadow_heartbeat_outcome_validation_v1 \
  --max-events 20 \
  --write-files \
  --output summary
```
