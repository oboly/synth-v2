# Fib Exit Ladder V1 — Phase A validation findings (Issue #270 Phase A)

## Disposition

```text
BLOCKED
```

This is not `INSUFFICIENT_DATA`. `INSUFFICIENT_DATA` means the deterministic
anchor detector ran against real historical data and legitimately could not
find a qualifying structure. `BLOCKED` means Phase A could not execute the
existing, unchanged runners (`run_fib_exit_ladder_backtest_v1.py`,
`run_fib_exit_ladder_scoreboard_v1.py`) against real historical data at all
in this environment. No backtest query was run beyond a connectivity probe.
No outcome numbers exist to report, revise, or reject.

Per the acceptance-criteria ordering fixed in
`docs/research/fib_exit_ladder_v1_phase_a_validation_contract_v1.md`, the
contract is frozen and unaffected by this outcome, so no re-run under this
same contract is invalidated — it can be executed as soon as the blocker
below is resolved.

## What was audited

- `docs/research/fib_exit_ladder_v1_findings.md` — original 2021-window
  findings and the three candidate exit-profile buckets.
- `docs/todo/fibo_zones.md` — confirms the same buckets, confirms
  `asset_exit_profile_hint` is metadata-only pending #270, and confirms this
  lane routes through Issue #270.
- `docs/architecture/automatic_exit_profile_promotion_v1.md` (merged, #657
  Phase A) — confirms #270 is the named blocking evidence-gate Issue for any
  `automatic_exit_profile_v1` producer, and that no promotion may occur
  absent a validated #270 conclusion.
- `src/research/run_fib_exit_ladder_backtest_v1.py` and
  `run_fib_exit_ladder_scoreboard_v1.py` — read in full; logic reconstructed
  into the frozen contract without modification. Both are read-only,
  account-agnostic, and already reject any non-SELECT SQL
  (`assert_read_only_sql`) and open only a `READ ONLY` transaction
  (`connect_read_only`).
- `git log` for both runner files: last logic-bearing commit `a36350b`
  ("Add fib exit ladder research runners"); only later commit is `93a3d73`
  (help-text formatting). No hidden revisions to the buckets since the
  findings doc was written.
- `tests/` — no existing test file covers either runner
  (`tests/test_fib_*` covers unrelated Fib map/navigation code). No prior
  automated reproduction of the original 2021 numbers exists to compare
  against.
- Issue #270 and its one comment (owner `oboly`, 2026-09-01): fixes the
  four-way (now five-way with `BLOCKED`) disposition requirement this
  document satisfies.

## Exact blocker

Phase A requires querying `obs_market_candle` for `LINK, SOL, XRP, HBAR, HOT,
SUI, XLM` on `venue=bitvavo, interval_code=1d` across the original window
(2020-01-01 -> 2022-01-01) and both new validation windows (2022-01-01 ->
2024-01-01, 2024-01-01 -> 2026-09-01). This worktree has:

```text
.env / SYNTH_DB_* / DB_* / MYSQL_* / MARIADB_* environment variables:  absent
Direct DB connection attempt (127.0.0.1:3306, default root/no-password):
  OperationalError 1045 Access denied for user 'root'@'127.0.0.1' (using password: NO)
```

No substitute dataset exists in-repo either. `data/research/` contains no
`obs_market_candle` export or equivalent OHLC dump for these seven symbols
covering 2020-2026; the only Fib-adjacent CSV present
(`data/research/fib_bull_run_sell_zones_overview_v1.csv`) is manually
extracted pro target-box data, not raw candles, and cannot stand in for the
anchor-detector input without changing the methodology (forbidden by the
frozen contract).

Per `AGENTS.md` host discipline, MariaDB is owned by a separate DB host; this
worktree is not that host and was not handed DB credentials or SSH access to
it as part of this task. Per `AGENTS.md` git/security rules, this document
does not attempt to guess or synthesize credentials, and does not fabricate
substitute candle history to work around the gap (explicitly forbidden by
this task's instructions and by the frozen contract's non-negotiable
constraints).

## What is needed to unblock

Exactly one of:

1. `SYNTH_DB_*` (or `DB_*`/`MYSQL_*`/`MARIADB_*`) read-only credentials for
   the MariaDB host that holds `obs_market_candle`, reachable from this
   worktree/host, supplied via `.env` or `--env-file` (never committed) —
   with confirmed coverage for `LINK, SOL, XRP, HBAR, HOT, SUI, XLM` on
   `bitvavo`/`1d` through at least 2026-09-01; or
2. An already-reviewed, point-in-time-safe offline candle export (research
   artifact under `data/research/`) covering the same symbols/venue/interval
   and window range, with documented provenance, that a future Phase A run
   can point the runners at without changing their query logic.

Once either exists, Phase A re-runs under the contract already frozen in
`docs/research/fib_exit_ladder_v1_phase_a_validation_contract_v1.md`
unchanged, and this findings document is superseded by a new version
reporting `VALIDATED` / `REVISED` / `REJECTED` / `INSUFFICIENT_DATA` per that
contract's § Acceptance thresholds.

## Downstream effect

`docs/architecture/automatic_exit_profile_promotion_v1.md` §1 names #270's
validated conclusion as the primary candidate canonical evidence source for
a future `automatic_exit_profile_v1` producer. This document does not
supply that conclusion. `#657` Phase B entry criterion 1 ("#270 ... records
a validated conclusion") remains unmet. No promotion, preview, or runtime
wiring may proceed on the basis of this document; `BLOCKED` here is itself
evidence that the criterion is unmet, not a workaround for it.

## Safety markers

```text
account_awareness=0
decision_permission=0
execution_intent=0
order_submission=0
broker_private_calls=0
broker_writes=0
db_writes=0
db_reads_executed=0
selection_engine_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
automatic_exit_profile_v1_writes=0
production_promotion=0
```
