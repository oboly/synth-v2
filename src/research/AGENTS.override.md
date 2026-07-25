# Research Runner Overrides

Scoped overrides for `src/research/`. These are **additional** constraints.
The canonical contract in root `AGENTS.md`, plus
`docs/ops/agent_orchestration_contract_v1.md` and
`docs/ops/agent_search_hygiene_v1.md`, still applies in full.

## Query and Process Efficiency

Before implementing or running a broad research job:

- estimate expected symbols, intervals, rows, memory use, and runtime
- inspect whether the query can filter earlier or fetch less data
- inspect `EXPLAIN` and existing indexes for expensive DB queries
- never use one unbounded `fetchall` for broad historical datasets
- stream or fetch in bounded batches
- incremental mode must query only new data plus required overlap
- do not fetch full history and trim it afterward
- benchmark worker counts instead of assuming more workers are faster
- avoid copying large candle datasets between workers unnecessarily

## Smoke Discipline

Run in this order:

1. one symbol, one horizon, one worker
2. incremental rerun on the same output
3. several symbols across all horizons
4. interrupt and resume test
5. worker-count benchmark
6. broad production/research run only after all earlier checks pass

Do not launch the next smoke step after a failed or interrupted step.
Use fail-closed shell commands such as `set -euo pipefail`.
