# Synth v2.5 TODO

Status: active TODO list  
Scope: current Synth v2.5 system state  
Archive note: files in `docs/archive/` are historical reference only and are not active TODO sources.

---

## Current State

Signal backfill status:

- 1d signal backfill completed.
- 4h signal backfill completed.
- 1h signal backfill completed after safe resume from `2025-05-03 00:00:00`.
- Resume log:
  - `/tmp/synth_signal_backfill/signal_1h_resume_20250503.log`
- Completion marker:
  - `[DONE] signal backfill rows=317279 interval=1h venue=bitvavo`

Original signal completion markers:

- 1d:
  - `[DONE] signal backfill rows=54286 interval=1d venue=bitvavo`
- 4h:
  - `[DONE] signal backfill rows=314737 interval=4h venue=bitvavo`
- 1h resume:
  - `[DONE] signal backfill rows=317279 interval=1h venue=bitvavo`

Runtime status at completion:

- no `run_signal_backfill` process running
- no advice writers running
- no replay/paper/oracle writers running
- chain crons temporarily paused:
  - `run_chain_1h.sh`
  - `run_chain_4h.sh`
  - `run_chain_1d.sh`

Do not restore chain crons until the immediate post-backfill research steps are stable.

---

## Current Priority

### 1. Rebuild replay/eval chain after completed signal backfill

Required sequence:

1. Confirm signal coverage samples.
2. Rebuild `bt_selection_v2_replay`.
3. Refresh `bt_selection_v2_replay_eval_horizon_v2`.
4. Export/stage paper candidates.
5. Run paper candidate scoreboards.
6. Run curve/risk comparisons.
7. Connect UI markers only after research tables exist.
8. Continue minimal backtest pipeline hardening.

Rules:

- Rebuild one stage at a time.
- Verify each stage before starting the next.
- Keep research outputs in research/backtest namespace.
- Do not write to decision/execution/account/order tables.
- Do not silently mix operational DB and research DB.

Expected runners / tools:

- `src.research.run_selection_v2_replay_backfill`
- `src.research.run_replay_policy_eval_horizon_v2`
- `src.research.run_arena_v2_paper_candidate_stage_bridge_v1`
- `src.research.run_paper_candidate_stage_writer_v1`
- `src.research.run_paper_candidate_stage_inspect_v1`
- `src.research.run_paper_candidate_batch_scoreboard_v1`
- `src.research.run_paper_candidate_curve_compare_v1`
- `src.research.run_paper_candidate_curve_risk_metrics_v1`
- `src.research.run_paper_candidate_risk_scoreboard_v1`

---

### 2. Signal coverage follow-up

Indexed coverage sample completed for:

- BTC
- ETH
- SOL
- ADA
- XRP
- SUI
- HBAR
- HOT
- XLM
- LINK

Intervals checked:

- 1d
- 4h
- 1h

Observed latest coverage included:

- 1d latest: `2026-05-01 00:00:00`
- 4h latest around: `2026-05-02 12:00:00`
- 1h latest around: `2026-05-02 16:00:00`

LINK now has signal coverage:

- LINK 1d: `2026-05-01 00:00:00`
- LINK 4h: `2026-05-02 12:00:00`
- LINK 1h: `2026-05-02 16:00:00`

Next LINK check is replay coverage, not raw/feature/signal repair.

---

### 3. Research DB boundary

Current issue:

- Some research/backtest tables may exist in `synth_bt` but not in operational/source DB.
- Examples:
  - `bt_selection_v2_replay`
  - `bt_selection_v2_replay_eval_horizon_v2`
  - `research_paper_candidate_signal`

Preferred split:

- `synth` = operational/source DB
- `synth_bt` = research/backtest write target

Rules:

- Operational DB may be read as source.
- Backtest/research writes should preferably go to research/backtest schema.
- Do not pollute operational runtime tables with backtest outputs.
- UI should later make marker DB/source explicit.

---

