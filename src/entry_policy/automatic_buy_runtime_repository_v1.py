"""DB-local input/evidence loader for the automatic BUY runtime.

The repository assembles persisted runtime input, canonical #279 strategy
bucket history, #318 account protection, Phase 7A BUY LIVE permission evidence
when the snapshot is LIVE-mode, and public venue constraints. It makes no BUY
permission or planning decision and has no executor/broker imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from src.decision_gate.account_protection_contract_v1 import ACTION_BUY, AccountProtectionEvaluationV1
from src.decision_gate.account_protection_evaluation_v1 import evaluate_account_protection_for_automatic_exit_v1
from src.decision_gate.automatic_buy_live_permission_evaluation_v1 import (
    AutomaticBuyLivePermissionEvaluationV1,
    evaluate_automatic_buy_live_permission_v1,
)
from src.decision_gate.strategy_bucket_account_config_contract_v1 import (
    StrategyBucketAccountConfigRevocationV1,
    StrategyBucketAccountConfigRowV1,
)
from src.decision_gate.strategy_bucket_account_config_repository_v1 import (
    StrategyBucketAccountConfigRepositoryError,
    load_strategy_bucket_account_config_revocations_v1,
    load_strategy_bucket_account_config_rows_v1,
)
from src.entry_policy.automatic_buy_runtime_contract_v1 import (
    AutomaticBuyRuntimeInputV1,
    validate_runtime_input_v1,
)
from src.market_rules.venue_execution_constraints_v1 import (
    STATUS_FRESH,
    VenueExecutionConstraints,
    load_constraints_from_db,
    resolve_venue_execution_constraints,
)


class AutomaticBuyRuntimeRepositoryError(RuntimeError):
    pass


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _row_to_input(row: dict[str, Any]) -> AutomaticBuyRuntimeInputV1:
    try:
        return AutomaticBuyRuntimeInputV1(
            automatic_buy_runtime_input_id=int(row["automatic_buy_runtime_input_id"]),
            source_snapshot_key=str(row["source_snapshot_key"]),
            input_contract_version=str(row["input_contract_version"]),
            evaluation_ts_utc=_aware(row["evaluation_ts_utc"]),
            trading_account_id=int(row["trading_account_id"]),
            venue=str(row["venue"]),
            asset_id=int(row["asset_id"]),
            market=str(row["market"]),
            strategy_bucket_id=str(row["strategy_bucket_id"]),
            strategy_id=str(row["strategy_id"]),
            strategy_version=str(row["strategy_version"]),
            setup_id=str(row["setup_id"]),
            setup_ready=bool(row["setup_ready"]),
            current_price=Decimal(str(row["current_price"])),
            entry_zone_low=Decimal(str(row["entry_zone_low"])) if row["entry_zone_low"] is not None else None,
            entry_zone_high=Decimal(str(row["entry_zone_high"])) if row["entry_zone_high"] is not None else None,
            re_entry_zone_low=Decimal(str(row["re_entry_zone_low"])) if row["re_entry_zone_low"] is not None else None,
            re_entry_zone_high=Decimal(str(row["re_entry_zone_high"])) if row["re_entry_zone_high"] is not None else None,
            setup_evidence_id=str(row["setup_evidence_id"]),
            setup_observed_ts_utc=_aware(row["setup_observed_ts_utc"]),
            account_observed_ts_utc=_aware(row["account_observed_ts_utc"]),
            account_enabled=bool(row["account_enabled"]),
            account_mode=str(row["account_mode"]),
            automatic_buy_execution_enabled=bool(row["automatic_buy_execution_enabled"]),
            free_quote_balance_eur=Decimal(str(row["free_quote_balance_eur"])),
            free_quote_balance_observed_ts_utc=_aware(row["free_quote_balance_observed_ts_utc"]),
            blocking_conflict=bool(row["blocking_conflict"]),
            proposed_position_amount_eur=Decimal(str(row["proposed_position_amount_eur"])),
            current_bucket_amount_eur=Decimal(str(row["current_bucket_amount_eur"])),
            current_open_positions=int(row["current_open_positions"]),
            current_asset_exposure_pct=Decimal(str(row["current_asset_exposure_pct"])),
            max_automatic_buy_notional_eur=(
                Decimal(str(row["max_automatic_buy_notional_eur"]))
                if row["max_automatic_buy_notional_eur"] is not None else None
            ),
            source_provenance=str(row["source_provenance"]),
            live_trading_enabled=bool(row.get("live_trading_enabled", 0)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AutomaticBuyRuntimeRepositoryError("INVALID_AUTOMATIC_BUY_RUNTIME_INPUT_ROW") from exc


@dataclass(frozen=True)
class RuntimeItemV1:
    runtime_input: AutomaticBuyRuntimeInputV1
    strategy_bucket_config_rows: tuple[StrategyBucketAccountConfigRowV1, ...]
    strategy_bucket_config_revocations: tuple[StrategyBucketAccountConfigRevocationV1, ...]
    account_protection_evaluation: AccountProtectionEvaluationV1
    venue_constraints: VenueExecutionConstraints
    automatic_buy_live_permission_evaluation: AutomaticBuyLivePermissionEvaluationV1 | None = None


def load_ready_runtime_inputs_v1(conn: Any, *, venue: str) -> tuple[AutomaticBuyRuntimeInputV1, ...]:
    sql = """
    SELECT automatic_buy_runtime_input_id, source_snapshot_key, input_contract_version,
           evaluation_ts_utc, trading_account_id, venue, asset_id, market, strategy_bucket_id,
           strategy_id, strategy_version, setup_id, setup_ready, current_price,
           entry_zone_low, entry_zone_high, re_entry_zone_low, re_entry_zone_high,
           setup_evidence_id, setup_observed_ts_utc,
           account_observed_ts_utc, account_enabled, account_mode,
           automatic_buy_execution_enabled, live_trading_enabled, free_quote_balance_eur,
           free_quote_balance_observed_ts_utc, blocking_conflict,
           proposed_position_amount_eur, current_bucket_amount_eur,
           current_open_positions, current_asset_exposure_pct,
           max_automatic_buy_notional_eur, source_provenance
    FROM automatic_buy_runtime_input_v1
    WHERE input_state = 'READY' AND venue = %s
    ORDER BY automatic_buy_runtime_input_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue,))
        rows = [dict(row) for row in cur.fetchall()]
    return tuple(_row_to_input(row) for row in rows)


