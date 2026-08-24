"""Issue #498: canonical CLI for automatic-BUY account configuration provisioning.

The single operator-facing entry point for both writers this issue adds:

    strategy-bucket-config   -> strategy_bucket_account_config_provisioning_v1
    account-permission       -> automatic_buy_account_permission_provisioning_v1

Both subcommands resolve the target account by canonical ``--account-code``/
``--venue`` identity only; neither accepts a raw numeric ``trading_account_id``
argument. Both are deterministic and idempotent: an identical rerun is a
no-op, a conflicting rerun fails closed (see the two provisioning modules'
docstrings for the exact resolution rules).

This CLI performs a repository-level DB write against whatever database
``src.common.db.get_db_connection`` is configured for. It does not decide
when/whether to run against production -- that authorization is a separate,
explicitly reviewed operational step (Issue #498's production mutation
boundary), not something this file enforces or assumes.

No broker, executor, credential, or order import. No market candidate truth
is created or modified.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
live_trading_enabled_mutation=0
executor_live_authority_grant=0
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from src.common.db import get_db_connection
from src.decision_gate.automatic_buy_account_permission_provisioning_v1 import (
    AutomaticBuyAccountPermissionProvisioningError,
    AutomaticBuyAccountPermissionProvisioningRequestV1,
    provision_automatic_buy_account_permission_v1,
)
from src.decision_gate.strategy_bucket_account_config_provisioning_v1 import (
    StrategyBucketAccountConfigProvisioningError,
    StrategyBucketAccountConfigProvisioningRequestV1,
    provision_strategy_bucket_account_config_v1,
)

RUNNER_NAME: Final[str] = "run_automatic_buy_account_config_provisioning_v1"

SAFETY_MARKERS: Final[str] = (
    "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
    "live_trading_enabled_mutation=0 executor_live_authority_grant=0"
)


class ProvisioningCliError(ValueError):
    pass


def _parse_ts(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ProvisioningCliError(f"INVALID_TIMESTAMP:{value}") from exc
    if parsed.tzinfo is None:
        raise ProvisioningCliError(f"NAIVE_TIMESTAMP:{value}")
    return parsed.astimezone(UTC)


def _parse_decimal_or_none(value: str | None, *, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ProvisioningCliError(f"INVALID_DECIMAL_FIELD:{field}") from exc


def _add_account_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account-code", required=True, help="Canonical trading_account.account_code.")
    parser.add_argument("--venue", required=True, help="Venue, e.g. bitvavo.")
    parser.add_argument("--effective-from-ts-utc", required=True, type=_parse_ts)
    parser.add_argument("--source-provenance", required=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Canonical provisioning path for account-owned automatic BUY configuration (Issue #498).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    bucket_parser = subparsers.add_parser(
        "strategy-bucket-config",
        help="Provision one strategy_bucket_account_config_v1 row.",
    )
    _add_account_args(bucket_parser)
    bucket_parser.add_argument("--strategy-bucket-id", required=True)
    bucket_parser.add_argument("--risk-profile", required=True)
    enabled_group = bucket_parser.add_mutually_exclusive_group(required=True)
    enabled_group.add_argument("--enabled", dest="is_enabled", action="store_true")
    enabled_group.add_argument("--disabled", dest="is_enabled", action="store_false")
    entries_group = bucket_parser.add_mutually_exclusive_group(required=True)
    entries_group.add_argument("--allow-new-entries", dest="allow_new_entries", action="store_true")
    entries_group.add_argument("--no-allow-new-entries", dest="allow_new_entries", action="store_false")
    reviews_group = bucket_parser.add_mutually_exclusive_group(required=True)
    reviews_group.add_argument("--allow-reduce-reviews", dest="allow_reduce_reviews", action="store_true")
    reviews_group.add_argument("--no-allow-reduce-reviews", dest="allow_reduce_reviews", action="store_false")
    bucket_parser.add_argument("--max-position-amount-eur", default=None)
    bucket_parser.add_argument("--max-bucket-amount-eur", default=None)
    bucket_parser.add_argument("--max-asset-exposure-pct", default=None)
    bucket_parser.add_argument("--max-open-positions", type=int, default=None)

    permission_parser = subparsers.add_parser(
        "account-permission",
        help="Provision one automatic_buy_account_permission_v1 row.",
    )
    _add_account_args(permission_parser)
    permission_enabled_group = permission_parser.add_mutually_exclusive_group(required=True)
    permission_enabled_group.add_argument("--enabled", dest="execution_enabled", action="store_true")
    permission_enabled_group.add_argument("--disabled", dest="execution_enabled", action="store_false")

    return parser.parse_args(argv)


def _run_strategy_bucket_config(conn: Any, args: argparse.Namespace) -> int:
    request = StrategyBucketAccountConfigProvisioningRequestV1(
        account_code=args.account_code,
        venue=args.venue,
        strategy_bucket_id=args.strategy_bucket_id,
        is_enabled=args.is_enabled,
        risk_profile=args.risk_profile,
        max_position_amount_eur=_parse_decimal_or_none(args.max_position_amount_eur, field="max_position_amount_eur"),
        max_bucket_amount_eur=_parse_decimal_or_none(args.max_bucket_amount_eur, field="max_bucket_amount_eur"),
        max_asset_exposure_pct=_parse_decimal_or_none(args.max_asset_exposure_pct, field="max_asset_exposure_pct"),
        max_open_positions=args.max_open_positions,
        allow_new_entries=args.allow_new_entries,
        allow_reduce_reviews=args.allow_reduce_reviews,
        effective_from_ts_utc=args.effective_from_ts_utc,
        source_provenance=args.source_provenance,
    )
    try:
        result = provision_strategy_bucket_account_config_v1(conn, request=request)
    except StrategyBucketAccountConfigProvisioningError as exc:
        conn.rollback()
        print(f"FAILED runner={RUNNER_NAME} command=strategy-bucket-config detail={exc}", file=sys.stderr)
        return 1
    conn.commit()
    print(
        f"TRADING_ACCOUNT_ID={result.trading_account_id}\n"
        f"STRATEGY_BUCKET_ACCOUNT_CONFIG_ID={result.strategy_bucket_account_config_id}\n"
        f"STRATEGY_BUCKET_ID={result.strategy_bucket_id}\n"
        f"IDEMPOTENT={result.idempotent}"
    )
    print(SAFETY_MARKERS)
    print(f"FINISHED runner={RUNNER_NAME} command=strategy-bucket-config result=ok")
    return 0


def _run_account_permission(conn: Any, args: argparse.Namespace) -> int:
    request = AutomaticBuyAccountPermissionProvisioningRequestV1(
        account_code=args.account_code,
        venue=args.venue,
        execution_enabled=args.execution_enabled,
        effective_from_ts_utc=args.effective_from_ts_utc,
        source_provenance=args.source_provenance,
    )
    try:
        result = provision_automatic_buy_account_permission_v1(conn, request=request)
    except AutomaticBuyAccountPermissionProvisioningError as exc:
        conn.rollback()
        print(f"FAILED runner={RUNNER_NAME} command=account-permission detail={exc}", file=sys.stderr)
        return 1
    conn.commit()
    print(
        f"TRADING_ACCOUNT_ID={result.trading_account_id}\n"
        f"AUTOMATIC_BUY_ACCOUNT_PERMISSION_ID={result.automatic_buy_account_permission_id}\n"
        f"IDEMPOTENT={result.idempotent}"
    )
    print(SAFETY_MARKERS)
    print(f"FINISHED runner={RUNNER_NAME} command=account-permission result=ok")
    return 0


def run(args: argparse.Namespace) -> int:
    print(f"STARTED runner={RUNNER_NAME} command={args.command} worker_count=1", flush=True)
    print(SAFETY_MARKERS, flush=True)

    try:
        conn = get_db_connection()
    except Exception as exc:  # pragma: no cover - environment-dependent
        print(f"FAILED runner={RUNNER_NAME} result=db_unavailable detail={exc}", file=sys.stderr)
        return 1

    try:
        if args.command == "strategy-bucket-config":
            return _run_strategy_bucket_config(conn, args)
        return _run_account_permission(conn, args)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except ProvisioningCliError as exc:
        print(f"FAILED runner={RUNNER_NAME} result=invalid_input detail={exc}", file=sys.stderr)
        return 1
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