### 4. Minimal backtest pipeline end-to-end

Goal:

- Get one clean minimal backtest pipeline working end-to-end before expanding.

Preferred path:

1. candles available
2. features available
3. signal states available
4. selection/advice snapshots available
5. replay/evaluation table or export available
6. one report showing forward returns by state/setup

Priority:

- complete one working loop first
- then iterate
- do not optimize strategy on incomplete data

---

### 5. Known strategy-family testing

Do not try to rediscover everything from scratch.

Start from known families:

- trend continuation
- pullback/reclaim
- range rotation
- breakout failure
- MTF vs no-MTF legacy priors
- volume-confirmed setup
- BTC-relative / market-relative strength

Legacy priors:

- LINK/XLM: no-MTF candidates
- HBAR/HOT/HYPE: MTF/adaptive candidates
- SUI/XRP/DEEP: caution / retest

Synth v1 ADAPTIVE meaning:

- `ADX >= threshold -> TREND -> no-MTF`
- `ADX < threshold -> CHOP -> MTF`

Architecture lesson:

- regime selector first
- strategy selector second
- avoid hard-wiring everything into one strategy matrix

Canonical reference:

- `docs/legacy_synth_v1_regime_strategy_priors.md`

---

## Supporting Priorities

### 6. Stabilize UI/chart framework v1

Current app:

- `apps/synth_chart_app_v1.py`
- `src/ui_chart/chart_repository.py`
- `src/ui_chart/chart_assembler.py`
- `src/ui_chart/chart_renderer.py`
- `src/ui_chart/chart_config.py`

Current status:

- Initial read-only UI framework committed.
- Commit: `7e69da2 Add read-only Synth chart debug UI`

Actions:

- Confirm BTC 1h chart renders.
- Confirm EMA20/EMA50 overlays render.
- Confirm RSI and signal confidence panels render.
- Confirm selection overlays do not crash Plotly.
- Confirm Streamlit UI remains read-only.
- Keep v1 as debug UI, not final trading interface.

Rules:

- UI may not write to decision, execution, order, account, balance, or position tables.
- UI queries must remain bounded by `asset_id`, `venue`, `interval_code`, timestamp range, and limit.
- UI is an inspection layer only.

---

### 7. Document UI/chart framework

Create or update:

- `docs/architecture/ui_chart_framework_v1.md`

Required content:

- purpose
- read-only boundary
- module responsibilities
- time alignment
- performance rules
- current features
- future extensions

Later UI v2 direction:

- TradingView-style Lightweight Charts frontend
- Python/FastAPI read-only backend
- better zoom/pan/crosshair/markers
- multi-pane charting
- paper/backtest/oracle marker overlays

---

### 8. DB collation cleanup

Current issue:

- DB has mixed text collations.
- Illegal mix of collations happened on joins involving `venue` / `interval_code`.

Do not fix during active writers or backfills.

Current workaround:

- avoid cross-table string equality joins on `venue` / `interval_code`
- use fixed query parameters where practical

Later workflow:

1. audit table/column collations
2. backup/restore plan
3. non-production test if possible
4. migrate consistently to:
   - `utf8mb4`
   - `utf8mb4_unicode_ci`
5. smoke-test joins/indexes

---

## Deferred / Later

### Oracle research lane

Status:

- planned
- research-only
- not live

Purpose:

- hindsight optimal long-only trades
- label candles around optimal entries/exits
- align labels with existing features
- derive interpretable feature combinations

Rule:

- oracle = microscope, not steering wheel
- future-aware labels may never leak into live selection, decision, execution, or executor

Initial interesting assets:

- BTC
- ETH
- SOL
- LINK
- HBAR
- HOT

---

## Operational Reminder

Before restarting scheduled chain crons:

1. confirm no manual replay/advice/paper/oracle jobs are running
2. confirm local docs/code diffs are handled
3. decide whether research rebuild should run first
4. restore only the intended crons

Current chain cron status should remain paused until explicitly restored.
