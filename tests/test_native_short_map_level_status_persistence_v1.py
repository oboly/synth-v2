from __future__ import annotations

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.market_data.native_short_map_level_status_v1 import (
    NativeShortMapLevelEvaluationReference,
    NativeShortMapLevelRole,
    NativeShortMapLevelSide,
    NativeShortMapLevelState,
    NativeShortMapLevelStatusPersistenceError,
    NativeShortMapLevelStatusRecord,
    REASON_MAP_COMPLETED,
    REASON_NO_PRIMARY_HIGH_REACHED_LEVEL,
    V1_NATIVE_SHORT_SELL_LEVEL_ROLES,
    delete_native_short_map_level_status_for_scope,
    replace_native_short_map_level_status_for_scope,
    serialize_native_short_map_level_status_record,
    validate_native_short_map_level_status_collection,
)
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey
from src.market_data.native_short_scope_status_v1 import (
    NativeShortScopeActionabilityState,
    NativeShortScopeMapLifecycleState,
    NativeShortScopeStatusCode,
)
from src.market_data.native_short_writer_provenance_v1 import build_explicit_test_provenance
from src.market_rules.price_tick_normalization_v1 import (
    NORM_STATUS_APPLIED,
    NORM_STATUS_MISSING,
    TICK_RULE_SOURCE_DB,
    TICK_RULE_SOURCE_MISSING,
)
from src.operations.writer_capability_authorization_v1 import AuthorizationDenied
from tests.writer_auth_support import make_test_authorization

MIGRATION_PATH = Path("db/migrations/20260708_native_short_map_level_status_v1.sql")
MODULE_PATH = Path("src/market_data/native_short_map_level_status_v1.py")
_WRONG_AUTH = make_test_authorization("public_price_snapshot")


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _key() -> NativeShortMapScopeKey:
    return NativeShortMapScopeKey(
        venue="bitvavo",
        symbol="NEAR",
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
    )


def _row(
    *,
    role: NativeShortMapLevelRole = NativeShortMapLevelRole.SELL_EXT_1_272,
    state: NativeShortMapLevelState = NativeShortMapLevelState.ACTIVE,
    price: Decimal = Decimal("1.272"),
    rounded_price: Decimal | None = Decimal("1.280"),
    tick_status: str = NORM_STATUS_APPLIED,
    tick_source: str = TICK_RULE_SOURCE_DB,
    map_lifecycle: NativeShortScopeMapLifecycleState = NativeShortScopeMapLifecycleState.MAP_ACTIVE,
    scope_status: NativeShortScopeStatusCode = NativeShortScopeStatusCode.CURRENT_EVALUATION,
    actionability: NativeShortScopeActionabilityState = NativeShortScopeActionabilityState.ACTIONABLE_ACTIVE_MAP,
    evaluation_reference: NativeShortMapLevelEvaluationReference = NativeShortMapLevelEvaluationReference.PRIMARY_4H_CLOSED_CANDLES,
    reason_code: str = REASON_NO_PRIMARY_HIGH_REACHED_LEVEL,
) -> NativeShortMapLevelStatusRecord:
    return NativeShortMapLevelStatusRecord(
        key=_key(),
        current_map_id=123,
        map_cycle_id="NEAR|SHORT|4h|2026-07-01T00:00:00+00:00|2026-07-02T00:00:00+00:00",
        canonical_map_level_role=role,
        side=NativeShortMapLevelSide.SELL,
        canonical_unrounded_price=price,
        canonical_tick_rounded_price=rounded_price,
        tick_rule_status=tick_status,
        tick_rule_source=tick_source,
        level_lifecycle_state=state,
        level_status_as_of_utc=datetime(2026, 7, 8, 2, 0, tzinfo=UTC),
        evaluation_reference=evaluation_reference,
        reason_code=reason_code,
        projection_scope_status_code=scope_status,
        projection_map_lifecycle_state=map_lifecycle,
        projection_actionability_state=actionability,
        rebuilt_at_utc=datetime(2026, 7, 8, 2, 1, tzinfo=UTC),
    )


