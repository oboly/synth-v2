from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.market_data.held_market_coverage_v1 import (
    COVERAGE_FRESH,
    COVERAGE_NOT_ENROLLED,
    COVERAGE_NOT_PUBLISHED,
    COVERAGE_NOT_RESOLVABLE,
    COVERAGE_NO_CANDLES,
    COVERAGE_STALE,
    COVERAGE_UNAVAILABLE_MAP_STATUS,
    NON_RESOLVABLE_DISABLED,
    NON_RESOLVABLE_NO_ASSET,
    RESOLVED_ALREADY_ENROLLED,
    RESOLVED_NEEDS_ENROLLMENT,
    AssetRegistryRow,
    HeldBalance,
    classify_held_coverage,
    resolutions_needing_enrollment,
    resolve_held_markets,
)


def _asset(symbol: str, *, enabled=True, tradeable=True, portfolio=False, core_sensor=False, asset_id=1) -> AssetRegistryRow:
    return AssetRegistryRow(
        asset_id=asset_id,
        symbol=symbol,
        is_enabled=enabled,
        is_tradeable=tradeable,
        is_portfolio=portfolio,
        is_core_sensor=core_sensor,
    )


def test_positive_holding_absent_from_selection_cohort_is_flagged_needing_enrollment() -> None:
    """A held asset that is enabled/tradeable but not is_portfolio/is_core_sensor
    (i.e. absent from the configured watchlist/selection cohort) must be
    resolvable and flagged needs_enrollment=True, not silently dropped."""
    balances = [HeldBalance(trading_account_id=1, account_code="acct-a", currency_code="LIGHTER", total_amount=Decimal("5"))]
    registry = {"LIGHTER": _asset("LIGHTER", asset_id=81)}
    [resolution] = resolve_held_markets(held_balances=balances, quote_currency="EUR", asset_registry_by_symbol=registry)
    assert resolution.resolvable is True
    assert resolution.needs_enrollment is True
    assert resolution.reason == RESOLVED_NEEDS_ENROLLMENT
    assert resolution.market == "LIGHTER-EUR"
    pending = resolutions_needing_enrollment([resolution])
    assert pending == (resolution,)


def test_canonical_identity_resolution_fixture_for_lighter() -> None:
    """LIGHTER resolves through an exact asset.symbol match, carrying the
    correct asset_id/market identity forward — the same identity the
    canonical Fib writer and Profit Plan already key off."""
    balances = [
        HeldBalance(trading_account_id=2, account_code="bitvavo_synth_read", currency_code="LIGHTER", total_amount=Decimal("12.5")),
    ]
    registry = {"LIGHTER": _asset("LIGHTER", asset_id=81, portfolio=False, core_sensor=False)}
    [resolution] = resolve_held_markets(held_balances=balances, quote_currency="EUR", asset_registry_by_symbol=registry)
    assert resolution.symbol == "LIGHTER"
    assert resolution.asset_id == 81
    assert resolution.market == "LIGHTER-EUR"
    assert resolution.held_by_account_codes == ("bitvavo_synth_read",)


def test_display_alias_does_not_affect_machine_joins() -> None:
    """A held currency code of 'LIT' must never resolve against an asset
    registered as 'LIGHTER' -- machine identity is exact-symbol-match only,
    no alias table is consulted here (alias display work is Issue #245)."""
    balances = [HeldBalance(trading_account_id=1, account_code="acct-a", currency_code="LIT", total_amount=Decimal("1"))]
    registry = {"LIGHTER": _asset("LIGHTER", asset_id=81)}
    [resolution] = resolve_held_markets(held_balances=balances, quote_currency="EUR", asset_registry_by_symbol=registry)
    assert resolution.resolvable is False
    assert resolution.reason == NON_RESOLVABLE_NO_ASSET
    assert resolution.symbol is None


def test_non_resolvable_reasons_are_precise_not_generic() -> None:
    balances = [
        HeldBalance(trading_account_id=1, account_code="acct-a", currency_code="GHOST", total_amount=Decimal("1")),
        HeldBalance(trading_account_id=1, account_code="acct-a", currency_code="POL", total_amount=Decimal("1")),
    ]
    registry = {"POL": _asset("POL", enabled=True, tradeable=False, asset_id=5)}
    resolutions = resolve_held_markets(held_balances=balances, quote_currency="EUR", asset_registry_by_symbol=registry)
    by_code = {r.currency_code: r for r in resolutions}
    assert by_code["GHOST"].reason == NON_RESOLVABLE_NO_ASSET
    assert by_code["POL"].reason == NON_RESOLVABLE_DISABLED
    assert by_code["POL"].resolvable is False


