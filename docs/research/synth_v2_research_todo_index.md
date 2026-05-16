# Synth v2 Research TODO Index

## Status

Central research TODO index.

Purpose: keep cross-lane TODOs in one place without scattering loose notes across chats or documents.

This document is an index only. Source docs remain canonical for detailed design.

## Global boundaries

Unless a task explicitly says otherwise, all open items are:

- research-only
- market-only where applicable
- account-agnostic until decision_gate
- no live trading
- no broker calls
- no broker writes
- no order submission
- no executor changes
- no `run_chain_4h.sh` changes
- no selection/advice/decision/execution changes unless the task explicitly belongs to that layer

Architecture rules remain:

```text
selection_engine = market-only candidate ranking
 decision_gate = account-aware permission / conflict resolution
execution_planner = execution intent only
executor / agents = order handling only
```

Do not bypass layers.

---

## P0 — Market Breath V1.1 calibration interpretation cleanup

Source:

```text
docs/research/market_breath_v1_1_calibration_audit.md
```

Status: open.

Current facts:

```text
sample_count=60
assets_per_sample=41
observations=2460

NEUTRAL_TRANSITION=88.333333%
EXHALE_EXPANSION=6.056911%
COLLAPSE_RESET=3.699187%
OVERBREATH_EXTENSION=1.178862%
INHALE_ACCUMULATION=0.650407%
HOLD_COMPRESSION=0.081301%
INSUFFICIENT_DATA=0.0%
```

Tasks:

- Keep Market Breath V1 thresholds unchanged.
- Improve V1.1 audit interpretation language.
- Distinguish intended selectivity from functional unreachability.
- Add explicit diagnostic language for `NEUTRAL_TRANSITION` structural dominance.
- Add explicit diagnostic language for sparse-but-reachable phases.
- Replace overly broad `thresholds appear plausible` when neutral dominance is high.

Boundary:

```text
No threshold changes in this cleanup.
No outcome validation in this cleanup.
No strategy logic.
No runtime promotion.
```

---

## P1 — Decide whether NEUTRAL_TRANSITION should remain the large rest bucket

Source:

```text
docs/research/market_breath_v1_1_calibration_audit.md
```

Status: open; depends on P0.

Questions:

- Is `NEUTRAL_TRANSITION` intended to absorb most non-clean states?
- Does an 88% neutral rate make later outcome validation too sparse for several phases?
- Should outcome validation first focus on phases with enough sample mass, such as `EXHALE_EXPANSION` and `COLLAPSE_RESET`?
- Should `HOLD_COMPRESSION` be reviewed separately because it appears only 2 times in 2460 observations?

Boundary:

```text
Review only.
Do not change thresholds without a separate threshold-calibration patch.
```

---

## P2 — Optional Market Breath threshold-calibration patch

Source:

```text
docs/research/market_breath_v1_1_calibration_audit.md
```

Status: blocked by P0 and P1.

Trigger:

Only open this if the calibration review confirms that V1 has a measurement problem rather than merely intentionally conservative labels.

Rules:

- Separate patch from audit-output work.
- Research-only.
- Market-only.
- No strategy logic.
- Rerun the same V1.1 distribution audit after any threshold change.

---

## P3 — Market Breath outcome validation

Source:

```text
docs/research/market_breath_v1_1_calibration_audit.md
```

Status: blocked by P0/P1 and optionally P2.

Goal:

Validate whether Market Breath labels have useful future market behavior.

Rules:

- No outcome validation inside V1.1 calibration audit.
- No strategy candidate before outcome validation exists.
- No selection/advice/decision/execution/broker integration.

---

## P2 — Breath Curve baseline and regime validation continuation

Sources:

```text
docs/research/breath_curve_template_partial_v1.md
docs/research/breath_curve_regime_gated_policy_preview_v1.md
```

Status: open / research continuation.

Known path:

