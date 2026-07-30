from __future__ import annotations

"""Integration tests: terminal-transition target-event atomicity (P1 fix).

These exercise `evaluate_scope` directly against a small purpose-built fake
connection, proving that a candle which both reaches/passes the final
canonical target level AND completes the map appends the target event and
the terminal COMPLETED lifecycle event in the same transaction, in the
correct order, exactly once, with no dependency on any later manual runner.
"""

import pytest as _pytest_authz


@_pytest_authz.fixture(autouse=True)
def _authorized_writer_context(monkeypatch):
    from tests.writer_auth_support import install_authorized_writer_context
    install_authorized_writer_context(monkeypatch)


import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.market_data.native_short_fib_context_v1 import (
    PRIMARY_LIFECYCLE_COMPLETED,
    STATUS_AVAILABLE,
    NativeShortContextRow,
)
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey
from src.market_data.native_short_map_materializer_v1 import ScopeMaterializationResult
from src.market_data.native_short_scope_status_materializer_v1 import evaluate_scope
from src.market_data.native_short_writer_provenance_v1 import build_explicit_test_provenance
from tests.writer_auth_support import make_test_authorization

_AS_OF = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
_PROVENANCE = build_explicit_test_provenance()
_NS_AUTH = make_test_authorization("native_short_4h_chain")
_MODULE_PATH = Path("src/market_data/native_short_scope_status_materializer_v1.py")


def _key() -> NativeShortMapScopeKey:
    return NativeShortMapScopeKey(venue="bitvavo", symbol="BTC", quote_currency="EUR")


def _context_row(**overrides) -> NativeShortContextRow:
    fields = dict(
        symbol="BTC",
        venue="bitvavo",
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
        context_status=STATUS_AVAILABLE,
        map_cycle_id="cycle-A",
        anchor_start_ts_utc=_AS_OF - timedelta(days=10),
        anchor_end_ts_utc=_AS_OF - timedelta(days=5),
        anchor_low_price=None,
        anchor_high_price=None,
        breakout_gate_price=None,
        latest_primary_close_ts_utc=_AS_OF - timedelta(hours=1),
        latest_support_close_ts_utc=_AS_OF - timedelta(minutes=20),
        latest_primary_close_price=None,
        ext_1_272_price=None,
        ext_1_618_price=None,
        ext_2_000_price=None,
        active_target_levels=(),
        previous_target_levels=(),
        reload_r382_price=None,
        reload_r500_price=None,
        reload_r618_price=None,
        reload_r786_price=None,
        invalidation_price=None,
        primary_4h_lifecycle_state=PRIMARY_LIFECYCLE_COMPLETED,
        supporting_1h_state="ALIGNED_WITH_4H",
        context_freshness_status="FRESH",
        max_primary_high_since_anchor=None,
        min_primary_low_since_anchor=None,
        source_name="native_short_fib_context_v1",
        source_version="0.1",
        source_primary_ref="obs_market_candle:4h",
        source_support_ref="obs_market_candle:1h",
        current_map_status="CURRENT_ACTIVE_MAP",
        previous_map_cycle_id="",
        previous_map_lifecycle_state="",
        rollover_state="SINGLE_MAP",
        selection_reason="Single active map selected",
        source_primary_candle_count=73,
        source_support_candle_count=219,
    )
    fields.update(overrides)
    return NativeShortContextRow(**fields)


def _map_row(**overrides) -> dict:
    row = {
        "map_id": 700,
        "structure_hash": "a" * 64,
        "generator_name": "native_short_map_materializer_v1",
        "generator_version": "0.1",
        "fib_model_name": "fib_v1",
        "fib_model_version": "0.1",
        "published_generation_attempt_id": "attempt-700",
        "previous_map_id": None,
        "previous_map_cycle_id": None,
        "map_cycle_id": "cycle-A",
        "market_snapshot_ts_utc": None,
        "published_at_utc": _AS_OF - timedelta(days=6),
        "anchor_low_ts_utc": None,
        "anchor_low_price": None,
        "anchor_high_ts_utc": _AS_OF - timedelta(days=5),
        "anchor_high_price": Decimal("10.0"),
        "retrace_ratio": None,
        "retrace_price": None,
        "fib_ratios_json": '{"ext_1_272": "10.5", "ext_1_618": "11.2", "ext_2_000": "12.0"}',
        "target_levels_json": "[]",
        "invalidation_price": None,
        "invalidation_rule": "",
        "source_primary_candle_ts_utc": None,
        "source_support_candle_ts_utc": None,
        "source_primary_ref": "",
        "source_support_ref": "",
        "source_primary_candle_count": 1,
        "source_support_candle_count": 1,
        "map_payload_json": "{}",
    }
    row.update(overrides)
    return row


