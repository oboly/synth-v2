from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterator

import pytest

from src.execution.live_prerequisites_v1 import (
    LiveExecutionPrerequisitesUnavailable,
)
from src.executor.executor_v1 import execute_plan_paper
from src.executor.models import ExecutionPlanRow
from src.executor.paper_contract_v1 import PaperExecutorContractError
from src.executor.repository import ExecutorRepository


DISPOSABLE_OPT_IN = "SYNTH_RUN_DISPOSABLE_MARIADB_EXECUTOR_TESTS"


def _require_disposable_mariadb() -> None:
    if os.getenv(DISPOSABLE_OPT_IN) != "1":
        pytest.skip(f"Set {DISPOSABLE_OPT_IN}=1 only for disposable MariaDB.")
    database = os.getenv("DB_NAME") or os.getenv("MYSQL_DATABASE") or ""
    host = os.getenv("DB_HOST") or os.getenv("MYSQL_HOST") or ""
    password = os.getenv("DB_PASSWORD") or os.getenv("MYSQL_PASSWORD") or ""
    if database not in {"", "information_schema"}:
        pytest.fail("executor test refuses a configured application database")
    if host not in {"127.0.0.1", "localhost"}:
        pytest.fail("executor test refuses a non-local MariaDB host")
    if "disposable" not in password.lower():
        pytest.fail("executor test password must contain the disposable marker")


def _apply(conn: Any, statements: list[str]) -> None:
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    conn.commit()


