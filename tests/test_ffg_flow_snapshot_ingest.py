from __future__ import annotations

import json
import copy
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.research.run_ffg_flow_snapshot_ingest import (
    ARTIFACT_KIND_HTML,
    ARTIFACT_KIND_TEXT,
    EXIT_CODE_EXPECTED_FAILURE,
    EXIT_CODE_UNEXPECTED_FAILURE,
    LIST_SCOPE_FFG,
    LIST_SCOPE_OUTSIDE,
    PARSE_STATUS_WARNINGS,
    REQUIRED_INGEST_TABLES,
    REQUIRED_SUPPORT_TABLES,
    SOURCE_NAME,
    build_ingest_plan,
    main,
    parse_artifact,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ffg_flow_snapshot_ingest"
TEXT_FIXTURE = FIXTURE_DIR / "sample_flow_snapshot.txt"
HTML_FIXTURE = FIXTURE_DIR / "sample_flow_snapshot.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _all_required_tables() -> set[str]:
    return set(REQUIRED_INGEST_TABLES) | set(REQUIRED_SUPPORT_TABLES)


def _full_universe_members() -> dict[str, dict[str, Any]]:
    return {
        "HYPE": {"ffg_universe_member_id": 1, "asset_id": 101},
        "XLM": {"ffg_universe_member_id": 2, "asset_id": 102},
        "XPL": {"ffg_universe_member_id": 3, "asset_id": 103},
        "BTC": {"ffg_universe_member_id": 4, "asset_id": 104},
        "ETH": {"ffg_universe_member_id": 5, "asset_id": 105},
    }


class RecordingCursor:
    def __init__(self, conn: "RecordingConnection") -> None:
        self.conn = conn
        self._results: list[dict[str, Any]] = []
        self.lastrowid = 0

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        normalized_sql = " ".join(sql.split())
        self.conn.statements.append((normalized_sql, params))
        self.lastrowid = 0

        if (
            self.conn.fail_on_sql_contains is not None
            and self.conn.fail_on_sql_contains in normalized_sql
        ):
            raise RuntimeError(f"simulated db failure for {self.conn.fail_on_sql_contains}")

        if "SELECT table_name FROM information_schema.tables" in normalized_sql:
            self._results = [{"table_name": table_name} for table_name in sorted(self.conn.present_tables)]
            return

        if "SELECT artifact_id, source_name, content_sha256 FROM external_research_artifact" in normalized_sql:
            _source_name, content_sha256 = params
            row = self.conn.artifacts_by_sha.get(str(content_sha256))
            self._results = [] if row is None else [row]
            return

        if "SELECT source_symbol, ffg_universe_member_id, asset_id FROM ffg_research_universe_member_v1" in normalized_sql:
            symbols = [str(symbol).upper() for symbol in params[1:]]
            self._results = []
            for symbol in symbols:
                row = self.conn.ffg_universe_members.get(symbol)
                if row is not None:
                    self._results.append(
                        {
                            "source_symbol": symbol,
                            "ffg_universe_member_id": row["ffg_universe_member_id"],
                            "asset_id": row["asset_id"],
                        }
                    )
            return

        if "INSERT INTO external_research_artifact" in normalized_sql:
            self.conn.stage_for_rollback()
            artifact_id = self.conn.next_artifact_id
            self.conn.next_artifact_id += 1
            row = {
                "artifact_id": artifact_id,
                "source_name": params[0],
                "artifact_kind": params[1],
                "original_filename": params[2],
                "content_sha256": params[3],
                "raw_content": params[4],
                "source_observed_label": params[5],
                "source_observed_at_utc": params[6],
                "parser_version": params[7],
                "parse_status": params[8],
                "parse_warning_json": params[9],
            }
            self.conn.artifacts_by_sha[row["content_sha256"]] = row
            self.lastrowid = artifact_id
            self._results = []
            return

        if "INSERT INTO external_research_flow_snapshot" in normalized_sql:
            self.conn.stage_for_rollback()
            snapshot_id = self.conn.next_snapshot_id
            self.conn.next_snapshot_id += 1
            row = {
                "snapshot_id": snapshot_id,
                "artifact_id": params[0],
                "source_name": params[1],
                "universe_key": params[2],
                "list_scope": params[3],
                "normalized_timeframe": params[4],
                "source_confidence": params[5],
                "source_status": params[6],
                "reported_inflow_count": params[7],
                "parsed_inflow_count": params[8],
                "reported_outflow_count": params[9],
                "parsed_outflow_count": params[10],
            }
            self.conn.snapshots_by_id[snapshot_id] = row
            self.lastrowid = snapshot_id
            self._results = []
            return

        if "INSERT INTO external_research_flow_observation" in normalized_sql:
            self.conn.stage_for_rollback()
            observation_id = self.conn.next_observation_id
            self.conn.next_observation_id += 1
            row = {
                "observation_id": observation_id,
                "snapshot_id": params[0],
                "source_symbol": params[1],
                "raw_display_name": params[2],
                "direction": params[3],
                "change_pct": params[4],
                "reported_flow_usd": params[5],
                "rank_in_section": params[6],
                "peak_flag": params[7],
                "active_alert_flag": params[8],
                "identity_status": params[9],
                "ffg_universe_member_id": params[10],
                "asset_id": params[11],
            }
            self.conn.observations_by_id[observation_id] = row
            self.lastrowid = observation_id
            self._results = []
            return

        self._results = []

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._results)

    def fetchone(self) -> dict[str, Any] | None:
        return None if not self._results else self._results[0]


