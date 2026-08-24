from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.entry_policy.automatic_buy_source_runtime_input_writer_v1 import (
    AutomaticBuyCanonicalZoneUniverseSourceRequestV1,
    AutomaticBuySourceRuntimeInputRequestV1,
)
from src.entry_policy.run_automatic_buy_dry_run_acceptance_v1 import (
    ALLOWED_INPUT_KEYS,
    CANONICAL_ZONE_SOURCE_INPUT_KEYS,
    CANONICAL_ZONE_UNIVERSE_SOURCE_INPUT_KEYS,
    FRESH_SOURCE_INPUT_KEYS,
    AutomaticBuyDryRunAcceptanceCliError,
    parse_fresh_source_candidate_from_json,
    parse_canonical_zone_source_request_from_json,
    parse_canonical_zone_universe_source_request_from_json,
    parse_source_request_from_json,
    run_automatic_buy_dry_run_acceptance_v1,
    _run_canonical_zone_universe_acceptance_v1,
)
from src.executor.execution_handoff_v1 import ExecutionHandoffV1
from src.executor.execution_plan_reference_v1 import ApprovedExecutionPlanV1
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import (
    TS,
    FakeConnection,
    insert_trading_account,
    seed_happy_path,
)

_AUDIT_TABLE_SCHEMA = """
CREATE TABLE automatic_buy_evaluation_audit_v1 (
    automatic_buy_evaluation_audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    runtime_version TEXT NOT NULL,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    asset_id INTEGER NOT NULL,
    market TEXT NOT NULL,
    source_evidence_json TEXT NOT NULL,
    candidate_state TEXT NOT NULL,
    candidate_action TEXT,
    candidate_reason_code TEXT NOT NULL,
    candidate_evidence_id TEXT,
    gate_state TEXT,
    gate_reason_code TEXT,
    approved_notional_ceiling_eur TEXT,
    strategy_bucket_reason_code TEXT,
    protection_code TEXT,
    protection_reason_code TEXT,
    planner_state TEXT NOT NULL,
    planner_reason_code TEXT,
    immutable_plan_json TEXT,
    evaluation_ts_utc TEXT NOT NULL,
    planning_ts_utc TEXT
);
"""


def _conn_with_audit_table() -> FakeConnection:
    conn = FakeConnection()
    conn.raw.executescript(_AUDIT_TABLE_SCHEMA)
    return conn


class _FakeHandoffRepository:
    def __init__(self) -> None:
        self.intake_calls: list[tuple[ApprovedExecutionPlanV1, str, str, str]] = []
        self.by_reference: dict[tuple[str, str], ExecutionHandoffV1] = {}

    def intake(
        self, *, plan: ApprovedExecutionPlanV1, executor_mode: str, executor_identity: str, runtime_owner: str,
    ) -> ExecutionHandoffV1:
        self.intake_calls.append((plan, executor_mode, executor_identity, runtime_owner))
        key = (plan.plan_source, plan.plan_reference_id)
        if key not in self.by_reference:
            self.by_reference[key] = ExecutionHandoffV1(
                handoff_id=len(self.by_reference) + 1,
                plan_source=plan.plan_source,
                plan_reference_id=plan.plan_reference_id,
                plan_content_hash=plan.content_hash,
                trading_account_id=plan.trading_account_id,
                venue=plan.venue,
                market=plan.market,
                side=plan.side,
                executor_mode=executor_mode,
                executor_identity=executor_identity,
                runtime_owner=runtime_owner,
                executor_credential_binding_id=None,
            )
        return self.by_reference[key]

    def intake_live_authorized(self, **_kwargs: object) -> ExecutionHandoffV1:
        raise AssertionError("DRY_RUN-only acceptance must never call intake_live_authorized")


def _paper_request(**overrides: object) -> AutomaticBuySourceRuntimeInputRequestV1:
    base = dict(
        evaluation_ts_utc=TS,
        trading_account_id=7,
        venue="bitvavo",
        asset_id=101,
        market="BTC-EUR",
        strategy_bucket_id="SHORT_TERM_ROTATION",
        strategy_id="strategy-a",
        strategy_version="1",
        setup_id="setup-1",
        setup_ready=True,
        current_price=Decimal("100"),
        entry_zone_low=Decimal("95"),
        entry_zone_high=Decimal("105"),
        re_entry_zone_low=None,
        re_entry_zone_high=None,
        setup_evidence_id="ev-1",
        setup_observed_ts_utc=TS,
        source_provenance="test",
    )
    base.update(overrides)
    return AutomaticBuySourceRuntimeInputRequestV1(**base)  # type: ignore[arg-type]


