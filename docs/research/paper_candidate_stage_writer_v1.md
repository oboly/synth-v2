# Paper Candidate Stage Writer V1

## Layer

Research / paper-candidate staging.

This is the kennel between research preview exports and any future adapter.

## Purpose

`run_paper_candidate_stage_writer_v1.py` stages validated paper-candidate contract rows into:

- database: `synth_bt`
- default table: `research_paper_candidate_signal`

It reads transport-safe JSONL from the paper candidate contract export and writes only validated market-only candidate rows.

## Boundary

Allowed:

- read paper candidate contract JSONL
- validate contract rows
- create the research staging table
- write validated paper-candidate staging rows
- assign a research lifecycle status

Forbidden:

- balances
- live positions
- open orders
- execution plans
- broker/order actions
- decision_gate writes
- execution_intent writes
- execution_plan writes
- order creation

## Candidate identity

Rows use a deterministic `candidate_key` based on:

- contract_version
- policy_name
- policy_version
- venue
- source_table
- source_replay_id

This allows safe re-runs using `ON DUPLICATE KEY UPDATE`.

## Architectural note

This table is not a strategy execution table.

It is not decision output.

It is not execution intent.

It is not an execution plan.

A future adapter may read validated candidate rows and translate them into a decision-gate-readable input shape, but that adapter must not bypass `decision_gate`.