class RecordingConnection:
    def __init__(
        self,
        *,
        present_tables: set[str] | None = None,
        ffg_universe_members: dict[str, dict[str, Any]] | None = None,
        fail_on_sql_contains: str | None = None,
    ) -> None:
        self.present_tables = present_tables if present_tables is not None else _all_required_tables()
        self.ffg_universe_members = ffg_universe_members or {}
        self.artifacts_by_sha: dict[str, dict[str, Any]] = {}
        self.snapshots_by_id: dict[int, dict[str, Any]] = {}
        self.observations_by_id: dict[int, dict[str, Any]] = {}
        self.next_artifact_id = 1
        self.next_snapshot_id = 1
        self.next_observation_id = 1
        self.fail_on_sql_contains = fail_on_sql_contains
        self.statements: list[tuple[str, Any]] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0
        self._rollback_state: dict[str, Any] | None = None

    def cursor(self) -> RecordingCursor:
        return RecordingCursor(self)

    def commit(self) -> None:
        self.commit_count += 1
        self._rollback_state = None

    def rollback(self) -> None:
        self.rollback_count += 1
        if self._rollback_state is None:
            return
        self.artifacts_by_sha = copy.deepcopy(self._rollback_state["artifacts_by_sha"])
        self.snapshots_by_id = copy.deepcopy(self._rollback_state["snapshots_by_id"])
        self.observations_by_id = copy.deepcopy(self._rollback_state["observations_by_id"])
        self.next_artifact_id = self._rollback_state["next_artifact_id"]
        self.next_snapshot_id = self._rollback_state["next_snapshot_id"]
        self.next_observation_id = self._rollback_state["next_observation_id"]
        self._rollback_state = None

    def close(self) -> None:
        self.close_count += 1

    def stage_for_rollback(self) -> None:
        if self._rollback_state is None:
            self._rollback_state = {
                "artifacts_by_sha": copy.deepcopy(self.artifacts_by_sha),
                "snapshots_by_id": copy.deepcopy(self.snapshots_by_id),
                "observations_by_id": copy.deepcopy(self.observations_by_id),
                "next_artifact_id": self.next_artifact_id,
                "next_snapshot_id": self.next_snapshot_id,
                "next_observation_id": self.next_observation_id,
            }


def _ffg_scope_tuples(parsed) -> list[tuple[Any, ...]]:
    for scope in parsed.scopes:
        if scope.list_scope == LIST_SCOPE_FFG:
            return [
                (
                    row.direction,
                    row.source_symbol,
                    row.raw_display_name,
                    None if row.change_pct is None else str(row.change_pct),
                    None if row.reported_flow_usd is None else str(row.reported_flow_usd),
                    row.rank_in_section,
                    row.peak_flag,
                    row.active_alert_flag,
                )
                for row in scope.observations
            ]
    return []