def build_runtime_item_v1(conn: Any, *, runtime_input: AutomaticBuyRuntimeInputV1) -> RuntimeItemV1:
    """Assemble canonical persisted evidence for one immutable runtime input."""
    try:
        validate_runtime_input_v1(runtime_input)
    except ValueError as exc:
        raise AutomaticBuyRuntimeRepositoryError(exc.args[0] if exc.args else "INVALID_RUNTIME_INPUT") from exc

    try:
        config_rows = load_strategy_bucket_account_config_rows_v1(
            conn, trading_account_id=runtime_input.trading_account_id,
        )
        config_revocations = load_strategy_bucket_account_config_revocations_v1(
            conn, trading_account_id=runtime_input.trading_account_id,
        )
    except StrategyBucketAccountConfigRepositoryError as exc:
        raise AutomaticBuyRuntimeRepositoryError("STRATEGY_BUCKET_CONFIGURATION_EVIDENCE_INVALID") from exc

    protection = evaluate_account_protection_for_automatic_exit_v1(
        conn,
        trading_account_id=runtime_input.trading_account_id,
        asset_id=runtime_input.asset_id,
        requested_action=ACTION_BUY,
        account_state_observed_ts_utc=runtime_input.account_observed_ts_utc,
        evaluation_ts_utc=runtime_input.evaluation_ts_utc,
    )

    live_permission = None
    if runtime_input.account_mode == "live":
        live_permission = evaluate_automatic_buy_live_permission_v1(
            conn,
            trading_account_id=runtime_input.trading_account_id,
            evaluation_ts_utc=runtime_input.evaluation_ts_utc,
        )

    db_constraints = load_constraints_from_db(
        conn, venue=runtime_input.venue, markets=[runtime_input.market],
    )
    constraints = resolve_venue_execution_constraints(
        venue=runtime_input.venue,
        market=runtime_input.market,
        db_rows=db_constraints,
        now=runtime_input.evaluation_ts_utc,
    )
    if constraints.status != STATUS_FRESH:
        raise AutomaticBuyRuntimeRepositoryError("VENUE_CONSTRAINTS_NOT_FRESH")
    return RuntimeItemV1(
        runtime_input=runtime_input,
        strategy_bucket_config_rows=config_rows,
        strategy_bucket_config_revocations=config_revocations,
        account_protection_evaluation=protection,
        venue_constraints=constraints,
        automatic_buy_live_permission_evaluation=live_permission,
    )