class _FakeMutationCursor:
    rowcount = 0

    def __init__(self, conn: "_FakeMutationConn") -> None:
        self._conn = conn

    def __enter__(self) -> "_FakeMutationCursor":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        self._conn.execute_called = True

    def executemany(self, sql: str, params: object = None) -> None:
        self._conn.executemany_called = True


class _FakeMutationConn:
    def __init__(self) -> None:
        self.execute_called = False
        self.executemany_called = False
        self.commit_called = False

    def cursor(self) -> _FakeMutationCursor:
        return _FakeMutationCursor(self)

    def commit(self) -> None:
        self.commit_called = True


def _rows() -> tuple[NativeShortMapLevelStatusRecord, ...]:
    return tuple(
        _row(role=role, price=Decimal(index) + Decimal("1.0"))
        for index, role in enumerate(V1_NATIVE_SHORT_SELL_LEVEL_ROLES)
    )


def _assert_no_sql_mutation(conn: _FakeMutationConn) -> None:
    assert conn.execute_called is False
    assert conn.executemany_called is False
    assert conn.commit_called is False


@pytest.mark.parametrize("authorization", (None, {}, _WRONG_AUTH))
def test_delete_requires_valid_native_short_authorization_before_sql(authorization: object) -> None:
    conn = _FakeMutationConn()
    with pytest.raises(AuthorizationDenied):
        delete_native_short_map_level_status_for_scope(
            conn,
            key=_key(),
            provenance=build_explicit_test_provenance(),
            authorization=authorization,  # type: ignore[arg-type]
        )
    _assert_no_sql_mutation(conn)


def test_delete_missing_authorization_argument_touches_no_sql() -> None:
    conn = _FakeMutationConn()

    with pytest.raises(TypeError):
        delete_native_short_map_level_status_for_scope(
            conn,
            key=_key(),
            provenance=build_explicit_test_provenance(),
        )
    _assert_no_sql_mutation(conn)


@pytest.mark.parametrize("rows", ((), _rows()))
@pytest.mark.parametrize("authorization", (None, {}, _WRONG_AUTH))
def test_replace_requires_valid_native_short_authorization_before_sql(
    rows: tuple[NativeShortMapLevelStatusRecord, ...],
    authorization: object,
) -> None:
    conn = _FakeMutationConn()

    with pytest.raises(AuthorizationDenied):
        replace_native_short_map_level_status_for_scope(
            conn,
            key=_key(),
            current_map_id=123,
            map_cycle_id=_row().map_cycle_id,
            level_status_as_of_utc=_row().level_status_as_of_utc,
            rows=rows,
            provenance=build_explicit_test_provenance(),
            authorization=authorization,  # type: ignore[arg-type]
        )
    _assert_no_sql_mutation(conn)


@pytest.mark.parametrize("rows", ((), _rows()))
def test_replace_missing_authorization_argument_touches_no_sql(
    rows: tuple[NativeShortMapLevelStatusRecord, ...],
) -> None:
    conn = _FakeMutationConn()

    with pytest.raises(TypeError):
        replace_native_short_map_level_status_for_scope(
            conn,
            key=_key(),
            current_map_id=123,
            map_cycle_id=_row().map_cycle_id,
            level_status_as_of_utc=_row().level_status_as_of_utc,
            rows=rows,
            provenance=build_explicit_test_provenance(),
        )
    _assert_no_sql_mutation(conn)


def test_migration_creates_single_rebuildable_table() -> None:
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS native_short_map_level_status_v1" in sql
    assert sql.count("CREATE TABLE IF NOT EXISTS") == 1
    assert "COMMENT='Rebuildable current native SHORT per-map-level status projection" in sql


def test_migration_uses_full_scope_and_map_level_identity() -> None:
    sql = _sql()
    assert "UNIQUE KEY uq_native_short_map_level_status_v1_identity" in sql
    assert "venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval" in sql
    for required in (
        "current_map_id",
        "canonical_map_level_role",
        "side",
        "canonical_unrounded_price",
    ):
        assert required in sql
    assert "browser" not in sql.lower()
    assert "render_uuid" not in sql.lower()