class TestParsing:
    def test_html_and_text_parse_same_representative_ffg_list_observations(self) -> None:
        parsed_text = parse_artifact(_read(TEXT_FIXTURE), ARTIFACT_KIND_TEXT)
        parsed_html = parse_artifact(_read(HTML_FIXTURE), ARTIFACT_KIND_HTML)

        assert _ffg_scope_tuples(parsed_text) == _ffg_scope_tuples(parsed_html)

    def test_ffg_list_and_outside_radar_become_separate_snapshots(self) -> None:
        conn = RecordingConnection(ffg_universe_members=_full_universe_members())
        parsed = parse_artifact(_read(TEXT_FIXTURE), ARTIFACT_KIND_TEXT)

        plan = build_ingest_plan(
            conn,
            path=TEXT_FIXTURE,
            parsed_artifact=parsed,
            source_observed_at_utc=None,
            source_observed_label_override=None,
        )

        assert [snapshot.list_scope for snapshot in plan.snapshot_plans] == [LIST_SCOPE_FFG, LIST_SCOPE_OUTSIDE]

    def test_duplicate_source_symbol_in_one_snapshot_fails_before_db_write(self, tmp_path: Path) -> None:
        duplicate_path = tmp_path / "duplicate_snapshot.txt"
        duplicate_path.write_text(
            _read(TEXT_FIXTURE).replace(
                "3 | XPL | Plasma | +131.8% | $364.7M | ALERT",
                "3 | HYPE | Hyperliquid copy | +131.8% | $364.7M | ALERT",
            ),
            encoding="utf-8",
        )
        stdout = StringIO()

        with patch("src.research.run_ffg_flow_snapshot_ingest.get_connection", side_effect=AssertionError("DB must stay closed")), \
             patch("sys.argv", ["ffg_flow_ingest", "--artifact-file", str(duplicate_path), "--dry-run"]), \
             patch("sys.stdout", stdout):
            result = main()

        assert result == EXIT_CODE_EXPECTED_FAILURE
        output = stdout.getvalue()
        assert "reason=DUPLICATE_SYMBOL" in output
        assert "Traceback" not in output