def test_paper_account_reaches_approved_staged_and_dry_run_handoff() -> None:
    conn = _conn_with_audit_table()
    seed_happy_path(conn)
    repo = _FakeHandoffRepository()

    result = run_automatic_buy_dry_run_acceptance_v1(conn, request=_paper_request(), handoff_repository=repo)

    assert result.candidate_state == "CANDIDATE"
    assert result.gate_state == "APPROVED"
    assert result.planner_state == "STAGED"
    assert result.handoff_id is not None
    assert result.plan_reference_id is not None
    assert result.plan_content_hash is not None
    assert result.executor_mode == "DRY_RUN"
    assert result.runtime_owner == "gurkdb"
    assert result.executor_identity == "shared-executor-v1"
    assert result.safety_markers == {
        "broker_private_calls": 0, "broker_writes": 0, "order_submission": 0,
        "live_orders": 0, "live_authority": 0,
    }
    assert len(repo.intake_calls) == 1
    _, executor_mode, executor_identity, runtime_owner = repo.intake_calls[0]
    assert executor_mode == "DRY_RUN"
    assert executor_identity == "shared-executor-v1"
    assert runtime_owner == "gurkdb"


def test_live_account_with_live_trading_disabled_remains_rejected() -> None:
    from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import (
        bind_account_market,
        insert_balance,
        insert_bucket_config,
        insert_buy_permission,
        insert_complete_bundle,
        insert_venue_constraint,
        insert_venue_market,
    )

    conn = _conn_with_audit_table()
    insert_trading_account(conn, account_mode="live", live_trading_enabled=False)
    insert_complete_bundle(conn)
    venue_market_id = insert_venue_market(conn)
    bind_account_market(conn, venue_market_id=venue_market_id)
    insert_balance(conn)
    insert_bucket_config(conn)
    insert_buy_permission(conn)
    insert_venue_constraint(conn)
    repo = _FakeHandoffRepository()

    result = run_automatic_buy_dry_run_acceptance_v1(conn, request=_paper_request(), handoff_repository=repo)

    assert result.candidate_state == "CANDIDATE"
    assert result.gate_state != "APPROVED"
    assert result.planner_state == "NOT_REACHED"
    assert result.handoff_id is None
    assert result.plan_reference_id is None
    assert repo.intake_calls == []


def test_replay_is_idempotent_and_never_duplicates_evidence_or_handoff() -> None:
    conn = _conn_with_audit_table()
    seed_happy_path(conn)
    repo = _FakeHandoffRepository()

    first = run_automatic_buy_dry_run_acceptance_v1(conn, request=_paper_request(), handoff_repository=repo)
    second = run_automatic_buy_dry_run_acceptance_v1(conn, request=_paper_request(), handoff_repository=repo)

    assert first.runtime_input_id == second.runtime_input_id
    assert first.source_snapshot_key == second.source_snapshot_key
    assert first.handoff_id == second.handoff_id
    assert first.plan_reference_id == second.plan_reference_id

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM automatic_buy_runtime_input_v1")
        assert cur.fetchone()["n"] == 1
        cur.execute("SELECT COUNT(*) AS n FROM automatic_buy_evaluation_audit_v1")
        assert cur.fetchone()["n"] == 1
    assert len(repo.by_reference) == 1
    assert len(repo.intake_calls) == 2  # called twice, but deduped to one persisted handoff


