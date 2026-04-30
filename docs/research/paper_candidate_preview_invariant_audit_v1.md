# Paper Candidate Preview Invariant Audit V1

## Purpose

`run_paper_candidate_preview_invariant_audit_v1.py` compares JSON output from the read-only paper candidate preview tools.

It checks that PnL, exposure, and ledger previews agree before any permanent paper ledger design is added.

## Boundary

Allowed:

```text
read JSON preview files
compare summary fields
fail on mismatches
print table or JSON audit output
```

Forbidden:

```text
no database writes
no decision_state writes
no execution_plan writes
no live orders
no account balance mutation
```

## Default input files

```text
/tmp/synth_paper_candidate_audit/pnl_preview.json
/tmp/synth_paper_candidate_audit/exposure_preview.json
/tmp/synth_paper_candidate_audit/ledger_preview.json
```

## Example

```bash
python -m src.research.run_paper_candidate_preview_invariant_audit_v1 --output table
```

## Rule

This remains a research-only consistency audit. It does not grant live execution permission.