def test_zero_balance_and_quote_currency_are_excluded() -> None:
    balances = [
        HeldBalance(trading_account_id=1, account_code="acct-a", currency_code="EUR", total_amount=Decimal("100")),
        HeldBalance(trading_account_id=1, account_code="acct-a", currency_code="SOL", total_amount=Decimal("0")),
        HeldBalance(trading_account_id=1, account_code="acct-a", currency_code="ETH", total_amount=Decimal("-1")),
    ]
    resolutions = resolve_held_markets(held_balances=balances, quote_currency="EUR", asset_registry_by_symbol={})
    assert resolutions == ()


def test_already_enrolled_asset_is_not_flagged_pending() -> None:
    balances = [HeldBalance(trading_account_id=1, account_code="acct-a", currency_code="BTC", total_amount=Decimal("0.1"))]
    registry = {"BTC": _asset("BTC", portfolio=True, asset_id=1)}
    [resolution] = resolve_held_markets(held_balances=balances, quote_currency="EUR", asset_registry_by_symbol=registry)
    assert resolution.reason == RESOLVED_ALREADY_ENROLLED
    assert resolution.needs_enrollment is False
    assert resolutions_needing_enrollment([resolution]) == ()


def _resolved(symbol: str, *, needs_enrollment: bool = False, resolvable: bool = True) -> object:
    from src.market_data.held_market_coverage_v1 import HeldMarketResolution

    return HeldMarketResolution(
        currency_code=symbol,
        symbol=symbol if resolvable else None,
        asset_id=1 if resolvable else None,
        market=f"{symbol}-EUR" if resolvable else None,
        resolvable=resolvable,
        reason=RESOLVED_NEEDS_ENROLLMENT if needs_enrollment else (RESOLVED_ALREADY_ENROLLED if resolvable else NON_RESOLVABLE_NO_ASSET),
        held_by_account_codes=("acct-a",),
        needs_enrollment=needs_enrollment,
    )


def test_missing_history_produces_precise_status_not_fib_map_symbol_missing() -> None:
    """A resolvable, enrolled held symbol with insufficient candle history
    must classify as INSUFFICIENT_CANDLE_HISTORY -- never the reporting-layer
    generic FIB_MAP_SYMBOL_MISSING status."""
    resolution = _resolved("NEWCOIN")
    status = classify_held_coverage(
        resolution,
        candle_count_by_symbol={"NEWCOIN": 5},
        canonical_row_by_symbol={},
        min_required_candles=60,
        available_map_statuses=frozenset({"FRESH"}),
        now_utc=datetime(2026, 8, 6, tzinfo=UTC),
        stale_after=timedelta(hours=8),
    )
    assert status.status == "GAP"
    assert status.reason == COVERAGE_NO_CANDLES
    assert status.reason != "FIB_MAP_SYMBOL_MISSING"
    assert status.candle_count == 5


def test_not_enrolled_symbol_reports_precise_not_enrolled_reason() -> None:
    resolution = _resolved("LIGHTER", needs_enrollment=True)
    status = classify_held_coverage(
        resolution,
        candle_count_by_symbol={"LIGHTER": 560},
        canonical_row_by_symbol={},
        min_required_candles=60,
        available_map_statuses=frozenset({"FRESH"}),
        now_utc=datetime(2026, 8, 6, tzinfo=UTC),
        stale_after=timedelta(hours=8),
    )
    assert status.status == "GAP"
    assert status.reason == COVERAGE_NOT_ENROLLED


def test_enrolled_with_history_but_no_publication_row_is_not_yet_published() -> None:
    resolution = _resolved("LIGHTER")
    status = classify_held_coverage(
        resolution,
        candle_count_by_symbol={"LIGHTER": 560},
        canonical_row_by_symbol={},
        min_required_candles=60,
        available_map_statuses=frozenset({"FRESH"}),
        now_utc=datetime(2026, 8, 6, tzinfo=UTC),
        stale_after=timedelta(hours=8),
    )
    assert status.reason == COVERAGE_NOT_PUBLISHED


def test_stale_canonical_row_is_reported_as_stale_not_fresh() -> None:
    resolution = _resolved("LIGHTER")
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    row = {"map_status": "FRESH", "asof_ts_utc": now - timedelta(hours=20)}
    status = classify_held_coverage(
        resolution,
        candle_count_by_symbol={"LIGHTER": 560},
        canonical_row_by_symbol={"LIGHTER": row},
        min_required_candles=60,
        available_map_statuses=frozenset({"FRESH"}),
        now_utc=now,
        stale_after=timedelta(hours=8),
    )
    assert status.reason == COVERAGE_STALE


