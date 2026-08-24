from __future__ import annotations

from decimal import Decimal

import pytest

from src.decision_gate.run_automatic_buy_account_config_provisioning_v1 import parse_args

_VALID_BUCKET_ARGV = [
    "strategy-bucket-config",
    "--account-code", "hugo-bitvavo",
    "--venue", "bitvavo",
    "--effective-from-ts-utc", "2026-08-24T12:00:00Z",
    "--source-provenance", "issue_498_acceptance",
    "--strategy-bucket-id", "SHORT_TERM_ROTATION",
    "--risk-profile", "standard",
    "--enabled",
    "--allow-new-entries",
    "--allow-reduce-reviews",
]


def test_valid_decimal_limits_parse_to_decimal_before_any_db_connection() -> None:
    args = parse_args([*_VALID_BUCKET_ARGV, "--max-position-amount-eur", "250.5"])
    assert args.max_position_amount_eur == Decimal("250.5")
    assert isinstance(args.max_position_amount_eur, Decimal)


def test_omitted_decimal_limit_defaults_to_none() -> None:
    args = parse_args(_VALID_BUCKET_ARGV)
    assert args.max_position_amount_eur is None


@pytest.mark.parametrize(
    "flag", ["--max-position-amount-eur", "--max-bucket-amount-eur", "--max-asset-exposure-pct"],
)
def test_invalid_decimal_cli_input_fails_closed_at_parse_time(flag: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #498 PR #499 review: invalid decimal input must be rejected by
    argparse itself (clean exit, no DB connection ever opened), not raise an
    uncaught exception mid-run after STARTED/get_db_connection()."""
    connection_opened = False

    def _fail_if_called() -> None:
        nonlocal connection_opened
        connection_opened = True
        raise AssertionError("get_db_connection must not be called for invalid CLI input")

    monkeypatch.setattr(
        "src.decision_gate.run_automatic_buy_account_config_provisioning_v1.get_db_connection", _fail_if_called,
    )

    with pytest.raises(SystemExit) as exc_info:
        parse_args([*_VALID_BUCKET_ARGV, flag, "not-a-decimal"])

    assert exc_info.value.code == 2
    assert connection_opened is False


def test_invalid_naive_timestamp_fails_closed_at_parse_time(monkeypatch: pytest.MonkeyPatch) -> None:
    connection_opened = False

    def _fail_if_called() -> None:
        nonlocal connection_opened
        connection_opened = True
        raise AssertionError("get_db_connection must not be called for invalid CLI input")

    monkeypatch.setattr(
        "src.decision_gate.run_automatic_buy_account_config_provisioning_v1.get_db_connection", _fail_if_called,
    )

    argv = [
        "account-permission",
        "--account-code", "hugo-bitvavo",
        "--venue", "bitvavo",
        "--effective-from-ts-utc", "not-a-timestamp",
        "--source-provenance", "issue_498_acceptance",
        "--enabled",
    ]
    with pytest.raises(SystemExit) as exc_info:
        parse_args(argv)

    assert exc_info.value.code == 2
    assert connection_opened is False
