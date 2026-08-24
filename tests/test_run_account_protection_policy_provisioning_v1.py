from __future__ import annotations

from decimal import Decimal

import pytest

from src.decision_gate.run_account_protection_policy_provisioning_v1 import parse_args

_BASE_ARGV = [
    "--account-code", "hugo-bitvavo",
    "--venue", "bitvavo",
    "--config-version", "1",
    "--configuration-version", "issue_504_acceptance",
    "--max-metric-age-seconds", "900",
    "--effective-from-ts-utc", "2026-08-24T12:00:00Z",
    "--source-provenance", "issue_504_acceptance",
    "--disable-max-account-drawdown",
    "--disable-max-daily-realized-loss",
    "--disable-max-repeated-stoploss-streak",
]


def test_all_metrics_disabled_parses_to_none() -> None:
    args = parse_args(_BASE_ARGV)
    assert args.max_account_drawdown is None
    assert args.max_daily_realized_loss is None
    assert args.max_repeated_stoploss_streak is None


def test_explicit_metric_values_parse_to_typed_positive_values() -> None:
    argv = [
        "--account-code", "hugo-bitvavo",
        "--venue", "bitvavo",
        "--config-version", "1",
        "--configuration-version", "issue_504_acceptance",
        "--max-metric-age-seconds", "900",
        "--effective-from-ts-utc", "2026-08-24T12:00:00Z",
        "--source-provenance", "issue_504_acceptance",
        "--max-account-drawdown", "500.5",
        "--disable-max-daily-realized-loss",
        "--max-repeated-stoploss-streak", "3",
    ]
    args = parse_args(argv)
    assert args.max_account_drawdown == Decimal("500.5")
    assert isinstance(args.max_account_drawdown, Decimal)
    assert args.max_repeated_stoploss_streak == 3


def test_metric_flag_and_its_disable_flag_are_mutually_exclusive() -> None:
    argv = [*_BASE_ARGV[:-3], "--max-account-drawdown", "100", "--disable-max-account-drawdown"]
    with pytest.raises(SystemExit) as exc_info:
        parse_args(argv)
    assert exc_info.value.code == 2


def test_omitting_a_metric_choice_entirely_is_rejected_not_defaulted() -> None:
    """No permissive default: every metric must be explicitly enabled or disabled."""
    argv = [
        "--account-code", "hugo-bitvavo",
        "--venue", "bitvavo",
        "--config-version", "1",
        "--configuration-version", "issue_504_acceptance",
        "--max-metric-age-seconds", "900",
        "--effective-from-ts-utc", "2026-08-24T12:00:00Z",
        "--source-provenance", "issue_504_acceptance",
        "--disable-max-daily-realized-loss",
        "--disable-max-repeated-stoploss-streak",
    ]
    with pytest.raises(SystemExit) as exc_info:
        parse_args(argv)
    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    "flag", ["--max-account-drawdown", "--max-daily-realized-loss"],
)
def test_invalid_decimal_cli_input_fails_closed_at_parse_time(flag: str, monkeypatch: pytest.MonkeyPatch) -> None:
    connection_opened = False

    def _fail_if_called() -> None:
        nonlocal connection_opened
        connection_opened = True
        raise AssertionError("get_db_connection must not be called for invalid CLI input")

    monkeypatch.setattr(
        "src.decision_gate.run_account_protection_policy_provisioning_v1.get_db_connection", _fail_if_called,
    )
    other_flag = "--disable-max-daily-realized-loss" if flag == "--max-account-drawdown" else "--disable-max-account-drawdown"
    argv = [
        "--account-code", "hugo-bitvavo",
        "--venue", "bitvavo",
        "--config-version", "1",
        "--configuration-version", "issue_504_acceptance",
        "--max-metric-age-seconds", "900",
        "--effective-from-ts-utc", "2026-08-24T12:00:00Z",
        "--source-provenance", "issue_504_acceptance",
        flag, "not-a-decimal",
        other_flag,
        "--disable-max-repeated-stoploss-streak",
    ]
    with pytest.raises(SystemExit) as exc_info:
        parse_args(argv)
    assert exc_info.value.code == 2
    assert connection_opened is False


def test_non_positive_decimal_metric_rejected_at_parse_time() -> None:
    argv = [*_BASE_ARGV[:-3], "--max-account-drawdown", "0", "--disable-max-daily-realized-loss", "--disable-max-repeated-stoploss-streak"]
    with pytest.raises(SystemExit) as exc_info:
        parse_args(argv)
    assert exc_info.value.code == 2


def test_negative_metric_age_rejected_at_parse_time() -> None:
    argv = [
        "--account-code", "hugo-bitvavo",
        "--venue", "bitvavo",
        "--config-version", "1",
        "--configuration-version", "issue_504_acceptance",
        "--max-metric-age-seconds", "-1",
        "--effective-from-ts-utc", "2026-08-24T12:00:00Z",
        "--source-provenance", "issue_504_acceptance",
        "--disable-max-account-drawdown",
        "--disable-max-daily-realized-loss",
        "--disable-max-repeated-stoploss-streak",
    ]
    with pytest.raises(SystemExit) as exc_info:
        parse_args(argv)
    assert exc_info.value.code == 2


def test_naive_timestamp_rejected_at_parse_time(monkeypatch: pytest.MonkeyPatch) -> None:
    connection_opened = False

    def _fail_if_called() -> None:
        nonlocal connection_opened
        connection_opened = True
        raise AssertionError("get_db_connection must not be called for invalid CLI input")

    monkeypatch.setattr(
        "src.decision_gate.run_account_protection_policy_provisioning_v1.get_db_connection", _fail_if_called,
    )
    argv = [
        "--account-code", "hugo-bitvavo",
        "--venue", "bitvavo",
        "--config-version", "1",
        "--configuration-version", "issue_504_acceptance",
        "--max-metric-age-seconds", "900",
        "--effective-from-ts-utc", "2026-08-24T12:00:00",  # no timezone
        "--source-provenance", "issue_504_acceptance",
        "--disable-max-account-drawdown",
        "--disable-max-daily-realized-loss",
        "--disable-max-repeated-stoploss-streak",
    ]
    with pytest.raises(SystemExit) as exc_info:
        parse_args(argv)
    assert exc_info.value.code == 2
    assert connection_opened is False


def test_unsupported_config_version_rejected_at_parse_time() -> None:
    argv = [
        "--account-code", "hugo-bitvavo",
        "--venue", "bitvavo",
        "--config-version", "999",
        "--configuration-version", "issue_504_acceptance",
        "--max-metric-age-seconds", "900",
        "--effective-from-ts-utc", "2026-08-24T12:00:00Z",
        "--source-provenance", "issue_504_acceptance",
        "--disable-max-account-drawdown",
        "--disable-max-daily-realized-loss",
        "--disable-max-repeated-stoploss-streak",
    ]
    with pytest.raises(SystemExit) as exc_info:
        parse_args(argv)
    assert exc_info.value.code == 2