def _create_schema(conn: Any) -> None:
    _apply(
        conn,
        [
            """
            CREATE TABLE asset (
                asset_id BIGINT UNSIGNED NOT NULL,
                symbol VARCHAR(16) NOT NULL,
                PRIMARY KEY (asset_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE execution_plan (
                execution_plan_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                account_id BIGINT UNSIGNED NOT NULL,
                trading_account_id BIGINT UNSIGNED NULL,
                asset_id BIGINT UNSIGNED NOT NULL,
                sleeve_code VARCHAR(32) NOT NULL,
                venue VARCHAR(32) NOT NULL,
                market VARCHAR(32) NULL,
                side VARCHAR(16) NOT NULL,
                desired_action VARCHAR(64) NOT NULL,
                execution_intent VARCHAR(64) NULL,
                action_type VARCHAR(64) NULL,
                requested_side VARCHAR(16) NULL,
                execution_mode VARCHAR(32) NULL,
                plan_ts_utc DATETIME(6) NOT NULL,
                valid_until_ts_utc DATETIME(6) NULL,
                target_fraction DECIMAL(18,8) NOT NULL,
                max_notional_eur DECIMAL(18,8) NULL,
                reference_price_eur DECIMAL(18,8) NULL,
                passive_price_eur DECIMAL(18,8) NULL,
                urgent_limit_price_eur DECIMAL(18,8) NULL,
                max_reprices INT NOT NULL,
                max_wait_seconds INT NOT NULL,
                max_chase_bps DECIMAL(18,8) NOT NULL,
                min_spread_bps_for_capture DECIMAL(18,8) NOT NULL,
                escalation_to_urgent_limit TINYINT(1) NOT NULL,
                abort_if_signal_invalidates TINYINT(1) NOT NULL,
                plan_state VARCHAR(32) NOT NULL,
                notes TEXT NULL,
                updated_ts_utc DATETIME(6) NULL,
                PRIMARY KEY (execution_plan_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE obs_market_candle (
                observation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                asset_id BIGINT UNSIGNED NOT NULL,
                venue VARCHAR(32) NOT NULL,
                interval_code VARCHAR(16) NOT NULL,
                close_ts_utc DATETIME(6) NOT NULL,
                close_price DECIMAL(18,8) NOT NULL,
                PRIMARY KEY (observation_id)
            ) ENGINE=InnoDB
            """,
            """
            CREATE TABLE capital_reservation (
                capital_reservation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                execution_plan_id BIGINT UNSIGNED NOT NULL,
                account_id BIGINT UNSIGNED NOT NULL,
                sleeve_code VARCHAR(32) NOT NULL,
                asset_id BIGINT UNSIGNED NOT NULL,
                reserved_amount_eur DECIMAL(18,8) NOT NULL,
                reservation_state VARCHAR(32) NOT NULL,
                released_ts_utc DATETIME(6) NULL,
                updated_ts_utc DATETIME(6) NULL,
                PRIMARY KEY (capital_reservation_id)
            ) ENGINE=InnoDB
            """,
            """
            CREATE TABLE portfolio_position (
                portfolio_position_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                account_id BIGINT UNSIGNED NOT NULL,
                sleeve_code VARCHAR(32) NOT NULL,
                asset_id BIGINT UNSIGNED NOT NULL,
                venue VARCHAR(32) NOT NULL,
                position_side VARCHAR(16) NOT NULL,
                qty DECIMAL(28,12) NOT NULL,
                avg_entry_price DECIMAL(18,8) NULL,
                mark_price DECIMAL(18,8) NULL,
                market_value_eur DECIMAL(18,8) NOT NULL,
                realized_pnl_eur DECIMAL(18,8) NOT NULL,
                unrealized_pnl_eur DECIMAL(18,8) NOT NULL,
                position_status VARCHAR(32) NOT NULL,
                opened_ts_utc DATETIME(6) NULL,
                updated_ts_utc DATETIME(6) NULL,
                PRIMARY KEY (portfolio_position_id),
                UNIQUE KEY uq_position (account_id, sleeve_code, asset_id, venue)
            ) ENGINE=InnoDB
            """,
            """
            CREATE TABLE portfolio_sleeve (
                account_id BIGINT UNSIGNED NOT NULL,
                sleeve_code VARCHAR(32) NOT NULL,
                reserved_equity_eur DECIMAL(18,8) NOT NULL,
                deployed_equity_eur DECIMAL(18,8) NOT NULL,
                available_equity_eur DECIMAL(18,8) NOT NULL,
                updated_ts_utc DATETIME(6) NULL,
                PRIMARY KEY (account_id, sleeve_code)
            ) ENGINE=InnoDB
            """,
            """
            CREATE TABLE execution_event (
                execution_event_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                execution_plan_id BIGINT UNSIGNED NOT NULL,
                account_id BIGINT UNSIGNED NOT NULL,
                asset_id BIGINT UNSIGNED NOT NULL,
                sleeve_code VARCHAR(32) NOT NULL,
                event_ts_utc DATETIME(6) NOT NULL,
                event_type VARCHAR(64) NOT NULL,
                event_reason VARCHAR(128) NULL,
                side VARCHAR(16) NULL,
                price DECIMAL(18,8) NULL,
                qty DECIMAL(28,12) NULL,
                fill_qty DECIMAL(28,12) NULL,
                fill_price DECIMAL(18,8) NULL,
                notes TEXT NULL,
                PRIMARY KEY (execution_event_id)
            ) ENGINE=InnoDB
            """,
            "INSERT INTO asset (asset_id, symbol) VALUES (3, 'BTC')",
            """
            INSERT INTO obs_market_candle (
                asset_id, venue, interval_code, close_ts_utc, close_price
            ) VALUES (3, 'bitvavo', '1h', UTC_TIMESTAMP(6), 100)
            """,
        ],
    )


@contextmanager
def _repository_schema() -> Iterator[tuple[ExecutorRepository, Any]]:
    from src.common.db import get_connection

    _require_disposable_mariadb()
    name = f"synth_executor_{uuid.uuid4().hex[:12]}"
    admin = get_connection(database="information_schema")
    try:
        with admin.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_unicode_ci"
            )
        admin.commit()
    finally:
        admin.close()

    control = get_connection(database=name)
    try:
        _create_schema(control)
        yield ExecutorRepository(
            connection_factory=lambda: get_connection(database=name)
        ), control
    finally:
        control.close()
        admin = get_connection(database="information_schema")
        try:
            with admin.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
            admin.commit()
        finally:
            admin.close()