def test_migration_has_closed_domains_and_projection_clock() -> None:
    sql = _sql()
    for required in (
        "projection_scope_status_code",
        "projection_map_lifecycle_state",
        "projection_actionability_state",
        "level_status_as_of_utc DATETIME(6) NOT NULL",
        "CHECK (canonical_map_level_role IN ('SELL_EXT_1_272', 'SELL_EXT_1_618', 'SELL_EXT_2_000'))",
        "CHECK (side = 'SELL')",
        "CHECK (level_lifecycle_state IN ('ACTIVE', 'REACHED', 'PASSED', 'COMPLETED', 'HISTORICAL'))",
        "CHECK (evaluation_reference IN ('PRIMARY_4H_CLOSED_CANDLES', 'MAP_LIFECYCLE_EVENT'))",
        "CHECK (tick_rule_status IN ('TICK_RULE_APPLIED', 'MISSING_TICK_RULE'))",
        "CHECK (tick_rule_source IN ('TICK_RULE_FROM_DB', 'TICK_RULE_FROM_STATIC', 'MISSING_TICK_RULE'))",
        "CONFIGURATION_UNAVAILABLE",
    ):
        assert required in sql


def test_migration_has_no_immutable_ledger_heartbeat_writes() -> None:
    sql = _sql()
    assert "native_short_map_generation_event_v1" not in sql
    assert "native_short_map_lifecycle_event_v1" not in sql
    assert "INSERT INTO" not in sql
    assert "UPDATE native_short_map_v1" not in sql


def test_valid_record_serializes_closed_enums_and_decimal_strings() -> None:
    row = _row()
    serialized = serialize_native_short_map_level_status_record(row)
    assert serialized["venue"] == "bitvavo"
    assert serialized["canonical_map_level_role"] == "SELL_EXT_1_272"
    assert serialized["side"] == "SELL"
    assert serialized["canonical_unrounded_price"] == "1.272"
    assert serialized["canonical_tick_rounded_price"] == "1.280"
    assert serialized["level_lifecycle_state"] == "ACTIVE"
    assert serialized["level_status_as_of_utc"] == datetime(2026, 7, 8, 2, 0, tzinfo=UTC)


def test_missing_tick_rule_requires_null_rounded_price_and_missing_source() -> None:
    row = _row(
        rounded_price=None,
        tick_status=NORM_STATUS_MISSING,
        tick_source=TICK_RULE_SOURCE_MISSING,
    )
    serialized = serialize_native_short_map_level_status_record(row)
    assert serialized["canonical_tick_rounded_price"] is None
    assert serialized["tick_rule_status"] == "MISSING_TICK_RULE"
    assert serialized["tick_rule_source"] == "MISSING_TICK_RULE"


@pytest.mark.parametrize(
    "state",
    [
        NativeShortMapLevelState.ACTIVE,
        NativeShortMapLevelState.REACHED,
        NativeShortMapLevelState.PASSED,
    ],
)
def test_non_terminal_level_states_require_active_projection(
    state: NativeShortMapLevelState,
) -> None:
    with pytest.raises(NativeShortMapLevelStatusPersistenceError, match="ACTIVE_MAP_PROJECTION"):
        _row(state=state, map_lifecycle=NativeShortScopeMapLifecycleState.MAP_COMPLETED)
    with pytest.raises(NativeShortMapLevelStatusPersistenceError, match="CURRENT_EVALUATION"):
        _row(state=state, scope_status=NativeShortScopeStatusCode.SOURCE_STALE)
    with pytest.raises(NativeShortMapLevelStatusPersistenceError, match="ACTIONABLE_ACTIVE_MAP"):
        _row(state=state, actionability=NativeShortScopeActionabilityState.BLOCKED_SOURCE)


