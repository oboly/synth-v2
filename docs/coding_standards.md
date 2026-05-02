# SYNTH V2 CODING STANDARDS

## 1. Core Principle

The system is built as a layered pipeline:

    obs → feat → measurement/event → signal → ranking → selection → decision → execution

Each layer:

- reads from upstream tables
- writes only to its own table
- never mixes responsibilities
- never bypasses downstream permission layers

Research/backtest lanes are allowed, but must remain clearly separated from live inference and execution.

---

## 2. Canonical Keys

All state tables should use the canonical identity/time keys where applicable:

    asset_id
    venue
    interval_code
    asof_ts_utc / signal_ts_utc / close_ts_utc / open_ts_utc

Preferred unique key pattern for state snapshots:

    (asset_id, venue, interval_code, asof_ts_utc)

Rules:

- `asset_id` is identity.
- `venue` is execution/data context.
- `symbol` is display only.
- Do not join core logic on `symbol`.
- Backtest/research tables may use source-specific timestamps, but they must document their alignment contract.

---

## 3. Time Handling

- Always UTC.
- Store timestamps as naive UTC in MariaDB unless a table explicitly documents otherwise.
- Use `[start_ts, end_ts)` window convention.
- Never mix timezone-aware and naive timestamps in engine logic.

Candle alignment must be explicit:

- `open_ts_utc` for candle start.
- `close_ts_utc` for candle close.
- feature tables usually align to candle close.
- event tables usually align to candle open.
- signal/replay alignment must be documented per table/engine.

---

## 4. Engine Contract

Each engine must accept where relevant:

    --venue
    --interval

Each engine should optionally support:

    --asset-id
    --dry-run
    --output table|json

Historical support rule:

If an engine does not support historical processing directly, create a separate runner:

    run_<engine>_backfill.py

---

## 5. File Header Standard

Each runner should start with a concise module docstring:

    """
    ENGINE: <name>
    MODE: latest-only | historical | hybrid

    INPUT:
    - <table1>
    - <table2>

    OUTPUT:
    - <table>

    CLI:
    python -m <module> \
      --venue bitvavo \
      --interval 4h

    HISTORICAL:
    - supported / use backfill runner

    NOTES:
    - critical assumptions
    """

---

## 6. Database Rules

- DB is the source of truth.
- Avoid logic duplication outside DB + engines.
- All writes must be:
  - idempotent
  - UPSERT-based where practical
  - restart-safe

Permanent schema descriptions belong in:

- native table comments
- native column comments
- `docs/database/README.md`

Higher-level architecture belongs in:

- `docs/architecture/`

Research process documentation belongs in:

- `docs/research/`

---

## 7. Database Native Description Standard

For new permanent tables:

- Add a table `COMMENT`.
- Add column comments for non-obvious columns.
- Explain:
  - layer ownership
  - point-in-time semantics
  - whether data is live-safe or research-only
  - whether latest views are safe for backtest use

For schema migrations:

- Do not rely only on markdown docs.
- Important DB semantics must live in the schema itself.
- If a column participates in time alignment, comment the alignment meaning.

Example:

    asof_ts_utc DATETIME(6) NOT NULL
        COMMENT 'Point-in-time timestamp of the snapshot. Backtests must use rows with asof_ts_utc <= replay time.'

---

## 8. Encoding & Unicode Standard

The entire Synth system uses strict UTF-8.

Database default:

    CHARSET = utf8mb4
    COLLATE = utf8mb4_unicode_ci

Never use:

    utf8
    latin1
    mixed collations without explicit reason

Python file handling:

    open(path, "r", encoding="utf-8")
    open(path, "w", encoding="utf-8")
    Path(path).read_text(encoding="utf-8")
    Path(path).write_text(text, encoding="utf-8")

---

## 9. Large Schema Migration Workflow

This is not a universal rule. It is the preferred workflow when doing a broad schema cleanup, collation cleanup, or rebuild where in-place conversion is risky.

Preferred workflow for the current broad migration path:

    1. Stabilize schema first.
    2. Normalize charset/collation.
    3. Add table and column comments.
    4. Add indexes.
    5. Add views.
    6. Deploy empty/clean schema.
    7. Load/backfill data.
    8. Rebuild derived layers.

