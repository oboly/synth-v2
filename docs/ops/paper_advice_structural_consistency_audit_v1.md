# Paper Advice Structural Consistency Audit V1

## Purpose
Paper Advice Structural Consistency Audit V1 compares the latest 4h `execution_zone_context` structural map against the latest 4h `paper_advice_observation` structural fields for each asset.

It diagnoses cases where market data and zone context are ready, but dashboards still show missing labels such as:
- `LEG_DIRECTION_MISSING`
- `NEXT_ZONE_UNKNOWN`
- `PRICE_PROGRESS_UNKNOWN`
- `TARGET_UNKNOWN`
- `RISK_UNKNOWN`

## Boundary
- Reporting/audit only.
- Read-only.
- Market-only structural comparison.
- No broker calls.
- No broker writes.
- No order submission.
- No live orders.
- No `decision_gate` changes.
- No `execution_planner` changes.
- No `executor` changes.
- No `selection_engine` behavior changes.

## Inputs
Reads:
- `asset`
- `execution_zone_context` latest 4h structural map
- `paper_advice_observation` latest 4h paper advice row
- `market_price_snapshot`
- `obs_market_candle` 15m

Reuses:
- `structural_zone_context_coverage_audit_v1` for structural coverage and market-data freshness
- `paper_advice_severity_calibration_v1` for display severity/substate when a paper advice row exists

Does not read:
- `account_position_snapshot`
- `trading_account_balance_snapshot`
- `broker_order_snapshot`
- broker/private APIs

## Output
Per asset:
- `symbol`
- `asset_id`
- `venue`
- `interval_code`
- `zone_asof_ts_utc`
- `paper_advice_asof_ts_utc`
- `zone_has_leg_direction`
- `zone_leg_direction`
- `advice_leg_direction`
- `zone_has_entry_zone`
- `advice_has_entry_zone`
- `zone_has_target_zone`
- `advice_has_target_zone`
- `zone_has_invalidation_price`
- `advice_has_invalidation_price`
- `price_snapshot_freshness`
- `ltf_candle_freshness`
- `structural_coverage_state`
- `paper_advice_state`
- `advice_action`
- `advice_severity`
- `advice_substate`
- `consistency_state`
- `mismatch_fields`
- `recommended_action`

## Consistency States
`CONSISTENT`
: Latest zone and paper advice structural fields are present and aligned.

`PAPER_ADVICE_STALE_VS_ZONE`
: Latest zone context is newer than latest paper advice for the asset.

`PAPER_ADVICE_MISSING_STRUCTURAL_FIELDS`
: Zone context is usable, but paper advice is missing leg, entry, target, or invalidation fields.

`DASHBOARD_MAPPING_SUSPECT`
: Reserved for a future dashboard-render audit where both zone and advice are ready but rendered labels still show missing.

`ZONE_READY_ADVICE_MISSING`
: Latest structural zone is ready, but no paper advice row exists for the asset.

`ZONE_MISSING_ADVICE_MISSING`
: Structural map is missing; this is not primarily a paper-advice bug.

`ASSET_INTERVAL_MISMATCH`
: Zone and advice rows exist but disagree on structural direction or join identity.

`INSUFFICIENT_DATA`
: Required market-data or structural inputs are not available.

## Recommended Actions
`NO_ACTION`
: No structural consistency issue detected.

`REFRESH_PAPER_ADVICE_FOR_ASSET`
: Rebuild paper advice for the asset using the latest available structural zone context.

`REFRESH_ZONE_AND_ADVICE_FOR_ASSET`
: Recompute structural zone context and then refresh paper advice for the asset.

`FIX_DASHBOARD_FALLBACK_MAPPING`
: Reserved for a future renderer-level issue when persisted data is ready but display mapping is wrong.

`CHECK_ASSET_INTERVAL_JOIN`
: Inspect asset/interval join assumptions.

`SKIP_INSUFFICIENT_DATA`
: Do not take a structural action until market data is available.

## CLI
```bash
python -m src.reporting.paper_advice_structural_consistency_audit_v1 \
  --venue bitvavo \
  --quote EUR \
  --interval 4h \
  --symbols HYPE NEAR ALGO RENDER INJ QNT TAO APT SXT \
  --output table
```

JSON:

```bash
python -m src.reporting.paper_advice_structural_consistency_audit_v1 \
  --symbols HYPE NEAR ALGO RENDER INJ QNT TAO APT SXT \
  --output json
```

## Interpretation
If `execution_zone_context` is `STRUCTURAL_MAP_READY` but paper advice is missing leg/entry/target/invalidation fields, this audit reports:

```text
PAPER_ADVICE_MISSING_STRUCTURAL_FIELDS
recommended_action=REFRESH_PAPER_ADVICE_FOR_ASSET
```

If `execution_zone_context.asof_ts_utc` is newer than `paper_advice_observation.asof_ts_utc`, this audit reports:

```text
PAPER_ADVICE_STALE_VS_ZONE
recommended_action=REFRESH_PAPER_ADVICE_FOR_ASSET
```

If structural zone context is missing, the audit reports zone coverage issues rather than a paper-advice bug.

## Verification
```bash
python -m py_compile src/reporting/paper_advice_structural_consistency_audit_v1.py

python -m src.reporting.paper_advice_structural_consistency_audit_v1 \
  --symbols HYPE NEAR ALGO RENDER INJ QNT TAO APT SXT \
  --output table

git diff --check
```

Safety markers:
- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `live_orders=0`
- `decision_gate_changes=0`
- `execution_planner_changes=0`
- `executor=none`
