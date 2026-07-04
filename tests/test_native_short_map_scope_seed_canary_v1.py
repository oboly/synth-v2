from __future__ import annotations

import ast
import io
import sys
from pathlib import Path
from typing import Any

import pytest

from src.market_data import run_native_short_map_scope_seed_canary_v1 as runner


def _market_row(
    symbol: str = "BTC",
    *,
    venue: str = "bitvavo",
    quote_currency: str = "EUR",
    market: str | None = None,
    venue_market_id: int = 1,
    is_market_data_enabled: Any = 1,
    is_tradeable: Any = 1,
    is_enabled: Any = 1,
) -> dict[str, Any]:
    return {
        "venue_market_id": venue_market_id,
        "venue": venue,
        "market": market if market is not None else f"{symbol}-{quote_currency}",
        "symbol": symbol,
        "quote_currency": quote_currency,
        "is_market_data_enabled": is_market_data_enabled,
        "is_tradeable": is_tradeable,
        "is_enabled": is_enabled,
    }


def _scope_row(
    symbol: str = "BTC",
    *,
    scope_id: int = 1,
    state: str = "SUPPORTED",
    reason_code: str | None = None,
    reason_detail: str | None = None,
) -> dict[str, Any]:
    return {
        "scope_id": scope_id,
        "venue": "bitvavo",
        "symbol": symbol,
        "quote_currency": "EUR",
        "fib_trading_horizon": "SHORT",
        "primary_interval": "4h",
        "supporting_interval": "1h",
        "scope_support_state": state,
        "scope_reason_code": reason_code,
        "scope_reason_detail": reason_detail,
    }