def _insert_plan(conn: Any, **overrides: object) -> int:
    values: dict[str, object] = {
        "account_id": 7,
        "trading_account_id": 19,
        "asset_id": 3,
        "sleeve_code": "CORE",
        "venue": "bitvavo",
        "market": "BTC-EUR",
        "side": "BUY",
        "desired_action": "SPREAD_CAPTURE_PASSIVE",
        "execution_intent": "PLACE_PASSIVE_LIMIT",
        "action_type": "PLACE_ORDER",
        "requested_side": "BUY",
        "execution_mode": "PAPER",
        "plan_state": "IDLE",
    }
    values.update(overrides)
    columns = list(values)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO execution_plan (
                {', '.join(columns)}, plan_ts_utc, target_fraction,
                max_notional_eur, reference_price_eur, max_reprices,
                max_wait_seconds, max_chase_bps,
                min_spread_bps_for_capture, escalation_to_urgent_limit,
                abort_if_signal_invalidates, notes
            ) VALUES (
                {', '.join(['%s'] * len(columns))}, UTC_TIMESTAMP(6), 0.1,
                25, 100, 2, 60, 10, 1, 0, 1, 'test'
            )
            """,
            list(values.values()),
        )
        plan_id = int(cur.lastrowid)
    conn.commit()
    return plan_id


def _model(plan_id: int, **overrides: object) -> ExecutionPlanRow:
    values: dict[str, object] = {
        "execution_plan_id": plan_id,
        "account_id": 7,
        "trading_account_id": 19,
        "asset_id": 3,
        "asset_symbol": "BTC",
        "sleeve_code": "CORE",
        "venue": "bitvavo",
        "market": "BTC-EUR",
        "side": "BUY",
        "desired_action": "SPREAD_CAPTURE_PASSIVE",
        "execution_intent": "PLACE_PASSIVE_LIMIT",
        "action_type": "PLACE_ORDER",
        "requested_side": "BUY",
        "execution_mode": "PAPER",
        "plan_ts_utc": datetime(2026, 7, 21, 12, 0, 0),
        "valid_until_ts_utc": None,
        "target_fraction": Decimal("0.1"),
        "max_notional_eur": Decimal("25"),
        "reference_price_eur": Decimal("100"),
        "passive_price_eur": None,
        "urgent_limit_price_eur": None,
        "max_reprices": 2,
        "max_wait_seconds": 60,
        "max_chase_bps": Decimal("10"),
        "min_spread_bps_for_capture": Decimal("1"),
        "escalation_to_urgent_limit": False,
        "abort_if_signal_invalidates": True,
        "plan_state": "IDLE",
        "notes": "test",
    }
    values.update(overrides)
    return ExecutionPlanRow(**values)  # type: ignore[arg-type]


def _counts_and_accounting(conn: Any) -> dict[str, object]:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM execution_event")
        events = int(cur.fetchone()["n"])
        cur.execute(
            "SELECT reservation_state FROM capital_reservation "
            "ORDER BY capital_reservation_id"
        )
        reservations = tuple(row["reservation_state"] for row in cur.fetchall())
        cur.execute(
            "SELECT sleeve_code, reserved_equity_eur, deployed_equity_eur, "
            "available_equity_eur FROM portfolio_sleeve ORDER BY sleeve_code"
        )
        sleeves = tuple(tuple(row.values()) for row in cur.fetchall())
        cur.execute(
            "SELECT sleeve_code, qty, market_value_eur, position_status "
            "FROM portfolio_position ORDER BY sleeve_code"
        )
        positions = tuple(tuple(row.values()) for row in cur.fetchall())
    return {
        "events": events,
        "reservations": reservations,
        "sleeves": sleeves,
        "positions": positions,
    }


def test_fetch_open_plans_requires_exact_canonical_contract() -> None:
    with _repository_schema() as (repo, conn):
        passive_buy = _insert_plan(conn)
        passive_sell = _insert_plan(conn, side="SELL", requested_side="SELL")
        close_sell = _insert_plan(
            conn,
            sleeve_code="SWING",
            side="SELL",
            requested_side="SELL",
            desired_action="CLOSE_POSITION_MARKET_PAPER",
            execution_intent="CLOSE_POSITION_MARKET_PAPER",
        )
        for mode in ("LIVE", "paper", "Paper", "live", "Live", "unknown", ""):
            _insert_plan(conn, execution_mode=mode)
        _insert_plan(conn, execution_mode=None)
        for action_type in ("place_order", "Place_Order"):
            _insert_plan(conn, action_type=action_type)
        for intent in ("place_passive_limit", "Place_Passive_Limit", "WRONG"):
            _insert_plan(conn, execution_intent=intent)
        for side in ("buy", "Buy"):
            _insert_plan(conn, side=side, requested_side=side)
        for side in ("sell", "Sell"):
            _insert_plan(conn, side=side, requested_side=side)
        _insert_plan(conn, side="SELL", requested_side="BUY")
        _insert_plan(conn, market="btc-eur")
        _insert_plan(conn, market="Btc-Eur")
        _insert_plan(conn, venue="BITVAVO")
        _insert_plan(conn, desired_action="ENTER")
        _insert_plan(conn, desired_action="ENTER_LONG")
        _insert_plan(
            conn, desired_action="PREPARE_PLAN", execution_intent="PREPARE_PLAN"
        )
        _insert_plan(
            conn,
            desired_action="CLOSE_POSITION_MARKET_PAPER",
            execution_intent="CLOSE_POSITION_MARKET_PAPER",
            side="BUY",
            requested_side="BUY",
        )
        _insert_plan(conn, plan_state="PLACED")

        plans = repo.fetch_open_plans(limit=100)
        assert [plan.execution_plan_id for plan in plans] == [
            passive_buy,
            passive_sell,
            close_sell,
        ]
        assert all(plan.trading_account_id == 19 for plan in plans)
        assert all(plan.market == "BTC-EUR" for plan in plans)
        assert all(plan.action_type == "PLACE_ORDER" for plan in plans)
        assert repo.fetch_open_plans(venue="BITVAVO", limit=100) == []
        assert len(repo.fetch_open_plans(venue="bitvavo", limit=100)) == 3


def test_live_rows_are_query_excluded_and_direct_calls_cross_no_boundary() -> None:
    with _repository_schema() as (repo, conn):
        live_ids = [
            _insert_plan(
                conn,
                execution_mode="LIVE",
                side=side,
                requested_side=side,
            )
            for side in ("BUY", "SELL")
        ]
        assert repo.fetch_open_plans(limit=100) == []

        class TrackingRepository(ExecutorRepository):
            def __init__(self) -> None:
                super().__init__(connection_factory=repo.connection_factory)
                self.price_lookups = 0
                self.fill_calls = 0

            def fetch_latest_price_eur(self, **kwargs: object) -> Decimal | None:
                self.price_lookups += 1
                return super().fetch_latest_price_eur(**kwargs)  # type: ignore[arg-type]

            def fill_passive_plan_paper(self, **kwargs: object) -> tuple[Decimal, bool]:
                self.fill_calls += 1
                return super().fill_passive_plan_paper(**kwargs)  # type: ignore[arg-type]

        tracking_repo = TrackingRepository()
        for plan_id, side in zip(live_ids, ("BUY", "SELL"), strict=True):
            with pytest.raises(LiveExecutionPrerequisitesUnavailable):
                execute_plan_paper(
                    _model(
                        plan_id,
                        execution_mode="LIVE",
                        side=side,
                        requested_side=side,
                    ),
                    tracking_repo,
                )
        assert tracking_repo.price_lookups == 0
        assert tracking_repo.fill_calls == 0
        assert _counts_and_accounting(conn)["events"] == 0
        with conn.cursor() as cur:
            cur.execute("SELECT plan_state FROM execution_plan ORDER BY execution_plan_id")
            assert [row["plan_state"] for row in cur.fetchall()] == ["IDLE", "IDLE"]


def _seed_accounting(conn: Any, passive_id: int, close_id: int) -> None:
    _apply(
        conn,
        [
            f"""
            INSERT INTO capital_reservation (
                execution_plan_id, account_id, sleeve_code, asset_id,
                reserved_amount_eur, reservation_state
            ) VALUES ({passive_id}, 7, 'CORE', 3, 25, 'ACTIVE')
            """,
            """
            INSERT INTO portfolio_sleeve (
                account_id, sleeve_code, reserved_equity_eur,
                deployed_equity_eur, available_equity_eur
            ) VALUES
                (7, 'CORE', 25, 0, 75),
                (7, 'SWING', 0, 25, 75)
            """,
            """
            INSERT INTO portfolio_position (
                account_id, sleeve_code, asset_id, venue, position_side,
                qty, avg_entry_price, mark_price, market_value_eur,
                realized_pnl_eur, unrealized_pnl_eur, position_status,
                opened_ts_utc
            ) VALUES (
                7, 'SWING', 3, 'bitvavo', 'LONG', 0.25, 90, 100, 25,
                0, 2.5, 'OPEN', UTC_TIMESTAMP(6)
            )
            """,
        ],
    )


def test_supported_mappings_execute_through_real_repository_boundary() -> None:
    with _repository_schema() as (repo, conn):
        passive_id = _insert_plan(conn)
        close_id = _insert_plan(
            conn,
            sleeve_code="SWING",
            side="SELL",
            requested_side="SELL",
            desired_action="CLOSE_POSITION_MARKET_PAPER",
            execution_intent="CLOSE_POSITION_MARKET_PAPER",
        )
        _seed_accounting(conn, passive_id, close_id)

        results = [execute_plan_paper(plan, repo) for plan in repo.fetch_open_plans()]
        assert [result.event_type for result in results] == [
            "PAPER_FILL_PASSIVE",
            "PAPER_FILL_CLOSE",
        ]
        with conn.cursor() as cur:
            cur.execute("SELECT plan_state FROM execution_plan ORDER BY execution_plan_id")
            assert [row["plan_state"] for row in cur.fetchall()] == ["FILLED", "FILLED"]
            cur.execute("SELECT event_type FROM execution_event ORDER BY execution_event_id")
            assert [row["event_type"] for row in cur.fetchall()] == [
                "PAPER_FILL_PASSIVE",
                "PAPER_FILL_CLOSE",
            ]


def test_both_fill_transactions_revalidate_every_persisted_contract_field() -> None:
    with _repository_schema() as (repo, conn):
        passive_id = _insert_plan(conn)
        close_id = _insert_plan(
            conn,
            sleeve_code="SWING",
            side="SELL",
            requested_side="SELL",
            desired_action="CLOSE_POSITION_MARKET_PAPER",
            execution_intent="CLOSE_POSITION_MARKET_PAPER",
        )
        _seed_accounting(conn, passive_id, close_id)
        plans = {plan.execution_plan_id: plan for plan in repo.fetch_open_plans()}
        baseline = _counts_and_accounting(conn)

        races = (
            ("execution_mode", "LIVE"),
            ("execution_intent", "WRONG_INTENT"),
            ("action_type", "place_order"),
            ("requested_side", "buy"),
            ("venue", "BITVAVO"),
            ("venue", "other"),
            ("venue", None),
            ("market", "btc-eur"),
            ("side", "buy"),
            ("plan_state", "FILLED"),
        )
        for plan_id, fill_name in (
            (passive_id, "fill_passive_plan_paper"),
            (close_id, "fill_close_position_market_paper"),
        ):
            plan = plans[plan_id]
            for field_name, changed_value in races:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE execution_plan SET {field_name} = %s "
                        "WHERE execution_plan_id = %s",
                        [changed_value, plan_id],
                    )
                conn.commit()

                fill = getattr(repo, fill_name)
                expected_error = (
                    LiveExecutionPrerequisitesUnavailable
                    if field_name == "execution_mode"
                    else PaperExecutorContractError
                )
                with pytest.raises(expected_error):
                    fill(plan=plan, fill_price_eur=Decimal("100"))

                assert _counts_and_accounting(conn) == baseline
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE execution_plan SET {field_name} = %s "
                        "WHERE execution_plan_id = %s",
                        [getattr(plan, field_name), plan_id],
                    )
                conn.commit()
