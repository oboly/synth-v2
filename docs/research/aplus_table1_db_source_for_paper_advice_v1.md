# A+ Table 1 DB Source for Paper Advice V1

## Status

Production-runtime source cleanup.

## Purpose

Paper advice should consume normalized A+ Table 1 rows from DB by default.

Raw A+ source files remain archive/audit material only.

## Runtime behavior

Default source:

```text
db://latest
```

This resolves to the latest valid `aplus_table1_report` plus valid rows from `aplus_table1_row`.

Legacy raw fallback remains available by passing an explicit raw file path or glob to `--aplus-raw`.

## Boundary

```text
paper advice enrichment only
no selection_engine changes
no setup_filter changes
no decision_gate changes
no execution_planner changes
no executor changes
no broker calls
no broker writes
no order submission
```

## Explicitly out of scope

- A+ Table 2 / breath rhythm module.
- Live trading decisions.
- Order generation.

