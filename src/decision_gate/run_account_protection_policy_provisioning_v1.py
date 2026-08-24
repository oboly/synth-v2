"""Operator CLI for explicit decision-gate account-protection provisioning.

The CLI accepts canonical account identity only.  It never prints or accepts
``trading_account_id``.  Every protection metric must be explicitly enabled
with a threshold or explicitly disabled; no omitted CLI value can create an
unintended permissive policy.
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from src.common.db import get_db_connection
from src.decision_gate.account_protection_policy_contract_v1 import POLICY_CONFIG_CONTRACT_VERSION
from src.decision_gate.account_protection_policy_provisioning_v1 import (
    AccountProtectionPolicyProvisioningError,
    AccountProtectionPolicyProvisioningRequestV1,
    provision_account_protection_policy_v1,
)

RUNNER_NAME: Final[str] = "run_account_protection_policy_provisioning_v1"
SAFETY_MARKERS: Final[str] = (
    "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
    "live_trading_enabled_mutation=0 executor_live_authority_grant=0"
)


def _parse_ts(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError(f"timestamp must include timezone: {value!r}")
    return parsed.astimezone(UTC)


def _decimal_arg(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"invalid decimal value: {value!r}") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise argparse.ArgumentTypeError(f"decimal must be finite and positive: {value!r}")
    return parsed


def _nonnegative_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer value: {value!r}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"integer must be non-negative: {value!r}")
    return parsed


def _positive_int_arg(value: str) -> int:
    parsed = _nonnegative_int_arg(value)
    if parsed == 0:
        raise argparse.ArgumentTypeError(f"integer must be positive: {value!r}")
    return parsed


def _add_metric_choice(parser: argparse.ArgumentParser, *, name: str, destination: str, value_type: Any) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(name, dest=destination, type=value_type)
    group.add_argument(f"--disable-{name.removeprefix('--')}", dest=destination, action="store_const", const=None)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Canonical account-protection policy provisioning (Issue #504).")
    parser.add_argument("--account-code", required=True)
    parser.add_argument("--venue", required=True)
    parser.add_argument("--config-version", required=True, choices=(POLICY_CONFIG_CONTRACT_VERSION,))
    parser.add_argument("--configuration-version", required=True)
    parser.add_argument("--max-metric-age-seconds", required=True, type=_nonnegative_int_arg)
    parser.add_argument("--effective-from-ts-utc", required=True, type=_parse_ts)
    parser.add_argument("--effective-until-ts-utc", type=_parse_ts)
    parser.add_argument("--source-provenance", required=True)
    _add_metric_choice(
        parser, name="--max-account-drawdown", destination="max_account_drawdown", value_type=_decimal_arg,
    )
    _add_metric_choice(
        parser, name="--max-daily-realized-loss", destination="max_daily_realized_loss", value_type=_decimal_arg,
    )
    _add_metric_choice(
        parser, name="--max-repeated-stoploss-streak", destination="max_repeated_stoploss_streak", value_type=_positive_int_arg,
    )
    return parser.parse_args(argv)


def _request_from_args(args: argparse.Namespace) -> AccountProtectionPolicyProvisioningRequestV1:
    return AccountProtectionPolicyProvisioningRequestV1(
        account_code=args.account_code,
        venue=args.venue,
        config_version=args.config_version,
        configuration_version=args.configuration_version,
        max_account_drawdown=args.max_account_drawdown,
        max_daily_realized_loss=args.max_daily_realized_loss,
        max_repeated_stoploss_streak=args.max_repeated_stoploss_streak,
        max_metric_age_seconds=args.max_metric_age_seconds,
        effective_from_ts_utc=args.effective_from_ts_utc,
        effective_until_ts_utc=args.effective_until_ts_utc,
        source_provenance=args.source_provenance,
    )


def run(args: argparse.Namespace) -> int:
    print(f"STARTED runner={RUNNER_NAME} mode=provision worker_count=1", flush=True)
    print(SAFETY_MARKERS, flush=True)
    try:
        conn = get_db_connection()
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"FAILED runner={RUNNER_NAME} result=db_unavailable detail={exc}", file=sys.stderr)
        return 1
    try:
        try:
            result = provision_account_protection_policy_v1(conn, request=_request_from_args(args))
        except AccountProtectionPolicyProvisioningError as exc:
            conn.rollback()
            print(f"FAILED runner={RUNNER_NAME} result=provisioning_rejected detail={exc}", file=sys.stderr)
            return 1
        conn.commit()
        print(
            f"ACCOUNT_CODE={args.account_code}\n"
            f"VENUE={args.venue}\n"
            f"CONFIGURATION_VERSION={args.configuration_version}\n"
            f"IDEMPOTENT={result.idempotent}"
        )
        print(SAFETY_MARKERS)
        print(f"FINISHED runner={RUNNER_NAME} result=ok")
        return 0
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