class _MapFactLike:
    def __init__(self, row: dict) -> None:
        self.map_id = row["map_id"]
        self.published_at_utc = row["published_at_utc"]
        self.map_cycle_id = row["map_cycle_id"]
        self.structure_hash = row["structure_hash"]


class _LifecycleEventLike:
    def __init__(
        self, *, lifecycle_event_id: int, map_id: int, event_type: str, event_ts_utc: datetime
    ) -> None:
        self.lifecycle_event_id = lifecycle_event_id
        self.map_id = map_id
        self.event_type = event_type
        self.event_ts_utc = event_ts_utc
        self.successor_map_id = None


def _candle_row(*, close_ts_utc: datetime, high: str, close: str) -> dict:
    return {
        "close_ts_utc": close_ts_utc,
        "open_price": close,
        "high_price": high,
        "low_price": close,
        "close_price": close,
    }


class _FakeCursor:
    def __init__(self, script: dict) -> None:
        self._script = script
        self._result: object = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: Any = ()) -> None:
        call_log = self._script.setdefault("call_log", [])
        if "FROM native_short_scope_support_event_v1" in sql:
            self._result = self._script.get("support_events", [])
        elif "FROM native_short_scope_cadence_config_v1" in sql:
            self._result = self._script.get("cadence_configs", [])
        elif "FROM native_short_map_v1" in sql:
            call_log.append("SELECT_MAP")
            self._result = self._script.get("map")
        elif "FROM obs_market_candle" in sql:
            call_log.append("SELECT_CANDLES")
            self._result = self._script.get("candles", [])
        elif "FROM venue_market" in sql:
            self._result = []
        elif "FROM native_short_map_level_target_event_coverage_v1" in sql:
            coverage = self._script.get("coverage")
            map_id = params[0] if isinstance(params, (tuple, list)) else params
            self._result = coverage if (coverage is not None and coverage["map_id"] == map_id) else None
        elif "FROM native_short_map_level_target_event_v1" in sql:
            self._result = self._script.get("existing_events", [])
        elif sql.strip().startswith("INSERT INTO native_short_map_level_target_event_coverage_v1"):
            call_log.append("INSERT_COVERAGE")
            existing = self._script.get("coverage")
            if existing is not None and existing["map_id"] == params["map_id"]:
                from pymysql.err import IntegrityError

                raise IntegrityError(1062, "Duplicate entry")
            self._script["coverage"] = dict(params)
        elif sql.strip().startswith("INSERT INTO native_short_map_level_target_event_v1"):
            call_log.append("INSERT_TARGET_EVENT")
            identity = (
                params["map_id"],
                params["canonical_map_level_role"],
                params["side"],
                params["canonical_unrounded_price"],
                params["target_event_type"],
            )
            inserted = self._script.setdefault("inserted_target_event_identities", set())
            if identity in inserted:
                from pymysql.err import IntegrityError

                raise IntegrityError(1062, "Duplicate entry")
            inserted.add(identity)
            self._script.setdefault("inserted_target_events", []).append(params)
        elif sql.strip().startswith("INSERT INTO native_short_scope_observation_v1"):
            call_log.append("INSERT_OBSERVATION")
        elif sql.strip().startswith("INSERT INTO native_short_map_lifecycle_event_v1"):
            call_log.append("INSERT_LIFECYCLE_EVENT")
            if self._script.get("raise_on_lifecycle_insert"):
                raise RuntimeError("simulated failure after target event insert")
            events = self._script.setdefault("lifecycle_events", [])
            events.append(
                {
                    "lifecycle_event_id": len(events) + 1,
                    "map_id": params[0],
                    "event_type": params[1],
                    "event_ts_utc": params[2],
                }
            )
            self._lastrowid = len(events)
        else:
            raise AssertionError(f"unexpected SQL in fake cursor: {sql.strip()[:100]}")

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._result or []

    @property
    def lastrowid(self) -> int:
        return getattr(self, "_lastrowid", 1)

    @property
    def rowcount(self) -> int:
        return 1


class _FakeConn:
    def __init__(self, script: dict) -> None:
        self.script = script

    def cursor(self):
        return _FakeCursor(self.script)


def _materialize_stub(*_args: Any, **_kwargs: Any) -> ScopeMaterializationResult:
    return ScopeMaterializationResult(symbol="BTC", attempted=True, status="unchanged", dry_run=False, map_id=700)


def _run_evaluate_scope(script: dict, *, watermark: datetime | None) -> tuple[_FakeConn, Any]:
    conn = _FakeConn(script)
    map_row = script["map"]
    outcome = evaluate_scope(
        conn,
        key=_key(),
        as_of_utc=_AS_OF,
        run_id=1,
        provenance=_PROVENANCE,
        fetch_context_row=lambda key, as_of_utc: _context_row(),
        fetch_existing_maps=lambda conn, key: [_MapFactLike(map_row)],
        fetch_existing_generation_events=lambda conn, key: [],
        fetch_existing_lifecycle_events=lambda conn, map_ids: [
            _LifecycleEventLike(**event) for event in script.get("lifecycle_events", [])
        ],
        materialize_scope_symbol_fn=_materialize_stub,
        authorization=_NS_AUTH,
        target_event_coverage_watermark_utc=watermark,
    )
    return conn, outcome