```text
partial-cycle matcher
-> policy baseline comparisons
-> regime-gated preview validation
-> strategy scoring board per regime
-> optional paper-candidate contract
-> decision_gate only after validated promotion
```

Tasks:

- Keep Breath Curve research parked from runtime selection until validation is stronger.
- Continue baseline comparisons where useful:
  - same-window buy-and-hold baseline
  - random anchor baseline
  - checkpoint 0.618 vs 0.786 comparison
  - offset-match-only variant
  - symbol/regime buckets
  - optional later 4h partial-cycle test
- Keep regime-gated preview market-only and account-agnostic.
- Do not convert regime-gated results into selection modifiers without validation and explicit promotion review.

Boundary:

```text
No direct orders.
No decision_gate bypass.
No execution_planner/executor logic.
No live/paper trigger from this research lane.
```

---

## P2 — Strategy candidate horizon bucket design review

Source:

```text
docs/research/strategy_candidate_horizon_buckets_v1.md
```

Status: open design questions; no implementation yet.

Tasks:

- Decide whether selection_engine should rank per horizon bucket independently.
- Specify how same-asset candidates conflict or reinforce each other.
- Specify how decision_gate resolves exposure when multiple active candidates target the same asset.
- Define graduation rules from `BREATH_CURVE_RESEARCH` to runtime-eligible candidate buckets only after validation.
- Preserve the rule: asset is not a strategy.

Boundary:

```text
selection_engine may rank market-only candidates.
decision_gate resolves account-aware exposure/conflicts/sizing/permission.
execution_planner/executor do not contain candidate logic.
```

---

## P3 — Paper candidate contract adapter design

Source:

```text
docs/research/paper_candidate_contract_v1.md
```

Status: future adapter design allowed; no execution wiring.

Task:

- Design a future adapter that reads contract-valid research candidates and presents them to `decision_gate`.

Rules:

- No shortcut from research preview to execution.
- No account, portfolio, wallet, balance, position, order, execution plan, broker, or fill fields in research candidate transport.
- `decision_gate` may receive account-aware context later; research must not derive it.

Boundary:

```text
research preview -> paper_candidate_contract -> future decision_gate adapter
```

Not:

```text
research preview -> execution
```

---

## P3 — A+ archive / raw file housekeeping

Sources:

```text
data/aplus_raw/
data/research/aplus_table1_table2_normalized_v1/
data/research/aplus_table2_harmonic_overlay_v1/
db/migrations/20260516_aplus_report_archive_v1.sql
src/research/load_aplus_reports_to_db_v1.py
```

Status: low priority.

Current project direction:

```text
A+ symbolic reports are parked.
Existing A+ reports are DB-backed as archive/comparator data only.
Main active direction is fully Synth-native Market Breath analysis from market data.
```

Tasks:

- Do not spend major time here unless cleanup blocks active research.
- If raw source text is already stored in DB with enough auditability, raw files do not need to be kept in git.
- If raw source text is not fully stored in DB, keeping raw files under `data/aplus_raw/` is acceptable.
- Do not mix A+ files into Market Breath commits.

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

## Active next-step recommendation

Recommended order:

```text
1. Finish Market Breath V1.1 P0 audit interpretation cleanup.
2. Review P1 neutral rest-bucket question.
3. Decide whether P2 threshold-calibration patch is needed or skipped.
4. Only then open Market Breath outcome validation.
5. Keep Breath Curve / A+ / PRO lanes parked unless directly needed.
```

Reason:

Market Breath is now the active Synth-native direction. Do not split focus back into A+ or Breath Curve unless it directly supports validation discipline.

---

## Explicit non-goals

- No live trading.
- No broker writes.
- No order submission.
- No runtime promotion from research docs.
- No selection_engine shortcuts.
- No decision_gate bypass.
- No execution_planner shortcuts.
- No executor/order changes.
- No A+ symbolic input into Market Breath.
- No external PRO narrative converted directly into signals.
