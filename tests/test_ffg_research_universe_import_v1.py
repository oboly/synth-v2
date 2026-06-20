"""
Tests for the FFG research universe import.

All tests run without MySQL.
They verify pure helpers and DB-facing synchronization through recording fakes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.research.run_ffg_research_universe_import_v1 import (
    EXPECTED_CANONICAL,
    EXPECTED_EXCLUDED,
    EXPECTED_MEMBERS,
    EXPECTED_SOURCE_ROWS,
    UNIVERSE_KEY,
    derive_bitvavo_resolution,
    extract_source_exchange,
    main,
    normalize_source_pair_rows,
    synchronize_source_pairs,
    synchronize_universe,
    upsert_signal_snapshot,
    validate_seed_totals,
)


def _make_asset(
    source_symbol: str = "WLD",
    source_row_count: int = 1,
    research_status: str = "RESEARCH_UNIVERSE",
    identity_status: str = "source_pair_resolved",
    source_pairs: list[str] | None = None,
    theme_tags: list[str] | None = None,
    priority_tier: str = "broad_research",
    ffg_return: float = 0.0,
    exclusion_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "source_symbol": source_symbol,
        "source_names": [source_symbol],
        "source_pairs": source_pairs or [f"BINANCE:{source_symbol}USDT"],
        "ffg_virtual_portfolio_return_pct": ffg_return,
        "source_row_count": source_row_count,
        "research_status": research_status,
        "account_plan_default": "NOT_ENABLED",
        "identity_status": identity_status,
        "theme_tags": theme_tags or [],
        "priority_tier": priority_tier,
        "bitvavo_eur_resolution": "PENDING_LOCAL_MARKET_SYNC",
        **({"exclusion_reason": exclusion_reason} if exclusion_reason else {}),
    }


def _make_seed(assets: list[dict[str, Any]], beta_flow_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "ffg_research_universe_seed_v1",
        "assets": assets,
        "beta_flow_snapshot": beta_flow_snapshot or {
            "captured_on": "2026-06-20",
            "timeframe": "UNVERIFIED_BETA",
            "source_confidence": "low",
            "reported_inflow_count": 1,
            "reported_outflow_count": 1,
            "inflows": [{"symbol": "WLD"}],
            "captured_outflow_symbols": ["ETH"],
            "notes": ["research only"],
        },
    }


def _make_member_row(source_symbol: str) -> dict[str, Any]:
    return {
        "universe_key": UNIVERSE_KEY,
        "source_symbol": source_symbol,
        "asset_id": None,
        "source_name": source_symbol,
        "ffg_virtual_portfolio_return_pct": 0.0,
        "research_status": "RESEARCH_UNIVERSE",
        "identity_status": "source_pair_resolved",
        "priority_tier": "broad_research",
        "bitvavo_eur_resolution": "UNAVAILABLE_ON_BITVAVO",
        "account_plan_default": "NOT_ENABLED",
        "theme_tags": "[]",
        "exclusion_reason": None,
        "seed_schema_version": "v1",
    }


def _valid_asset_list() -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    assets.append(_make_asset("USDT", research_status="EXCLUDED", exclusion_reason="quote_asset_not_research_candidate"))
    assets.append(_make_asset("XPLUS", research_status="EXCLUDED", exclusion_reason="source_value_zero_or_unresolved_identity", identity_status="do_not_import"))
    multi_pairs = [
        ("AERO", 2), ("CRO", 2), ("ETH", 3), ("XTZ", 2), ("BCH", 2), ("ENA", 2),
    ]
    for sym, count in multi_pairs:
        assets.append(_make_asset(sym, source_row_count=count))
    for i in range(94):
        assets.append(_make_asset(f"SYM{i:02d}"))
    return assets


class RecordingCursor:
    def __init__(self, conn: "RecordingConnection") -> None:
        self.conn = conn
        self._results: list[dict[str, Any]] = []

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        normalized_sql = " ".join(sql.split())
        self.conn.statements.append((normalized_sql, params))

        if "SELECT source_symbol FROM ffg_research_universe_member_v1" in normalized_sql:
            universe_key = params[0]
            self._results = [{"source_symbol": symbol} for symbol in sorted(self.conn.member_symbols_by_universe.get(universe_key, set()))]
            return

        if "SELECT source_symbol, source_pair FROM ffg_research_source_pair_v1" in normalized_sql:
            universe_key = params[0]
            self._results = [
                {"source_symbol": symbol, "source_pair": pair}
                for symbol, pair in sorted(self.conn.source_pairs_by_universe.get(universe_key, set()))
            ]
            return

        if normalized_sql == "SELECT symbol, asset_id FROM asset":
            self._results = [{"symbol": symbol, "asset_id": asset_id} for symbol, asset_id in sorted(self.conn.asset_rows.items())]
            return

        if "SELECT DISTINCT asset_id FROM obs_venue_ticker_24h" in normalized_sql:
            self._results = [{"asset_id": asset_id} for asset_id in sorted(self.conn.bitvavo_asset_ids)]
            return

        if "SELECT DISTINCT asset_id FROM obs_market_candle" in normalized_sql:
            self._results = [{"asset_id": asset_id} for asset_id in sorted(self.conn.bitvavo_asset_ids)]
            return

        if "SELECT COUNT(*) AS n FROM ffg_research_source_pair_v1" in normalized_sql:
            universe_key = params[0]
            self._results = [{"n": len(self.conn.source_pairs_by_universe.get(universe_key, set()))}]
            return

        if "SELECT COUNT(*) AS canonical_total" in normalized_sql:
            universe_key = params[0]
            rows = self.conn.member_rows_by_universe.get(universe_key, {})
            self._results = [{
                "canonical_total": len(rows),
                "excluded_count": sum(1 for row in rows.values() if row["research_status"] == "EXCLUDED"),
                "member_count": sum(1 for row in rows.values() if row["research_status"] == "RESEARCH_UNIVERSE"),
                "resolved_count": sum(1 for row in rows.values() if row["bitvavo_eur_resolution"] == "RESOLVED"),
                "unavailable_count": sum(1 for row in rows.values() if row["bitvavo_eur_resolution"] == "UNAVAILABLE_ON_BITVAVO"),
                "manual_count": sum(1 for row in rows.values() if row["bitvavo_eur_resolution"] == "REQUIRES_MANUAL_RESOLUTION"),
                "pending_count": sum(1 for row in rows.values() if row["bitvavo_eur_resolution"] == "PENDING_LOCAL_MARKET_SYNC"),
            }]
            return

        if "INSERT INTO ffg_research_universe_member_v1" in normalized_sql:
            row = dict(params)
            universe_key = row["universe_key"]
            symbol = row["source_symbol"]
            self.conn.member_rows_by_universe.setdefault(universe_key, {})[symbol] = row
            self.conn.member_symbols_by_universe.setdefault(universe_key, set()).add(symbol)
            self._results = []
            return

        if "DELETE FROM ffg_research_universe_member_v1" in normalized_sql:
            universe_key = params[0]
            symbols = {str(symbol).upper() for symbol in params[1:]}
            self.conn.member_symbols_by_universe.setdefault(universe_key, set()).difference_update(symbols)
            rows = self.conn.member_rows_by_universe.setdefault(universe_key, {})
            for symbol in symbols:
                rows.pop(symbol, None)
            self._results = []
            return

        if "INSERT INTO ffg_research_source_pair_v1" in normalized_sql:
            universe_key, symbol, pair, _exchange = params
            self.conn.source_pairs_by_universe.setdefault(universe_key, set()).add((symbol, pair))
            self._results = []
            return

        if "DELETE FROM ffg_research_source_pair_v1" in normalized_sql:
            universe_key = params[0]
            flat = list(params[1:])
            pairs = {(str(flat[i]).upper(), str(flat[i + 1]).upper()) for i in range(0, len(flat), 2)}
            self.conn.source_pairs_by_universe.setdefault(universe_key, set()).difference_update(pairs)
            self._results = []
            return

        if "INSERT INTO ffg_external_signal_snapshot_v1" in normalized_sql:
            row = dict(params)
            key = (row["source"], row["captured_on"], row["timeframe"])
            self.conn.signal_snapshots[key] = row
            self._results = []
            return

        self._results = []

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._results)

    def fetchone(self) -> dict[str, Any]:
        return self._results[0]


class RecordingConnection:
    def __init__(
        self,
        *,
        member_symbols_by_universe: dict[str, set[str]] | None = None,
        source_pairs_by_universe: dict[str, set[tuple[str, str]]] | None = None,
        asset_rows: dict[str, int] | None = None,
        bitvavo_asset_ids: set[int] | None = None,
    ) -> None:
        self.member_symbols_by_universe = member_symbols_by_universe or {}
        self.member_rows_by_universe: dict[str, dict[str, dict[str, Any]]] = {
            universe_key: {
                symbol: {
                    "universe_key": universe_key,
                    "source_symbol": symbol,
                    "research_status": "RESEARCH_UNIVERSE",
                    "bitvavo_eur_resolution": "UNAVAILABLE_ON_BITVAVO",
                }
                for symbol in symbols
            }
            for universe_key, symbols in self.member_symbols_by_universe.items()
        }
        self.source_pairs_by_universe = source_pairs_by_universe or {}
        self.asset_rows = asset_rows or {}
        self.bitvavo_asset_ids = bitvavo_asset_ids or set()
        self.signal_snapshots: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.statements: list[tuple[str, Any]] = []
        self.commit_count = 0
        self.close_count = 0

    def cursor(self) -> RecordingCursor:
        return RecordingCursor(self)

    def commit(self) -> None:
        self.commit_count += 1

    def close(self) -> None:
        self.close_count += 1


class TestSeedTotals:
    def test_valid_seed_passes(self) -> None:
        validate_seed_totals(_valid_asset_list())

    def test_wrong_source_rows_raises(self) -> None:
        assets = _valid_asset_list()
        assets.append(_make_asset("EXTRA"))
        with pytest.raises(ValueError, match="source_rows"):
            validate_seed_totals(assets)

    def test_wrong_excluded_count_raises(self) -> None:
        assets = [a for a in _valid_asset_list() if a["source_symbol"] != "USDT"]
        with pytest.raises(ValueError):
            validate_seed_totals(assets)

    def test_total_counts_match_expected_constants(self) -> None:
        assert EXPECTED_SOURCE_ROWS == 109
        assert EXPECTED_CANONICAL == 102
        assert EXPECTED_MEMBERS == 100
        assert EXPECTED_EXCLUDED == 2


class TestAccountPlanBoundary:
    def test_account_plan_default_is_always_not_enabled(self) -> None:
        for asset in _valid_asset_list():
            assert asset["account_plan_default"] == "NOT_ENABLED"

    def test_universe_key_is_market_only(self) -> None:
        assert "ACCOUNT" not in UNIVERSE_KEY
        assert "PORTFOLIO" not in UNIVERSE_KEY
        assert "ORDER" not in UNIVERSE_KEY


class TestDeduplication:
    def test_multi_pair_asset_has_one_canonical_symbol(self) -> None:
        assets = _valid_asset_list()
        symbols = [a["source_symbol"] for a in assets]
        assert symbols.count("AERO") == 1
        assert symbols.count("ETH") == 1

    def test_multi_pair_asset_source_row_count_matches(self) -> None:
        assets = _valid_asset_list()
        aero = next(a for a in assets if a["source_symbol"] == "AERO")
        eth = next(a for a in assets if a["source_symbol"] == "ETH")
        assert aero["source_row_count"] == 2
        assert eth["source_row_count"] == 3

    def test_total_source_rows_equals_sum_of_row_counts(self) -> None:
        assert sum(a["source_row_count"] for a in _valid_asset_list()) == EXPECTED_SOURCE_ROWS


class TestBitvavoResolution:
    def test_resolved_when_symbol_in_asset_table_with_bitvavo_data(self) -> None:
        result = derive_bitvavo_resolution("WLD", "source_pair_resolved", bitvavo_asset_ids={42}, symbol_to_asset_id={"WLD": 42})
        assert result == "RESOLVED"

    def test_unavailable_when_symbol_not_in_asset_table(self) -> None:
        result = derive_bitvavo_resolution("HYPE", "source_pair_resolved", bitvavo_asset_ids=set(), symbol_to_asset_id={})
        assert result == "UNAVAILABLE_ON_BITVAVO"

    def test_unavailable_when_symbol_in_asset_table_but_no_bitvavo_data(self) -> None:
        result = derive_bitvavo_resolution("RNDR", "source_pair_resolved", bitvavo_asset_ids=set(), symbol_to_asset_id={"RNDR": 99})
        assert result == "UNAVAILABLE_ON_BITVAVO"

    def test_requires_manual_for_unresolved_identity(self) -> None:
        result = derive_bitvavo_resolution("BOB", "requires_identity_resolution", bitvavo_asset_ids={5}, symbol_to_asset_id={"BOB": 5})
        assert result == "REQUIRES_MANUAL_RESOLUTION"

    def test_requires_manual_for_do_not_import(self) -> None:
        result = derive_bitvavo_resolution("XPLUS", "do_not_import", bitvavo_asset_ids=set(), symbol_to_asset_id={})
        assert result == "REQUIRES_MANUAL_RESOLUTION"

    def test_requires_manual_takes_priority_over_bitvavo_resolved(self) -> None:
        result = derive_bitvavo_resolution("CC", "requires_identity_resolution", bitvavo_asset_ids={77}, symbol_to_asset_id={"CC": 77})
        assert result == "REQUIRES_MANUAL_RESOLUTION"

    def test_all_identity_resolution_statuses_map_to_manual(self) -> None:
        for status in ("requires_identity_resolution", "do_not_import"):
            assert derive_bitvavo_resolution("X", status, set(), {}) == "REQUIRES_MANUAL_RESOLUTION"


class TestUnresolvedAssets:
    def test_excluded_assets_have_exclusion_reason(self) -> None:
        excluded = [a for a in _valid_asset_list() if a["research_status"] == "EXCLUDED"]
        for asset in excluded:
            assert asset.get("exclusion_reason")

    def test_requires_identity_resolution_assets_are_not_excluded(self) -> None:
        assert _make_asset("ASTR", identity_status="requires_identity_resolution")["research_status"] == "RESEARCH_UNIVERSE"

    def test_unresolved_asset_bitvavo_resolution_is_manual_not_resolved(self) -> None:
        result = derive_bitvavo_resolution("ASTR", "requires_identity_resolution", bitvavo_asset_ids={88}, symbol_to_asset_id={"ASTR": 88})
        assert result == "REQUIRES_MANUAL_RESOLUTION"
        assert result != "RESOLVED"


class TestBetaFlowSnapshot:
    def _make_snapshot(self) -> dict[str, Any]:
        return {
            "source": "FFG",
            "captured_on": "2026-06-20",
            "timeframe": "UNVERIFIED_BETA",
            "source_confidence": "low",
            "reported_inflow_count": 10,
            "captured_inflow_count": 8,
            "reported_outflow_count": 96,
            "inflows": json.dumps([{"symbol": "HYPE", "change_pct": 22.1, "reported_flow_usd": 748100000, "peak_flag": True}]),
            "outflow_symbols": json.dumps(["BTC", "ETH"]),
            "snapshot_notes": json.dumps(["Beta feature; do not use for gate logic."]),
        }

    def test_timeframe_is_unverified_beta(self) -> None:
        assert self._make_snapshot()["timeframe"] == "UNVERIFIED_BETA"

    def test_source_confidence_is_low(self) -> None:
        assert self._make_snapshot()["source_confidence"] == "low"

    def test_inflows_is_json_serializable(self) -> None:
        parsed = json.loads(self._make_snapshot()["inflows"])
        assert isinstance(parsed, list)
        assert parsed[0]["symbol"] == "HYPE"

    def test_snapshot_does_not_contain_decision_gate_fields(self) -> None:
        forbidden_keys = {"decision_gate", "execution_intent", "order_permission", "account_plan"}
        assert not forbidden_keys & set(self._make_snapshot().keys())


class TestSourcePairExtraction:
    def test_exchange_extracted_from_standard_pair(self) -> None:
        assert extract_source_exchange("BINANCE:WLDUSDT") == "BINANCE"

    def test_exchange_extracted_from_crypto_com(self) -> None:
        assert extract_source_exchange("CRYPTO:TRACUSD") == "CRYPTO"

    def test_missing_separator_returns_empty(self) -> None:
        assert extract_source_exchange("NOCOLON") == ""

    def test_multi_pair_asset_all_pairs_extracted(self) -> None:
        assert [extract_source_exchange(p) for p in ["KUCOIN:AEROUSDT", "COINBASE:AEROUSD"]] == ["KUCOIN", "COINBASE"]


class TestNormalization:
    def test_normalize_source_pair_rows_deduplicates_and_sorts(self) -> None:
        assets = [
            _make_asset("wld", source_pairs=["coinbase:wldusd", "BINANCE:WLDUSDT", "coinbase:wldusd"]),
            _make_asset("eth", source_pairs=["BINANCE:ETHUSDT"]),
        ]
        assert normalize_source_pair_rows(UNIVERSE_KEY, assets) == [
            (UNIVERSE_KEY, "ETH", "BINANCE:ETHUSDT", "BINANCE"),
            (UNIVERSE_KEY, "WLD", "BINANCE:WLDUSDT", "BINANCE"),
            (UNIVERSE_KEY, "WLD", "COINBASE:WLDUSD", "COINBASE"),
        ]


class TestDbSynchronization:
    def test_repeat_import_with_unchanged_seed_has_no_stale_delete_targets(self) -> None:
        assets = [
            _make_asset("WLD", source_pairs=["BINANCE:WLDUSDT", "COINBASE:WLDUSD"]),
            _make_asset("ETH", source_pairs=["BINANCE:ETHUSDT"]),
        ]
        conn = RecordingConnection(
            member_symbols_by_universe={UNIVERSE_KEY: {"WLD", "ETH"}},
            source_pairs_by_universe={UNIVERSE_KEY: {("WLD", "BINANCE:WLDUSDT"), ("WLD", "COINBASE:WLDUSD"), ("ETH", "BINANCE:ETHUSDT")}},
        )

        stale_members, stale_pairs, pair_count = synchronize_universe(
            conn=conn,
            universe_key=UNIVERSE_KEY,
            member_rows=[_make_member_row("WLD"), _make_member_row("ETH")],
            assets=assets,
            beta_flow={},
            dry_run=False,
        )

        assert stale_members == set()
        assert stale_pairs == set()
        assert pair_count == 3
        assert not [sql for sql, _ in conn.statements if "DELETE FROM ffg_research_source_pair_v1" in sql]
        assert not [sql for sql, _ in conn.statements if "DELETE FROM ffg_research_universe_member_v1" in sql]

    def test_corrected_seed_deletes_removed_source_pairs_only_within_its_universe(self) -> None:
        conn = RecordingConnection(
            source_pairs_by_universe={
                UNIVERSE_KEY: {("WLD", "BINANCE:WLDUSDT"), ("WLD", "COINBASE:WLDUSD")},
                "OTHER_UNIVERSE": {("WLD", "COINBASE:WLDUSD")},
            },
        )

        stale_pairs = synchronize_source_pairs(conn, UNIVERSE_KEY, [_make_asset("WLD", source_pairs=["BINANCE:WLDUSDT"])], dry_run=False)

        assert stale_pairs == {("WLD", "COINBASE:WLDUSD")}
        delete_statements = [(sql, params) for sql, params in conn.statements if "DELETE FROM ffg_research_source_pair_v1" in sql]
        assert len(delete_statements) == 1
        assert delete_statements[0][1] == (UNIVERSE_KEY, "WLD", "COINBASE:WLDUSD")
        assert conn.source_pairs_by_universe["OTHER_UNIVERSE"] == {("WLD", "COINBASE:WLDUSD")}

    def test_empty_source_pair_seed_removes_all_pairs_for_that_universe_only(self) -> None:
        conn = RecordingConnection(
            source_pairs_by_universe={
                UNIVERSE_KEY: {("WLD", "BINANCE:WLDUSDT"), ("ETH", "BINANCE:ETHUSDT")},
                "OTHER_UNIVERSE": {("WLD", "COINBASE:WLDUSD")},
            },
        )

        stale_pairs = synchronize_source_pairs(conn, UNIVERSE_KEY, [{"source_symbol": "WLD", "source_pairs": []}], dry_run=False)

        assert stale_pairs == {("WLD", "BINANCE:WLDUSDT"), ("ETH", "BINANCE:ETHUSDT")}
        assert conn.source_pairs_by_universe[UNIVERSE_KEY] == set()
        assert conn.source_pairs_by_universe["OTHER_UNIVERSE"] == {("WLD", "COINBASE:WLDUSD")}

    def test_corrected_same_key_signal_snapshot_uses_upsert_update_path(self) -> None:
        conn = RecordingConnection()
        snapshot = {
            "source": "FFG",
            "captured_on": "2026-06-20",
            "timeframe": "UNVERIFIED_BETA",
            "source_confidence": "low",
            "reported_inflow_count": 10,
            "captured_inflow_count": 8,
            "reported_outflow_count": 96,
            "inflows": "[]",
            "outflow_symbols": "[]",
            "snapshot_notes": "[]",
        }

        upsert_signal_snapshot(conn, snapshot, dry_run=False)
        corrected_snapshot = dict(snapshot)
        corrected_snapshot["reported_inflow_count"] = 11
        upsert_signal_snapshot(conn, corrected_snapshot, dry_run=False)

        statements = [sql for sql, _ in conn.statements if "ffg_external_signal_snapshot_v1" in sql]
        assert len(statements) == 2
        assert all("ON DUPLICATE KEY UPDATE" in sql for sql in statements)
        assert len(conn.signal_snapshots) == 1
        assert conn.signal_snapshots[("FFG", "2026-06-20", "UNVERIFIED_BETA")]["reported_inflow_count"] == 11

    def test_source_pair_and_member_synchronization_is_transactional_in_main(self) -> None:
        conn = RecordingConnection(asset_rows={"AERO": 1}, bitvavo_asset_ids={1})
        seed = _make_seed(_valid_asset_list())

        with patch("src.research.run_ffg_research_universe_import_v1.get_connection", return_value=conn), \
             patch("src.research.run_ffg_research_universe_import_v1.load_seed", return_value=seed), \
             patch("sys.argv", ["ffg_import", "--seed-file", str(Path("/tmp/ffg.json"))]):
            result = main()

        assert result == 0
        assert conn.commit_count == 1
        assert conn.close_count == 1
        verification_index = next(i for i, (sql, _params) in enumerate(conn.statements) if "SELECT COUNT(*) AS n FROM ffg_research_source_pair_v1" in sql)
        write_indexes = [
            i for i, (sql, _params) in enumerate(conn.statements)
            if (
                "INSERT INTO ffg_research_universe_member_v1" in sql
                or "INSERT INTO ffg_research_source_pair_v1" in sql
                or "DELETE FROM ffg_research_universe_member_v1" in sql
                or "DELETE FROM ffg_research_source_pair_v1" in sql
            )
        ]
        assert write_indexes
        assert max(write_indexes) < verification_index

    def test_no_sql_writes_target_runtime_or_trading_tables(self) -> None:
        conn = RecordingConnection(
            member_symbols_by_universe={UNIVERSE_KEY: {"OLD"}},
            source_pairs_by_universe={UNIVERSE_KEY: {("OLD", "BINANCE:OLDUSDT")}},
        )

        synchronize_universe(
            conn=conn,
            universe_key=UNIVERSE_KEY,
            member_rows=[_make_member_row("WLD")],
            assets=[_make_asset("WLD", source_pairs=["BINANCE:WLDUSDT"])],
            beta_flow={},
            dry_run=False,
        )

        forbidden_targets = (
            "update asset ",
            "insert into asset ",
            "delete from asset ",
            "account_asset",
            "selection_engine",
            "decision_gate",
            "execution_planner",
            "executor",
            "broker",
            "profit_plan",
            "order",
        )
        write_statements = [
            sql.lower()
            for sql, _params in conn.statements
            if sql.startswith("INSERT") or sql.startswith("DELETE") or sql.startswith("UPDATE")
        ]
        assert write_statements
        assert all(
            "ffg_research_universe_member_v1".lower() in sql
            or "ffg_research_source_pair_v1".lower() in sql
            or "ffg_external_signal_snapshot_v1".lower() in sql
            for sql in write_statements
        )
        assert not any(target in sql for sql in write_statements for target in forbidden_targets)

    def test_stale_members_are_reconciled_for_authoritative_seed(self) -> None:
        conn = RecordingConnection(member_symbols_by_universe={UNIVERSE_KEY: {"WLD", "ETH"}})

        stale_members, _stale_pairs, _pair_count = synchronize_universe(
            conn=conn,
            universe_key=UNIVERSE_KEY,
            member_rows=[_make_member_row("WLD")],
            assets=[],
            beta_flow={},
            dry_run=False,
        )

        assert stale_members == {"ETH"}
        delete_statements = [(sql, params) for sql, params in conn.statements if "DELETE FROM ffg_research_universe_member_v1" in sql]
        assert len(delete_statements) == 1
        assert delete_statements[0][1] == (UNIVERSE_KEY, "ETH")