def _base_script() -> dict:
    return {
        "map": _map_row(),
        "candles": [_candle_row(close_ts_utc=_AS_OF - timedelta(hours=4), high="12.1", close="12.05")],
        "existing_events": [],
        "coverage": None,
        "lifecycle_events": [],
        "support_events": [
            {
                "scope_support_event_id": 1,
                "scope_support_state": "SUPPORTED",
                "event_ts_utc": _AS_OF - timedelta(days=30),
            }
        ],
        "cadence_configs": [
            {
                "cadence_contract_version": "native_short_cadence_v1",
                "target_evaluation_interval": "4h",
                "primary_source_freshness_limit_seconds": 43200,
                "supporting_source_freshness_limit_seconds": 10800,
                "evaluation_grace_seconds": 900,
                "recent_scope_grace_seconds": 900,
                "effective_from_utc": _AS_OF - timedelta(days=30),
                "effective_to_utc": None,
            }
        ],
    }


def test_completing_candle_records_target_event_and_completed_state_in_one_pass() -> None:
    script = _base_script()
    conn, outcome = _run_evaluate_scope(script, watermark=_AS_OF - timedelta(days=7))
    assert outcome.lifecycle_event_appended is True
    assert outcome.target_event_rows_appended >= 1
    assert len(script["lifecycle_events"]) == 1
    assert script["lifecycle_events"][0]["event_type"] == "COMPLETED"


def test_execution_order_target_event_insert_precedes_lifecycle_event_insert() -> None:
    script = _base_script()
    _run_evaluate_scope(script, watermark=_AS_OF - timedelta(days=7))
    call_log = script["call_log"]
    target_event_index = call_log.index("INSERT_TARGET_EVENT")
    lifecycle_index = call_log.index("INSERT_LIFECYCLE_EVENT")
    assert target_event_index < lifecycle_index


def test_evaluate_scope_never_commits_or_rolls_back_itself() -> None:
    """Atomicity is inherited from the caller's single shared transaction:
    evaluate_scope must never call conn.commit()/conn.rollback() directly, so
    a failure anywhere in its write sequence leaves rollback entirely to
    whichever caller owns the transaction (see
    run_native_short_scope_status_materializer's own tested rollback-on-
    exception contract in test_native_short_scope_status_materializer_orchestrator_v1.py)."""
    source = _MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    evaluate_scope_node = functions["evaluate_scope"]
    for node in ast.walk(evaluate_scope_node):
        if isinstance(node, ast.Attribute) and node.attr in ("commit", "rollback"):
            raise AssertionError("evaluate_scope must never commit/rollback its own connection")


def test_terminal_map_cannot_generate_new_events_from_later_candles() -> None:
    script = _base_script()
    _run_evaluate_scope(script, watermark=_AS_OF - timedelta(days=7))
    assert len(script["lifecycle_events"]) == 1
    first_event_count = len(script.get("inserted_target_events", []))
    assert first_event_count >= 1

    # A later cycle observes a further candle continuing to close well above
    # the level, on an already-COMPLETED map.
    script["candles"].append(
        _candle_row(close_ts_utc=_AS_OF + timedelta(hours=4), high="13.0", close="12.9")
    )
    second_conn, second_outcome = _run_evaluate_scope(script, watermark=_AS_OF - timedelta(days=7))
    assert second_outcome.lifecycle_event_appended is False
    assert second_outcome.target_event_rows_appended == 0
    assert len(script["lifecycle_events"]) == 1  # no second COMPLETED event
    assert len(script.get("inserted_target_events", [])) == first_event_count  # no new target events


def test_idempotent_retry_creates_no_duplicate_event_or_lifecycle_transition() -> None:
    script = _base_script()
    first_conn, first_outcome = _run_evaluate_scope(script, watermark=_AS_OF - timedelta(days=7))
    assert len(script["lifecycle_events"]) == 1
    events_after_first = len(script.get("inserted_target_events", []))

    # Simulate an identical retry of the same cycle (e.g. a crashed run
    # re-invoked with the same as_of_utc and the same observed facts).
    second_conn, second_outcome = _run_evaluate_scope(script, watermark=_AS_OF - timedelta(days=7))
    assert second_outcome.lifecycle_event_appended is False
    assert second_outcome.target_event_rows_appended == 0
    assert len(script["lifecycle_events"]) == 1
    assert len(script.get("inserted_target_events", [])) == events_after_first