If in-place migration is technically safe:

    ALTER DATABASE
    ALTER TABLE
    ALTER COLUMN
    CONVERT TO CHARACTER SET

may be used.

If in-place migration is unsafe or unreliable:

    DDL export
    → normalize DDL
    → deploy clean schema
    → reload/backfill data

Do not run large backfills into a schema known to have unresolved collation or naming issues unless there is a deliberate temporary reason.

---

## 10. Backfill Rule

Backfills must:

- iterate over snapshots or bounded chunks
- be restart-safe
- avoid blind full recalculation when a bounded mode exists
- log progress clearly
- avoid unnecessary full-table scans
- avoid running heavy jobs in parallel on constrained DB/storage

Progress logs should include:

    snapshot index
    timestamp
    rows written
    interval
    venue

---

## 11. Naming Convention

Table prefixes:

    obs_*        raw observations
    feat_*       derived features
    measurement_* / structure_* objective measurements
    signal_*     interpretation
    ranking_*    ranking/rotation state
    selection_*  market-only candidate selection
    decision_*   account-aware permission state
    execution_*  execution planning/events
    research_*   research/backtest-only outputs
    bt_*         backtest/replay-only outputs

Column naming:

    *_score   decimal scoring
    *_signal  categorical interpretation
    *_state   interpreted state
    *_flag    boolean/int flag
    *_ts_utc  UTC timestamp

---

## 12. Return Naming

Canonical return naming depends on layer.

Trade/backtest result tables:

    trade_return

Forward-return analysis views:

    next_return_4h
    next_return_24h

Research/eval tables may use horizon-explicit names:

    gross_return_24h
    net_return_24h
    simulated_net_return

Avoid ad hoc drift:

    pnl_pct
    return_pct
    next_4h_return_proxy
    score

unless a table explicitly documents why it uses them.

---

## 13. No Shortcuts Rule

Forbidden:

- joining core logic on `symbol`
- mixing layers
- skipping upstream dependencies
- writing decision/execution data from research tools
- allowing future-aware labels into live inference
- using latest-only profile views inside historical replay

---

## 14. Research Boundary Rule

Research/backtest/oracle/paper tools may use future-aware returns or labels only when clearly namespaced.

Allowed namespaces:

    src/research/
    src/backtest/
    research_*
    bt_*
    docs/research/

Forbidden:

    future-aware labels in selection_engine live path
    future-aware labels in decision_gate
    future-aware labels in execution_planner
    future-aware labels in executor

---

## 15. Asset Profile Rule

Static asset identity lives in:

    asset

Derived market behavior lives in:

    asset_profile_snapshot
    vw_asset_profile_latest

Meaning:

    liquidity_class = derived tradability tier
    beta_profile = derived market sensitivity / volatility behavior
    sector_group_code = empirical co-movement group, not narrative label
    market = concrete tradable venue/quote instrument

Backtest/replay must use point-in-time profile snapshots:

    asset_profile_snapshot.asof_ts_utc <= replay_asof_ts_utc

Do not use `vw_asset_profile_latest` in historical replay.

---

## 16. Development Style

- Provide full-file replacements when changing files.
- Avoid patch fragments unless explicitly requested.
- Keep CLI copy-paste runnable.
- Prefer simple, non-nested heredocs when using shell file writers.
- Avoid `set -euo pipefail` in interactive copy-paste bundles unless explicitly needed.
- Keep SQL as plain SQL unless an executable shell block is explicitly requested.
- Avoid huge multi-file dumps that make the UI unstable.

---

## 17. Future Proofing

Design must support:

- multi-exchange / venue
- multi-timeframe
- multi-account
- multi-strategy
- sleeve-specific behavior
- research/live separation
- point-in-time backtests

---

## 18. Priority Rule

Always prioritize:

    1. Data correctness
    2. Pipeline completeness
    3. Architecture cleanliness
    4. Strategy tuning
    5. Runtime optimization

Never optimize strategy on incomplete or misaligned data.