class _FakeCursor:
    """List-backed fake that preserves duplicate rows and only supports fetchall."""

    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn
        self._rows: list[dict[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        normalized = " ".join(sql.split())
        self._conn.executions.append((normalized, params))
        if "FROM venue_market vm" in sql:
            venue, market, quote_currency, symbol = params
            self._rows = [
                dict(row)
                for row in self._conn.market_rows
                if row["venue"] == venue
                and row["market"] == market
                and row["quote_currency"] == quote_currency
                and row["symbol"] == symbol
            ]
            return
        if "FROM native_short_map_scope_v1" in sql:
            venue, symbol, quote_currency, horizon, primary, support = params
            visible = self._conn.scope_rows + self._conn.pending_inserts
            self._rows = [
                dict(row)
                for row in visible
                if row["venue"] == venue
                and row["symbol"] == symbol
                and row["quote_currency"] == quote_currency
                and row["fib_trading_horizon"] == horizon
                and row["primary_interval"] == primary
                and row["supporting_interval"] == support
            ]
            return
        if normalized.startswith("INSERT INTO native_short_map_scope_v1"):
            (
                venue,
                symbol,
                quote_currency,
                horizon,
                primary,
                support,
                state,
                reason_code,
                reason_detail,
            ) = params
            self._conn.pending_inserts.append(
                {
                    "scope_id": 99,
                    "venue": venue,
                    "symbol": symbol,
                    "quote_currency": quote_currency,
                    "fib_trading_horizon": horizon,
                    "primary_interval": primary,
                    "supporting_interval": support,
                    "scope_support_state": state,
                    "scope_reason_code": reason_code,
                    "scope_reason_detail": reason_detail,
                }
            )
            if self._conn.fail_insert:
                raise RuntimeError("insert failed")
            self._rows = []
            return
        raise AssertionError(f"Unexpected SQL: {normalized}")

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


class _FakeConn:
    def __init__(
        self,
        *,
        market_rows: list[dict[str, Any]] | None = None,
        scope_rows: list[dict[str, Any]] | None = None,
        fail_insert: bool = False,
    ) -> None:
        self.market_rows = list(market_rows or [])
        self.scope_rows = list(scope_rows or [])
        self.pending_inserts: list[dict[str, Any]] = []
        self.fail_insert = fail_insert
        self.executions: list[tuple[str, Any]] = []
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def begin(self) -> None:
        self.begin_count += 1

    def commit(self) -> None:
        self.commit_count += 1
        self.scope_rows.extend(self.pending_inserts)
        self.pending_inserts = []

    def rollback(self) -> None:
        self.rollback_count += 1
        self.pending_inserts = []

    def close(self) -> None:
        self.close_count += 1

    @property
    def committed_inserts(self) -> list[dict[str, Any]]:
        return [row for row in self.scope_rows if row.get("scope_id") == 99]


def _capture_main(monkeypatch: pytest.MonkeyPatch, conn: _FakeConn, argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()

    monkeypatch.setattr(runner, "get_connection", lambda: conn)
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = stdout
    sys.stderr = stderr
    try:
        code = runner.main(argv)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return code, stdout.getvalue(), stderr.getvalue()


def _capture_main_no_db(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> tuple[int, str, str]:
    def _forbidden() -> Any:
        raise AssertionError("DB connection must not be opened")

    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(runner, "get_connection", _forbidden)
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = stdout
    sys.stderr = stderr
    try:
        code = runner.main(argv)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return code, stdout.getvalue(), stderr.getvalue()


def test_parse_symbols_is_explicit_and_deterministic() -> None:
    assert runner.parse_symbols("eth,BTC, btc") == ["BTC", "ETH"]


def test_dry_run_default_has_no_transaction_and_no_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(market_rows=[_market_row()])

    code, out, err = _capture_main(monkeypatch, conn, ["--symbols", "BTC", "--output", "summary"])

    assert code == 0
    assert err == ""
    assert "PLANNED symbol=BTC market=BTC-EUR eligible=True" in out
    assert "dry_run=True write=False" in out
    assert conn.begin_count == 0
    assert conn.commit_count == 0
    assert conn.rollback_count == 0
    assert conn.pending_inserts == []
    assert conn.committed_inserts == []
    assert not any(sql.startswith("INSERT") for sql, _ in conn.executions)


def test_dry_run_allows_multiple_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(market_rows=[_market_row("BTC"), _market_row("ETH", venue_market_id=2)])

    code, out, _ = _capture_main(monkeypatch, conn, ["--symbols", "BTC,ETH", "--output", "summary"])

    assert code == 0
    assert "PLANNED symbol=BTC" in out
    assert "PLANNED symbol=ETH" in out
    assert "planned=2 seeded=0 skipped=0 failed=0" in out
    assert conn.begin_count == 0
    assert conn.committed_inserts == []


def test_btc_eligible_dry_run_plan_uses_canonical_scope_values() -> None:
    conn = _FakeConn(market_rows=[_market_row()])

    plan = runner.build_scope_seed_plan(conn, venue="bitvavo", symbol="BTC")

    assert plan.status == "planned"
    assert plan.eligible is True
    assert plan.venue == "bitvavo"
    assert plan.symbol == "BTC"
    assert plan.quote_currency == "EUR"
    assert plan.fib_trading_horizon == "SHORT"
    assert plan.primary_interval == "4h"
    assert plan.supporting_interval == "1h"
    assert plan.reason_code is None
    market_sql, market_params = conn.executions[0]
    assert "FROM venue_market vm" in market_sql
    assert market_params == ("bitvavo", "BTC-EUR", "EUR", "BTC")


def test_explicit_write_seeds_exact_supported_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(market_rows=[_market_row()])

    code, out, _ = _capture_main(monkeypatch, conn, ["--symbols", "BTC", "--write", "--output", "summary"])

    assert code == 0
    assert "SEEDED symbol=BTC market=BTC-EUR eligible=True" in out
    assert "planned=0 seeded=1 skipped=0 failed=0" in out
    assert conn.begin_count == 1
    assert conn.commit_count == 1
    assert conn.rollback_count == 0
    assert len(conn.committed_inserts) == 1
    inserted = conn.committed_inserts[0]
    assert inserted["venue"] == "bitvavo"
    assert inserted["symbol"] == "BTC"
    assert inserted["quote_currency"] == "EUR"
    assert inserted["fib_trading_horizon"] == "SHORT"
    assert inserted["primary_interval"] == "4h"
    assert inserted["supporting_interval"] == "1h"
    assert inserted["scope_support_state"] == "SUPPORTED"
    assert inserted["scope_reason_code"] is None
    assert inserted["scope_reason_detail"] is None


def test_identical_supported_scope_is_skipped_in_write_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(market_rows=[_market_row()], scope_rows=[_scope_row()])

    code, out, _ = _capture_main(monkeypatch, conn, ["--symbols", "BTC", "--write", "--output", "summary"])

    assert code == 0
    assert "SKIPPED symbol=BTC market=BTC-EUR eligible=True reason=SCOPE_ALREADY_SUPPORTED" in out
    assert "planned=0 seeded=0 skipped=1 failed=0" in out
    assert conn.commit_count == 0
    assert conn.rollback_count == 1
    assert conn.committed_inserts == []


def test_identical_supported_scope_is_skipped_in_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(market_rows=[_market_row()], scope_rows=[_scope_row()])

    code, out, _ = _capture_main(monkeypatch, conn, ["--symbols", "BTC", "--output", "summary"])

    assert code == 0
    assert "SKIPPED symbol=BTC market=BTC-EUR eligible=True reason=SCOPE_ALREADY_SUPPORTED" in out
    assert conn.begin_count == 0
    assert conn.committed_inserts == []


def test_write_with_empty_symbols_rejected_before_db(monkeypatch: pytest.MonkeyPatch) -> None:
    code, out, err = _capture_main_no_db(monkeypatch, ["--symbols", " , ", "--write"])

    assert code == 2
    assert "at least one symbol" in err
    assert out == ""


def test_write_with_multiple_symbols_rejected_before_db(monkeypatch: pytest.MonkeyPatch) -> None:
    code, out, err = _capture_main_no_db(monkeypatch, ["--symbols", "BTC,ETH", "--write"])

    assert code == 2
    assert "--write requires exactly one explicit symbol; parsed 2" in err
    assert out == ""


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("is_market_data_enabled", 0, "MARKET_DATA_NOT_ENABLED"),
        ("is_market_data_enabled", None, "MARKET_DATA_NOT_ENABLED"),
        ("is_tradeable", 0, "MARKET_NOT_TRADEABLE"),
        ("is_tradeable", None, "MARKET_NOT_TRADEABLE"),
        ("is_enabled", 0, "ASSET_NOT_ENABLED"),
        ("is_enabled", None, "ASSET_NOT_ENABLED"),
    ],
)
def test_ineligible_flag_fails_closed(
    monkeypatch: pytest.MonkeyPatch, field: str, value: Any, reason: str
) -> None:
    conn = _FakeConn(market_rows=[_market_row(**{field: value})])

    code, out, _ = _capture_main(monkeypatch, conn, ["--symbols", "BTC", "--write", "--output", "summary"])

    assert code == 1
    assert f"FAILED symbol=BTC market=BTC-EUR eligible=False reason={reason}" in out
    assert conn.commit_count == 0
    assert conn.rollback_count == 1
    assert conn.committed_inserts == []


def test_non_integer_flag_fails_closed() -> None:
    conn = _FakeConn(market_rows=[_market_row(is_tradeable="yes")])

    plan = runner.build_scope_seed_plan(conn, venue="bitvavo", symbol="BTC")

    assert plan.status == "failed"
    assert plan.reason_code == "MARKET_NOT_TRADEABLE"


def test_wrong_venue_has_no_market_match() -> None:
    conn = _FakeConn(market_rows=[_market_row(venue="kraken")])

    plan = runner.build_scope_seed_plan(conn, venue="bitvavo", symbol="BTC")

    assert plan.status == "failed"
    assert plan.reason_code == "VENUE_MARKET_NOT_FOUND"


def test_wrong_quote_has_no_market_match() -> None:
    conn = _FakeConn(market_rows=[_market_row(quote_currency="USDT")])

    plan = runner.build_scope_seed_plan(conn, venue="bitvavo", symbol="BTC", quote_currency="EUR")

    assert plan.status == "failed"
    assert plan.reason_code == "VENUE_MARKET_NOT_FOUND"


def test_missing_market_rejected_without_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()

    code, out, _ = _capture_main(monkeypatch, conn, ["--symbols", "BTC", "--write", "--output", "summary"])

    assert code == 1
    assert "FAILED symbol=BTC market=BTC-EUR eligible=False reason=VENUE_MARKET_NOT_FOUND" in out
    assert conn.begin_count == 1
    assert conn.commit_count == 0
    assert conn.rollback_count == 1
    assert conn.committed_inserts == []


def test_duplicate_eligible_market_rows_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(
        market_rows=[
            _market_row(venue_market_id=1),
            _market_row(venue_market_id=2),
        ]
    )

    code, out, _ = _capture_main(monkeypatch, conn, ["--symbols", "BTC", "--write", "--output", "summary"])

    assert code == 1
    assert "FAILED symbol=BTC market=BTC-EUR eligible=False reason=AMBIGUOUS_VENUE_MARKET" in out
    assert conn.commit_count == 0
    assert conn.committed_inserts == []


def test_duplicate_canonical_scope_rows_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(
        market_rows=[_market_row()],
        scope_rows=[_scope_row(scope_id=1), _scope_row(scope_id=2)],
    )

    code, out, _ = _capture_main(monkeypatch, conn, ["--symbols", "BTC", "--write", "--output", "summary"])

    assert code == 1
    assert "FAILED symbol=BTC market=BTC-EUR eligible=True reason=AMBIGUOUS_SCOPE" in out
    assert conn.commit_count == 0
    assert conn.committed_inserts == []


def test_existing_not_applicable_scope_is_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(
        market_rows=[_market_row()],
        scope_rows=[_scope_row(state="NOT_APPLICABLE", reason_code="NOT_SHORT_NATIVE")],
    )

    code, out, _ = _capture_main(monkeypatch, conn, ["--symbols", "BTC", "--write", "--output", "summary"])

    assert code == 1
    assert "FAILED symbol=BTC market=BTC-EUR eligible=True reason=SCOPE_CONFLICT" in out
    assert conn.commit_count == 0
    assert conn.committed_inserts == []


def test_supported_scope_with_reason_detail_is_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(
        market_rows=[_market_row()],
        scope_rows=[_scope_row(state="SUPPORTED", reason_detail="legacy note")],
    )

    code, out, _ = _capture_main(monkeypatch, conn, ["--symbols", "BTC", "--write", "--output", "summary"])

    assert code == 1
    assert "reason=SCOPE_CONFLICT" in out
    assert conn.committed_inserts == []


def test_rollback_after_insert_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(market_rows=[_market_row()], fail_insert=True)

    code, out, _ = _capture_main(monkeypatch, conn, ["--symbols", "BTC", "--write", "--output", "summary"])

    assert code == 1
    assert "FAILED symbol=BTC market=BTC-EUR eligible=False reason=RuntimeError" in out
    assert conn.begin_count == 1
    assert conn.commit_count == 0
    assert conn.rollback_count == 1
    assert conn.pending_inserts == []
    assert conn.committed_inserts == []


def test_connection_failure_reports_failed_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def _broken() -> Any:
        raise RuntimeError("db unreachable")

    stdout = io.StringIO()
    monkeypatch.setattr(runner, "get_connection", _broken)
    old_stdout = sys.stdout
    sys.stdout = stdout
    try:
        code = runner.main(["--symbols", "BTC", "--output", "summary"])
    finally:
        sys.stdout = old_stdout
    out = stdout.getvalue()

    assert code == 1
    assert "FAILED symbol=BTC market=BTC-EUR eligible=False reason=RuntimeError" in out
    assert "FAILED runner=native_short_map_scope_seed_canary_v1 requested=1" in out


def test_write_scope_select_uses_for_update_lock() -> None:
    conn = _FakeConn(market_rows=[_market_row()])

    runner.run_write_symbol(conn, venue="bitvavo", symbol="BTC", quote_currency="EUR")

    assert any("FROM native_short_map_scope_v1" in sql and "FOR UPDATE" in sql for sql, _ in conn.executions)


def test_dry_run_scope_select_has_no_lock() -> None:
    conn = _FakeConn(market_rows=[_market_row()])

    runner.run_dry_run_symbol(conn, venue="bitvavo", symbol="BTC", quote_currency="EUR")

    scope_selects = [sql for sql, _ in conn.executions if "FROM native_short_map_scope_v1" in sql]
    assert scope_selects
    assert all("FOR UPDATE" not in sql for sql in scope_selects)
    assert conn.begin_count == 0
    assert conn.commit_count == 0
    assert conn.rollback_count == 0


def test_runner_has_no_forbidden_layer_imports_or_reachable_project_deps() -> None:
    root = Path(__file__).parent.parent
    checked = [
        root / "src" / "market_data" / "run_native_short_map_scope_seed_canary_v1.py",
        root / "src" / "market_data" / "native_short_map_lifecycle_v1.py",
        root / "src" / "common" / "db.py",
    ]
    forbidden = (
        "src.account",
        "src.portfolio",
        "src.selection",
        "src.advice",
        "src.decision_gate",
        "src.execution_planner",
        "src.executor",
        "src.execution",
        "src.operations",
        "src.reporting",
        "src.web",
        "src.live",
        "src.broker",
        "src.etl",
    )
    for path in checked:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                assert not any(
                    module == item or module.startswith(f"{item}.") for item in forbidden
                ), f"forbidden import {module} in {path}"


def test_runner_source_only_writes_scope_table_and_hides_no_duplicates() -> None:
    src = (
        Path(__file__).parent.parent
        / "src"
        / "market_data"
        / "run_native_short_map_scope_seed_canary_v1.py"
    ).read_text()
    assert src.count("INSERT INTO") == 1
    assert "INSERT INTO native_short_map_scope_v1" in src
    assert "UPDATE native_short_map_scope_v1" not in src
    assert "UPDATE venue_market" not in src
    assert "UPDATE asset" not in src
    assert "DELETE FROM" not in src
    assert "LIMIT 1" not in src
    assert "fetchone" not in src