class TestDbPlan:
    def test_reported_count_differs_from_parsed_stores_warning_and_does_not_fail(self) -> None:
        conn = RecordingConnection(ffg_universe_members=_full_universe_members())
        stdout = StringIO()

        with patch("src.research.run_ffg_flow_snapshot_ingest.get_connection", return_value=conn), \
             patch("sys.argv", ["ffg_flow_ingest", "--artifact-file", str(TEXT_FIXTURE), "--write-db"]), \
             patch("sys.stdout", stdout):
            result = main()

        assert result == 0
        artifact = next(iter(conn.artifacts_by_sha.values()))
        assert artifact["parse_status"] == PARSE_STATUS_WARNINGS
        warnings = json.loads(artifact["parse_warning_json"])
        assert any(
            warning["code"] == "REPORTED_COUNT_MISMATCH"
            and warning["list_scope"] == LIST_SCOPE_FFG
            and warning["direction"] == "INFLOW"
            for warning in warnings
        )

    def test_ffg_list_xpl_resolves_through_exact_ffg_universe_match(self) -> None:
        conn = RecordingConnection(
            ffg_universe_members={
                "HYPE": {"ffg_universe_member_id": 1, "asset_id": 101},
                "XLM": {"ffg_universe_member_id": 2, "asset_id": 102},
                "XPL": {"ffg_universe_member_id": 3, "asset_id": 103},
                "BTC": {"ffg_universe_member_id": 4, "asset_id": 104},
                "ETH": {"ffg_universe_member_id": 5, "asset_id": 105},
            }
        )
        parsed = parse_artifact(_read(TEXT_FIXTURE), ARTIFACT_KIND_TEXT)

        plan = build_ingest_plan(
            conn,
            path=TEXT_FIXTURE,
            parsed_artifact=parsed,
            source_observed_at_utc=None,
            source_observed_label_override=None,
        )

        ffg_rows = next(snapshot for snapshot in plan.snapshot_plans if snapshot.list_scope == LIST_SCOPE_FFG).observations
        xpl_row = next(row for row in ffg_rows if row.source_symbol == "XPL")
        assert xpl_row.identity_status == "FFG_UNIVERSE_RESOLVED"
        assert xpl_row.ffg_universe_member_id == 3
        assert xpl_row.asset_id == 103

    def test_parsed_ffg_list_lit_observation_resolves_to_expected_member_and_asset(self, tmp_path: Path) -> None:
        lit_path = tmp_path / "lit_flow_snapshot.txt"
        lit_path.write_text(
            _read(TEXT_FIXTURE).replace(
                "3 | XPL | Plasma | +131.8% | $364.7M | ALERT",
                "3 | LIT | Lighter | +131.8% | $364.7M | ALERT",
            ),
            encoding="utf-8",
        )
        conn = RecordingConnection(
            ffg_universe_members={
                "HYPE": {"ffg_universe_member_id": 1, "asset_id": 101},
                "XLM": {"ffg_universe_member_id": 2, "asset_id": 102},
                "LIT": {"ffg_universe_member_id": 6, "asset_id": 106},
                "BTC": {"ffg_universe_member_id": 4, "asset_id": 104},
                "ETH": {"ffg_universe_member_id": 5, "asset_id": 105},
            }
        )
        parsed = parse_artifact(_read(lit_path), ARTIFACT_KIND_TEXT)

        plan = build_ingest_plan(
            conn,
            path=lit_path,
            parsed_artifact=parsed,
            source_observed_at_utc=None,
            source_observed_label_override=None,
        )

        ffg_rows = next(snapshot for snapshot in plan.snapshot_plans if snapshot.list_scope == LIST_SCOPE_FFG).observations
        lit_row = next(row for row in ffg_rows if row.source_symbol == "LIT")
        assert lit_row.identity_status == "FFG_UNIVERSE_RESOLVED"
        assert lit_row.ffg_universe_member_id == 6
        assert lit_row.asset_id == 106

    def test_outside_radar_symbols_create_no_asset_market_account_or_universe_rows(self) -> None:
        conn = RecordingConnection(ffg_universe_members=_full_universe_members())

        with patch("src.research.run_ffg_flow_snapshot_ingest.get_connection", return_value=conn), \
             patch("sys.argv", ["ffg_flow_ingest", "--artifact-file", str(TEXT_FIXTURE), "--write-db"]):
            result = main()

        assert result == 0
        outside_snapshot_ids = [
            snapshot_id
            for snapshot_id, row in conn.snapshots_by_id.items()
            if row["list_scope"] == LIST_SCOPE_OUTSIDE
        ]
        outside_rows = [
            row
            for row in conn.observations_by_id.values()
            if row["snapshot_id"] in outside_snapshot_ids
        ]
        assert outside_rows
        assert all(row["identity_status"] == "OUTSIDE_RADAR_UNRESOLVED" for row in outside_rows)
        assert all(row["ffg_universe_member_id"] is None for row in outside_rows)
        assert all(row["asset_id"] is None for row in outside_rows)


