# Synth v2.14 Signal Dashboard Strategy Bridge Backlog — Historical Record

Status: historical only, no active ownership.

This document preserves version-specific historical context from the removed
`docs/todo/synth_v214_signal_dashboard_strategy_bridge_backlog.md`. It is not
an operational board and must not be used to track current work.

Canonical architecture now lives in:

- `docs/architecture/strategy_proposal_contract_v1.md` (strategy proposal
  contract, schema, action/horizon/setup enums, profile/bucket ownership,
  lifecycle, freshness, LLM/manual bridge boundary, anti-patterns).

GitHub Issues own current operational work. See
`docs/development/docs_todo_canonicalization_batch_3b3_v1.md` for the full
disposition of every source section, including which existing documents and
Issues already own the still-active parts of this backlog
(`docs/todo/signal_matrix_dashboard.md`, `docs/todo/manual_ladder_dashboard.md`,
`docs/ops/runtime_chain_ownership_v1.md`, and others).

## Why this file existed

Written during the Synth v2.14 dashboard rework, this backlog captured a set
of complaints about the (then-current) old signal/paper-advice dashboard and
proposed a strategy-proposal bridge concept to replace ad hoc dashboard
interpretation. Most of its durable architecture has since been canonicalized
elsewhere; the parts below are retained only as dated context for why the
rework happened and in what order it was originally sequenced.

## v2.14-specific dashboard complaints (historical)

The old dashboard, as of v2.14, was assessed as:

- too table-like, too wide, and requiring too much scrolling;
- hard to keep symbol, current price, and headers visible;
- using labels that were too technical and not immediately meaningful;
- mixing signals, context, strategy advice, and refresh behavior in one
  surface;
- becoming partly blackbox-like;
- coupling dashboard refresh to canonical data/signal freshness, which was
  identified at the time as an architecture violation.

These complaints motivated the signal-matrix and manual-ladder dashboard
lanes (`docs/todo/signal_matrix_dashboard.md`,
`docs/todo/manual_ladder_dashboard.md`), which remain the active, current
dashboard direction and are not superseded by this archive.

## Originally proposed implementation order (historical, not current)

The backlog proposed the following sequencing. It is preserved for context
only; current priority and status live in GitHub Issues, not here:

1. Runtime freshness audit and ownership docs.
2. Signal inventory.
3. Horizon-separated signal matrix.
4. Asset-card dashboard.
5. Strategy proposal contract.
6. Manual Excel or dropfolder path.
7. LLM strategy bridge.
8. Outcome logging.
9. Promotion rules for measured strategy logic.
10. Only later: decision or execution integration, if explicitly approved.

Step 1 is superseded by `docs/ops/runtime_chain_ownership_v1.md`. Steps 2-4
are owned by the still-active `docs/todo/signal_matrix_dashboard.md` and
`docs/todo/manual_ladder_dashboard.md`. Step 5 is fulfilled by
`docs/architecture/strategy_proposal_contract_v1.md`. Steps 6-8 remain
genuinely unowned implementation work; see
`docs/development/docs_todo_canonicalization_batch_3b3_v1.md` (Section 10,
"Future Issue candidates") for their disposition. Step 9 is already governed
by the "Strategy Candidate Rules" in `AGENTS.md`. Step 10 remains
non-authorized per `AGENTS.md` live-trading safety rules.

## Historical candidate strategy list

The backlog listed the following illustrative `strategy_id` examples under
the `{ACTION}_{HORIZON}_{SETUP}` format defined in
`docs/architecture/strategy_proposal_contract_v1.md`. These were examples,
not an approved or exhaustive strategy list, and remain unvalidated:

- `SELL_SHORT_SPIKE`
- `BUY_SHORT_PULLBACK`
- `BUY_SHORT_RECLAIM`
- `HOLD_MID_REL_STRENGTH`
- `SELL_MID_EXHAUSTION`
- `ROTATE_LONG_LEGACY_EXIT`
- `BUY_LONG_BASE`
- `WARN_SHORT_NO_CHASE`

Any promotion of these (or any other) strategy candidates requires the
evidence described in the "Strategy Candidate Rules" section of `AGENTS.md`
(baseline comparison, replay validation, sample size, winrate, profit
factor, drawdown, regime stability, and explicit review) before any
paper/live use.

## Historical example ladder rows

Two worked dashboard-row examples from the original backlog (ALGO-style and
WLD-style manual ladders) illustrated the desired asset-card display. Those
examples were about UI presentation, not architecture, and are already
superseded by the worked examples retained in
`docs/todo/manual_ladder_dashboard.md`, which is still the active dashboard
TODO. They are not duplicated here.