def test_terminal_completed_requires_completed_projection_context() -> None:
    row = _row(
        state=NativeShortMapLevelState.COMPLETED,
        map_lifecycle=NativeShortScopeMapLifecycleState.MAP_COMPLETED,
        scope_status=NativeShortScopeStatusCode.MAP_COMPLETED,
        actionability=NativeShortScopeActionabilityState.TERMINAL_MAP,
        evaluation_reference=NativeShortMapLevelEvaluationReference.MAP_LIFECYCLE_EVENT,
        reason_code=REASON_MAP_COMPLETED,
    )
    assert serialize_native_short_map_level_status_record(row)["level_lifecycle_state"] == "COMPLETED"
    with pytest.raises(NativeShortMapLevelStatusPersistenceError, match="MAP_LIFECYCLE_REFERENCE"):
        _row(state=NativeShortMapLevelState.COMPLETED)


def test_collection_allows_empty_fail_closed_replacement() -> None:
    assert (
        validate_native_short_map_level_status_collection(
            key=_key(),
            current_map_id=123,
            map_cycle_id="cycle-a",
            level_status_as_of_utc=datetime(2026, 7, 8, 2, 0, tzinfo=UTC),
            rows=[],
        )
        == ()
    )


def test_collection_requires_exact_v1_role_set_when_rows_present() -> None:
    rows = [
        _row(role=role, price=Decimal(index) + Decimal("1.0"))
        for index, role in enumerate(V1_NATIVE_SHORT_SELL_LEVEL_ROLES)
    ]
    assert len(
        validate_native_short_map_level_status_collection(
            key=_key(),
            current_map_id=123,
            map_cycle_id=rows[0].map_cycle_id,
            level_status_as_of_utc=rows[0].level_status_as_of_utc,
            rows=rows,
        )
    ) == 3
    with pytest.raises(NativeShortMapLevelStatusPersistenceError, match="V1_ROLE_SET_INCOMPLETE"):
        validate_native_short_map_level_status_collection(
            key=_key(),
            current_map_id=123,
            map_cycle_id=rows[0].map_cycle_id,
            level_status_as_of_utc=rows[0].level_status_as_of_utc,
            rows=rows[:2],
        )


def test_collection_rejects_duplicate_role_even_with_different_price() -> None:
    rows = [
        _row(role=NativeShortMapLevelRole.SELL_EXT_1_272, price=Decimal("1.272")),
        _row(role=NativeShortMapLevelRole.SELL_EXT_1_272, price=Decimal("1.273")),
        _row(role=NativeShortMapLevelRole.SELL_EXT_1_618, price=Decimal("1.618")),
        _row(role=NativeShortMapLevelRole.SELL_EXT_2_000, price=Decimal("2.000")),
    ]
    with pytest.raises(NativeShortMapLevelStatusPersistenceError, match="DUPLICATE_LEVEL_ROLE"):
        validate_native_short_map_level_status_collection(
            key=_key(),
            current_map_id=123,
            map_cycle_id=rows[0].map_cycle_id,
            level_status_as_of_utc=rows[0].level_status_as_of_utc,
            rows=rows,
        )


def test_new_type_module_imports_no_forbidden_layers() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    for module_name in imported_modules:
        for forbidden in (
            "src.bro" + "ker",
            "src.acc" + "ount",
            "src.exec" + "utor",
            "src.exec" + "ution",
            "src.exec" + "ution_planner",
            "src.decision" + "_gate",
            "src.reporting",
            "src.selection" + "_engine",
        ):
            assert not module_name.startswith(forbidden), module_name


def test_migration_introduces_no_forbidden_layer_references() -> None:
    sql = _sql().lower()
    for forbidden in (
        "sys" + "temd",
        " ti" + "mer",
        " ser" + "vice",
        "sub" + "process",
        "bro" + "ker",
        "acc" + "ount",
        "wal" + "let",
        "exec" + "utor",
        "exec" + "ution_planner",
        "decision" + "_gate",
        "selection" + "_engine",
    ):
        assert forbidden not in sql