class TestCliModes:
    def test_validate_only_never_opens_db(self) -> None:
        with patch("src.research.run_ffg_flow_snapshot_ingest.get_connection", side_effect=AssertionError("DB must stay closed")), \
             patch("sys.argv", ["ffg_flow_ingest", "--artifact-file", str(TEXT_FIXTURE), "--validate-only"]):
            result = main()

        assert result == 0

    def test_dry_run_performs_no_writes(self) -> None:
        conn = RecordingConnection(ffg_universe_members=_full_universe_members())

        with patch("src.research.run_ffg_flow_snapshot_ingest.get_connection", return_value=conn), \
             patch("sys.argv", ["ffg_flow_ingest", "--artifact-file", str(TEXT_FIXTURE), "--dry-run"]):
            result = main()

        assert result == 0
        assert conn.commit_count == 0
        write_statements = [
            sql for sql, _params in conn.statements
            if sql.startswith("INSERT") or sql.startswith("DELETE") or sql.startswith("UPDATE")
        ]
        assert not write_statements

    def test_write_db_is_transactional_and_append_only_for_distinct_content_hashes(self, tmp_path: Path) -> None:
        conn = RecordingConnection(ffg_universe_members=_full_universe_members())
        second_path = tmp_path / "sample_flow_snapshot_copy.txt"
        second_path.write_text(_read(TEXT_FIXTURE) + "\nSaved copy id: 2\n", encoding="utf-8")

        with patch("src.research.run_ffg_flow_snapshot_ingest.get_connection", return_value=conn), \
             patch("sys.argv", ["ffg_flow_ingest", "--artifact-file", str(TEXT_FIXTURE), "--write-db"]):
            first_result = main()

        with patch("src.research.run_ffg_flow_snapshot_ingest.get_connection", return_value=conn), \
             patch("sys.argv", ["ffg_flow_ingest", "--artifact-file", str(second_path), "--write-db"]):
            second_result = main()

        assert first_result == 0
        assert second_result == 0
        assert conn.commit_count == 2
        assert len(conn.artifacts_by_sha) == 2
        assert len(conn.snapshots_by_id) == 4
        assert len(conn.observations_by_id) == 16
        assert conn.rollback_count == 0

    def test_exact_repeated_artifact_is_idempotent(self) -> None:
        conn = RecordingConnection(ffg_universe_members=_full_universe_members())

        with patch("src.research.run_ffg_flow_snapshot_ingest.get_connection", return_value=conn), \
             patch("sys.argv", ["ffg_flow_ingest", "--artifact-file", str(TEXT_FIXTURE), "--write-db"]):
            first_result = main()

        with patch("src.research.run_ffg_flow_snapshot_ingest.get_connection", return_value=conn), \
             patch("sys.argv", ["ffg_flow_ingest", "--artifact-file", str(TEXT_FIXTURE), "--write-db"]):
            second_result = main()

        assert first_result == 0
        assert second_result == 0
        assert len(conn.artifacts_by_sha) == 1
        assert len(conn.snapshots_by_id) == 2
        assert len(conn.observations_by_id) == 8

    def test_write_db_rolls_back_partial_state_on_unexpected_db_failure(self) -> None:
        conn = RecordingConnection(
            ffg_universe_members=_full_universe_members(),
            fail_on_sql_contains="INSERT INTO external_research_flow_snapshot",
        )
        stdout = StringIO()

        with patch("src.research.run_ffg_flow_snapshot_ingest.get_connection", return_value=conn), \
             patch("sys.argv", ["ffg_flow_ingest", "--artifact-file", str(TEXT_FIXTURE), "--write-db"]), \
             patch("sys.stdout", stdout):
            result = main()

        assert result == EXIT_CODE_UNEXPECTED_FAILURE
        assert conn.rollback_count == 1
        assert conn.commit_count == 0
        assert conn.artifacts_by_sha == {}
        assert conn.snapshots_by_id == {}
        assert conn.observations_by_id == {}
        assert "FAILED run_ffg_flow_snapshot_ingest reason=UNEXPECTED_ERROR detail=RuntimeError" in stdout.getvalue()


class TestSqlBoundaries:
    def test_no_sql_writes_target_asset_account_or_runtime_tables(self) -> None:
        conn = RecordingConnection(ffg_universe_members=_full_universe_members())

        with patch("src.research.run_ffg_flow_snapshot_ingest.get_connection", return_value=conn), \
             patch("sys.argv", ["ffg_flow_ingest", "--artifact-file", str(TEXT_FIXTURE), "--write-db"]):
            result = main()

        assert result == 0
        forbidden_targets = (
            " asset ",
            "account_asset",
            "selection",
            "decision",
            "order",
            "broker",
            "execution",
            "profit_plan",
            "venue_market",
        )
        write_statements = [
            sql.lower()
            for sql, _params in conn.statements
            if sql.startswith("INSERT") or sql.startswith("DELETE") or sql.startswith("UPDATE")
        ]
        assert write_statements
        assert all(
            "external_research_artifact" in sql
            or "external_research_flow_snapshot" in sql
            or "external_research_flow_observation" in sql
            for sql in write_statements
        )
        assert not any(target in sql for sql in write_statements for target in forbidden_targets)
