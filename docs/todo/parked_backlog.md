# TODO — Parked Backlog

## Status

Parked / backlog.

This file tracks lanes that should not distract from the active Synth-native Market Breath direction.

---

## Done / Parked — A+ archive and raw file handling

Sources:

```text
data/aplus_raw/
data/research/aplus_table1_table2_normalized_v1/
data/research/aplus_table2_harmonic_overlay_v1/
db/migrations/20260516_aplus_report_archive_v1.sql
src/research/load_aplus_reports_to_db_v1.py
```

Status: done / parked.

Current direction:

```text
A+ symbolic reports are parked.
Existing A+ reports are DB-backed as archive/comparator data only.
Main active direction is fully Synth-native Market Breath analysis from market data.
```

Resolved decisions:

- A+ is archive/comparator data only, not active signal input.
- Raw A+ files do not need active cleanup work while they do not block Market Breath research.
- If raw source text is already stored in DB with sufficient auditability, raw files do not need to be committed.
- If raw source text is not fully stored in DB, keeping raw files under `data/aplus_raw/` is acceptable.
- Do not mix A+ files into Market Breath commits.

Standing hygiene note:

- Untracked A+ files may remain locally while parked.
- Do not stage broad `data/` paths from Market Breath branches.
- Revisit only if A+ archive auditability becomes unclear or if untracked files start blocking active work.

Boundary:

```text
A+ archive/comparator only.
No A+ input into Market Breath.
No A+ symbolic labels in native Market Breath validation.
```

---

## P4 — External PRO narrative normalization backlog

Source:

```text
external PRO / membership research notes
```

Status: backlog.

Tasks:

- Keep external PRO notes as narrative/research data only.
- Normalize only when there is a concrete validation question.
- Store as external research labels, not signals.
- Validate via market-only reports before any feature-candidate promotion.

Boundary:

```text
external note -> normalized research label -> validation report -> optional feature candidate after validation
```

Not:

```text
external note -> buy/sell/order logic
```

---

## Parked — Astro context interaction backlog

Sources:

```text
docs/research/astro_cycle_context_v1.md
src/research/run_astro_cycle_context_v1.py
```

Status: parked.

Current direction:

```text
astro_cycle = external lunar/solar context only
```

Parked items:

- `astro_regime_interaction_audit_v1`
- deeper lunar/solar correlation research

Reopen only after:

- discovered regime review is complete
- `symbol_breath_profile_v1` exists as a design or implementation baseline

Boundary:

```text
No astro use in market decision logic.
No selection, decision, execution, broker, account, or dashboard use.
Research joins only.
```