def test_fresh_canonical_row_within_all_thresholds_is_ok() -> None:
    resolution = _resolved("LIGHTER")
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    row = {"map_status": "FRESH", "asof_ts_utc": now - timedelta(hours=1)}
    status = classify_held_coverage(
        resolution,
        candle_count_by_symbol={"LIGHTER": 560},
        canonical_row_by_symbol={"LIGHTER": row},
        min_required_candles=60,
        available_map_statuses=frozenset({"FRESH"}),
        now_utc=now,
        stale_after=timedelta(hours=8),
    )
    assert status.status == "OK"
    assert status.reason == COVERAGE_FRESH


def test_non_resolvable_holding_reports_non_resolvable_not_ok() -> None:
    resolution = _resolved("GHOST", resolvable=False)
    status = classify_held_coverage(
        resolution,
        candle_count_by_symbol={},
        canonical_row_by_symbol={},
        min_required_candles=60,
        available_map_statuses=frozenset({"FRESH"}),
        now_utc=datetime(2026, 8, 6, tzinfo=UTC),
        stale_after=timedelta(hours=8),
    )
    assert status.status == "GAP"
    assert status.reason == COVERAGE_NOT_RESOLVABLE


def test_canonical_publication_coverage_invariant_across_all_held_assets() -> None:
    """Aggregate invariant: every resolvable positive holding must land in
    either the OK bucket or carry exactly one precise gap reason -- no
    resolvable holding is silently omitted from the classification."""
    resolutions = [
        _resolved("BTC"),
        _resolved("LIGHTER", needs_enrollment=True),
        _resolved("GHOST", resolvable=False),
    ]
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    statuses = [
        classify_held_coverage(
            r,
            candle_count_by_symbol={"BTC": 1000},
            canonical_row_by_symbol={"BTC": {"map_status": "FRESH", "asof_ts_utc": now - timedelta(minutes=5)}},
            min_required_candles=60,
            available_map_statuses=frozenset({"FRESH"}),
            now_utc=now,
            stale_after=timedelta(hours=8),
        )
        for r in resolutions
    ]
    assert len(statuses) == len(resolutions)
    by_symbol = {s.currency_code: s for s in statuses}
    assert by_symbol["BTC"].status == "OK"
    assert by_symbol["LIGHTER"].status == "GAP" and by_symbol["LIGHTER"].reason == COVERAGE_NOT_ENROLLED
    assert by_symbol["GHOST"].status == "GAP" and by_symbol["GHOST"].reason == COVERAGE_NOT_RESOLVABLE


def test_held_market_coverage_module_has_no_db_or_broker_imports() -> None:
    """held_market_coverage_v1 is pure classification logic -- no SQL, no DB
    connection, no broker access, so it stays trivially unit-testable and
    reusable by both the enrollment writer and the read-only health check."""
    source = Path("src/market_data/held_market_coverage_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"pymysql", "src.common.db", "src.account_provisioning", "src.executor", "src.execution_planner"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in forbidden, node.module


def test_enrollment_writer_only_ever_updates_the_asset_table() -> None:
    """The enrollment writer must not contain INSERT/UPDATE/DELETE against any
    table other than `asset` -- it is a market-wide flag flip, not a general
    write path."""
    source = Path("src/market_data/run_held_market_enrollment_v1.py").read_text(encoding="utf-8")
    for keyword in ("INSERT INTO", "DELETE FROM"):
        assert keyword not in source
    assert source.count("UPDATE ") == 1
    assert "UPDATE asset" in source


def test_health_check_module_contains_no_write_statements() -> None:
    source = Path("src/market_data/run_held_market_coverage_health_check_v1.py").read_text(encoding="utf-8")
    for keyword in ("INSERT INTO", "UPDATE ", "DELETE FROM", "conn.commit"):
        assert keyword not in source


def test_profit_plan_reporting_does_not_import_enrollment_or_writer_modules() -> None:
    """Profit Plan reporting must stay read-only: no writer invocation, no
    enrollment-script import, from either reporting module touched by
    Issue #238."""
    forbidden_modules = {
        "src.market_data.run_held_market_enrollment_v1",
        "src.market_data.run_canonical_fib_zone_map_v1",
        "src.account.run_account_wallet_refresh_v1",
    }
    for path in (
        "src/reporting/manual_short_trader_profit_plan_v1.py",
        "src/reporting/run_manual_short_trader_profit_plan_v1.py",
    ):
        source = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in forbidden_modules, (path, node.module)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden_modules, (path, alias.name)


def test_enrollment_writer_dry_run_by_default_requires_operator_and_reason_to_apply() -> None:
    import src.market_data.run_held_market_enrollment_v1 as enrollment_runner

    args = enrollment_runner.parse_args([])
    assert args.apply is False
    args_apply_missing_reason = enrollment_runner.parse_args(["--apply", "--operator", "joost"])
    assert args_apply_missing_reason.reason is None