def test_universe_acceptance_retries_only_after_a_normal_gate_denial(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.entry_policy.run_automatic_buy_dry_run_acceptance_v1 as runner

    requests = (_paper_request(market="HOT-EUR", asset_id=1), _paper_request(market="BTC-EUR", asset_id=2))
    seen: list[str] = []

    def result_for(*, market: str, gate_state: str) -> runner.AutomaticBuyDryRunAcceptanceResultV1:
        return runner.AutomaticBuyDryRunAcceptanceResultV1(
            runtime_input_id=1,
            source_snapshot_key=market,
            candidate_state="CANDIDATE",
            gate_state=gate_state,
            gate_reason=None,
            planner_state="STAGED" if gate_state == "APPROVED" else "NOT_REACHED",
            planner_reason=None,
            handoff_id=None,
            plan_reference_id=None,
            plan_content_hash=None,
            executor_mode="DRY_RUN",
            runtime_owner="gurkdb",
            executor_identity="shared-executor-v1",
            safety_markers={},
        )

    monkeypatch.setattr(
        runner,
        "resolve_actionable_canonical_zone_source_runtime_input_requests_v1",
        lambda *_args, **_kwargs: requests,
    )

    def run_once(*_args: object, request: AutomaticBuySourceRuntimeInputRequestV1, **_kwargs: object) -> runner.AutomaticBuyDryRunAcceptanceResultV1:
        seen.append(request.market)
        return result_for(market=request.market, gate_state="DENIED" if request.market == "HOT-EUR" else "APPROVED")

    monkeypatch.setattr(runner, "run_automatic_buy_dry_run_acceptance_v1", run_once)
    result = _run_canonical_zone_universe_acceptance_v1(
        object(),
        universe=AutomaticBuyCanonicalZoneUniverseSourceRequestV1(
            trading_account_id=7,
            venue="bitvavo",
            strategy_bucket_id="SHORT_TERM_ROTATION",
            strategy_id="strategy-a",
            strategy_version="1",
        ),
        now_utc=TS,
    )

    assert seen == ["HOT-EUR", "BTC-EUR"]
    assert result.gate_state == "APPROVED"


def test_universe_acceptance_rolls_back_and_skips_unbound_market_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.entry_policy.run_automatic_buy_dry_run_acceptance_v1 as runner

    class _Conn:
        rollbacks = 0

        def rollback(self) -> None:
            self.rollbacks += 1

    requests = (_paper_request(market="AERO-EUR", asset_id=1), _paper_request(market="BTC-EUR", asset_id=2))
    conn = _Conn()
    seen: list[str] = []
    approved = runner.AutomaticBuyDryRunAcceptanceResultV1(
        runtime_input_id=2,
        source_snapshot_key="BTC-EUR",
        candidate_state="CANDIDATE",
        gate_state="APPROVED",
        gate_reason=None,
        planner_state="STAGED",
        planner_reason=None,
        handoff_id=None,
        plan_reference_id=None,
        plan_content_hash=None,
        executor_mode="DRY_RUN",
        runtime_owner="gurkdb",
        executor_identity="shared-executor-v1",
        safety_markers={},
    )
    monkeypatch.setattr(
        runner,
        "resolve_actionable_canonical_zone_source_runtime_input_requests_v1",
        lambda *_args, **_kwargs: requests,
    )

    def run_once(*_args: object, request: AutomaticBuySourceRuntimeInputRequestV1, **_kwargs: object) -> runner.AutomaticBuyDryRunAcceptanceResultV1:
        seen.append(request.market)
        if request.market == "AERO-EUR":
            raise runner.AutomaticBuyRuntimeRepositoryError("ASSET_MARKET_BINDING_MISSING")
        return approved

    monkeypatch.setattr(runner, "run_automatic_buy_dry_run_acceptance_v1", run_once)
    result = _run_canonical_zone_universe_acceptance_v1(
        conn,
        universe=AutomaticBuyCanonicalZoneUniverseSourceRequestV1(
            trading_account_id=7,
            venue="bitvavo",
            strategy_bucket_id="SHORT_TERM_ROTATION",
            strategy_id="strategy-a",
            strategy_version="1",
        ),
        now_utc=TS,
    )

    assert seen == ["AERO-EUR", "BTC-EUR"]
    assert conn.rollbacks == 1
    assert result is approved


@pytest.mark.parametrize(
    "forbidden_field,value",
    [
        ("account_mode", "paper"),
        ("account_enabled", True),
        ("live_trading_enabled", True),
        ("automatic_buy_execution_enabled", True),
        ("free_quote_balance_eur", "1000"),
        ("proposed_position_amount_eur", "250"),
        ("current_bucket_amount_eur", "0"),
        ("current_open_positions", 0),
        ("current_asset_exposure_pct", "0"),
        ("blocking_conflict", False),
    ],
)
def test_operator_json_cannot_supply_any_account_owned_field(forbidden_field: str, value: object) -> None:
    payload = _valid_payload()
    payload[forbidden_field] = value
    with pytest.raises(AutomaticBuyDryRunAcceptanceCliError, match="FORBIDDEN_OR_UNKNOWN_INPUT_FIELDS"):
        parse_source_request_from_json(payload)


def test_parser_accepts_exactly_the_bounded_source_field_set() -> None:
    payload = _valid_payload()
    request = parse_source_request_from_json(payload)
    assert request.trading_account_id == 7
    assert request.venue == "bitvavo"
    assert set(payload) <= ALLOWED_INPUT_KEYS


@pytest.mark.parametrize("forbidden_field,value", [
    ("evaluation_ts_utc", "2026-08-22T12:00:00+00:00"),
    ("setup_observed_ts_utc", "2026-08-22T12:00:00+00:00"),
    ("current_price", "100"),
    ("setup_evidence_id", "operator-evidence"),
    ("source_provenance", "operator"),
    ("free_quote_balance_eur", "1000"),
])
def test_fresh_source_json_rejects_operator_time_price_evidence_and_account_fields(
    forbidden_field: str, value: object,
) -> None:
    payload = _fresh_source_payload()
    payload[forbidden_field] = value
    with pytest.raises(AutomaticBuyDryRunAcceptanceCliError, match="FORBIDDEN_OR_UNKNOWN_FRESH_SOURCE_FIELDS"):
        parse_fresh_source_candidate_from_json(payload)


def test_fresh_source_parser_accepts_source_identity_only() -> None:
    payload = _fresh_source_payload()
    candidate = parse_fresh_source_candidate_from_json(payload)
    assert candidate.market == "BTC-EUR"
    assert candidate.entry_zone_low == Decimal("95")
    assert set(payload) <= FRESH_SOURCE_INPUT_KEYS


def test_canonical_zone_source_parser_accepts_identity_and_rejects_operator_geometry() -> None:
    payload = _canonical_zone_source_payload()
    candidate = parse_canonical_zone_source_request_from_json(payload)
    assert candidate.market == "BTC-EUR"
    assert set(payload) == CANONICAL_ZONE_SOURCE_INPUT_KEYS
    payload["entry_zone_low"] = "95"
    with pytest.raises(AutomaticBuyDryRunAcceptanceCliError, match="FORBIDDEN_OR_UNKNOWN_CANONICAL_ZONE_SOURCE_FIELDS"):
        parse_canonical_zone_source_request_from_json(payload)


def test_canonical_zone_universe_source_parser_accepts_identity_only() -> None:
    payload = _canonical_zone_universe_source_payload()
    candidate = parse_canonical_zone_universe_source_request_from_json(payload)
    assert candidate.strategy_bucket_id == "SHORT_TERM_ROTATION"
    assert set(payload) == CANONICAL_ZONE_UNIVERSE_SOURCE_INPUT_KEYS
    payload["market"] = "BTC-EUR"
    with pytest.raises(AutomaticBuyDryRunAcceptanceCliError, match="FORBIDDEN_OR_UNKNOWN_CANONICAL_ZONE_UNIVERSE_SOURCE_FIELDS"):
        parse_canonical_zone_universe_source_request_from_json(payload)


def _valid_payload() -> dict[str, object]:
    return {
        "evaluation_ts_utc": "2026-08-22T12:00:00+00:00",
        "trading_account_id": 7,
        "venue": "bitvavo",
        "asset_id": 101,
        "market": "BTC-EUR",
        "strategy_bucket_id": "SHORT_TERM_ROTATION",
        "strategy_id": "strategy-a",
        "strategy_version": "1",
        "setup_id": "setup-1",
        "setup_ready": True,
        "current_price": "100",
        "entry_zone_low": "95",
        "entry_zone_high": "105",
        "setup_evidence_id": "ev-1",
        "setup_observed_ts_utc": "2026-08-22T12:00:00+00:00",
        "source_provenance": "test",
    }


def _fresh_source_payload() -> dict[str, object]:
    return {
        "trading_account_id": 7,
        "venue": "bitvavo",
        "asset_id": 101,
        "market": "BTC-EUR",
        "strategy_bucket_id": "SHORT_TERM_ROTATION",
        "strategy_id": "strategy-a",
        "strategy_version": "1",
        "setup_id": "setup-1",
        "setup_ready": True,
        "entry_zone_low": "95",
        "entry_zone_high": "105",
    }


def _canonical_zone_source_payload() -> dict[str, object]:
    return {
        "trading_account_id": 7,
        "venue": "bitvavo",
        "asset_id": 101,
        "market": "BTC-EUR",
        "strategy_bucket_id": "SHORT_TERM_ROTATION",
        "strategy_id": "strategy-a",
        "strategy_version": "1",
    }


def _canonical_zone_universe_source_payload() -> dict[str, object]:
    return {
        "trading_account_id": 7,
        "venue": "bitvavo",
        "strategy_bucket_id": "SHORT_TERM_ROTATION",
        "strategy_id": "strategy-a",
        "strategy_version": "1",
    }
