from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from src.executor.execution_kill_switch_v1 import (
    ExecutionKillSwitchRepositoryV1,
    KILL_SWITCH_DISENGAGED,
    KILL_SWITCH_ENGAGED,
)
from src.executor.execution_live_authority_v1 import (
    MAX_LIVE_AUTHORITY_WINDOW,
    ExecutionLiveAuthorityAmbiguousError,
    ExecutionLiveAuthorityDeniedError,
    ExecutionLiveAuthorityRepositoryV1,
    require_execution_live_authority_v1,
)


NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


class _Backend:
    def __init__(self) -> None:
        self.grants: list[dict[str, Any]] = []
        self.revocations: list[dict[str, Any]] = []
        self.kill_events: list[dict[str, Any]] = []
        self.next_grant_id = 1
        self.next_revocation_id = 1
        self.next_kill_event_id = 1


class _Cursor:
    def __init__(self, backend: _Backend) -> None:
        self.backend = backend
        self._rows: list[dict[str, Any]] = []
        self.lastrowid: int | None = None

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        normalized = " ".join(sql.split())
        params = params or []
        backend = self.backend
        self._rows = []

        if normalized.startswith("INSERT INTO executor_live_authority_grant"):
            grant_id = backend.next_grant_id
            backend.next_grant_id += 1
            (
                account_id,
                venue,
                side,
                market,
                executor_identity,
                runtime_owner,
                effective_from,
                effective_until,
                authorized_by,
                reason,
            ) = params
            backend.grants.append(
                {
                    "executor_live_authority_grant_id": grant_id,
                    "trading_account_id": account_id,
                    "venue": venue,
                    "side": side,
                    "market": market,
                    "executor_identity": executor_identity,
                    "runtime_owner": runtime_owner,
                    "effective_from_ts_utc": effective_from,
                    "effective_until_ts_utc": effective_until,
                    "authorized_by": authorized_by,
                    "authorization_reason": reason,
                    "created_ts_utc": NOW,
                }
            )
            self.lastrowid = grant_id
            return
        if normalized.startswith(
            "SELECT * FROM executor_live_authority_grant WHERE"
        ):
            self._rows = [
                dict(row)
                for row in backend.grants
                if row["executor_live_authority_grant_id"] == params[0]
            ]
            return
        if normalized.startswith("SELECT grant.* FROM executor_live_authority_grant"):
            account_id, venue, side, executor_identity, runtime_owner = params[:5]
            as_of = params[5]
            requested_market = params[8] if "grant.market=%s" in normalized else None
            rows = []
            for row in backend.grants:
                if (
                    row["trading_account_id"] != account_id
                    or row["venue"] != venue
                    or row["side"] != side
                    or row["executor_identity"] != executor_identity
                    or row["runtime_owner"] != runtime_owner
                    or not row["effective_from_ts_utc"] <= as_of
                    or not as_of < row["effective_until_ts_utc"]
                    or row["market"] != requested_market
                ):
                    continue
                revoked = any(
                    rev["executor_live_authority_grant_id"]
                    == row["executor_live_authority_grant_id"]
                    and rev["revoked_ts_utc"] <= as_of
                    for rev in backend.revocations
                )
                if not revoked:
                    rows.append(dict(row))
            self._rows = rows
            return
        if normalized.startswith(
            "SELECT * FROM executor_live_authority_revocation WHERE executor_live_authority_grant_id"
        ):
            self._rows = [
                dict(row)
                for row in backend.revocations
                if row["executor_live_authority_grant_id"] == params[0]
            ]
            return
        if normalized.startswith("INSERT INTO executor_live_authority_revocation"):
            revocation_id = backend.next_revocation_id
            backend.next_revocation_id += 1
            grant_id, revoked_ts, revoked_by, reason = params
            backend.revocations.append(
                {
                    "executor_live_authority_revocation_id": revocation_id,
                    "executor_live_authority_grant_id": grant_id,
                    "revoked_ts_utc": revoked_ts,
                    "revoked_by": revoked_by,
                    "revocation_reason": reason,
                    "created_ts_utc": NOW,
                }
            )
            self.lastrowid = revocation_id
            return
        if normalized.startswith(
            "SELECT * FROM executor_live_authority_revocation WHERE executor_live_authority_revocation_id"
        ):
            self._rows = [
                dict(row)
                for row in backend.revocations
                if row["executor_live_authority_revocation_id"] == params[0]
            ]
            return
        if normalized.startswith("INSERT INTO executor_kill_switch_event"):
            event_id = backend.next_kill_event_id
            backend.next_kill_event_id += 1
            state, actor, reason, created_ts = params
            backend.kill_events.append(
                {
                    "executor_kill_switch_event_id": event_id,
                    "state": state,
                    "actor": actor,
                    "reason": reason,
                    "created_ts_utc": created_ts,
                }
            )
            self.lastrowid = event_id
            return
        if normalized.startswith(
            "SELECT * FROM executor_kill_switch_event WHERE executor_kill_switch_event_id"
        ):
            self._rows = [
                dict(row)
                for row in backend.kill_events
                if row["executor_kill_switch_event_id"] == params[0]
            ]
            return
        if normalized.startswith(
            "SELECT * FROM executor_kill_switch_event ORDER BY"
        ):
            if backend.kill_events:
                self._rows = [dict(backend.kill_events[-1])]
            return
        raise AssertionError(f"unexpected SQL: {normalized}")

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _Session:
    def __init__(self, backend: _Backend) -> None:
        self.backend = backend

    def __enter__(self) -> _Cursor:
        return _Cursor(self.backend)

    def __exit__(self, *_exc: Any) -> bool:
        return False


def _repositories(
    backend: _Backend | None = None,
) -> tuple[ExecutionLiveAuthorityRepositoryV1, ExecutionKillSwitchRepositoryV1, _Backend]:
    backend = backend or _Backend()
    factory = lambda **_kwargs: _Session(backend)
    return (
        ExecutionLiveAuthorityRepositoryV1(cursor_factory=factory),
        ExecutionKillSwitchRepositoryV1(cursor_factory=factory),
        backend,
    )


def _grant(repo: ExecutionLiveAuthorityRepositoryV1, **overrides: Any):
    values: dict[str, Any] = {
        "trading_account_id": 7,
        "venue": "bitvavo",
        "side": "BUY",
        "market": "BTC-EUR",
        "executor_identity": "shared-executor-v1",
        "runtime_owner": "executor-host",
        "effective_from_ts_utc": NOW - timedelta(hours=1),
        "effective_until_ts_utc": NOW + timedelta(hours=1),
        "authorized_by": "operator-7",
        "authorization_reason": "bounded acceptance fixture",
    }
    values.update(overrides)
    return repo.grant(**values)


def _require(
    authority: ExecutionLiveAuthorityRepositoryV1,
    kill_switch: ExecutionKillSwitchRepositoryV1,
    **overrides: Any,
):
    values: dict[str, Any] = {
        "trading_account_id": 7,
        "venue": "bitvavo",
        "side": "BUY",
        "market": "BTC-EUR",
        "executor_identity": "shared-executor-v1",
        "runtime_owner": "executor-host",
        "as_of_ts_utc": NOW,
        "authority_repository": authority,
        "kill_switch_repository": kill_switch,
    }
    values.update(overrides)
    return require_execution_live_authority_v1(**values)


@pytest.mark.parametrize(
    "grant_overrides",
    [
        {"effective_from_ts_utc": NOW + timedelta(minutes=1), "effective_until_ts_utc": NOW + timedelta(hours=1)},
        {"effective_from_ts_utc": NOW - timedelta(hours=2), "effective_until_ts_utc": NOW},
    ],
)
def test_future_and_expired_grants_are_denied(grant_overrides: dict[str, Any]) -> None:
    authority, kill_switch, _ = _repositories()
    _grant(authority, **grant_overrides)
    with pytest.raises(ExecutionLiveAuthorityDeniedError):
        _require(authority, kill_switch)


def test_no_grant_is_denied_and_valid_bounded_grant_is_allowed() -> None:
    authority, kill_switch, _ = _repositories()
    with pytest.raises(ExecutionLiveAuthorityDeniedError):
        _require(authority, kill_switch)
    expected = _grant(authority)
    assert _require(authority, kill_switch).grant_id == expected.grant_id


def test_grant_over_seven_days_is_rejected() -> None:
    authority, _, backend = _repositories()
    with pytest.raises(ValueError, match="MAX_LIVE_AUTHORITY_WINDOW"):
        _grant(
            authority,
            effective_from_ts_utc=NOW,
            effective_until_ts_utc=NOW + MAX_LIVE_AUTHORITY_WINDOW + timedelta(microseconds=1),
        )
    assert backend.grants == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"effective_until_ts_utc": None},
        {"effective_until_ts_utc": NOW - timedelta(hours=1)},
        {"side": "HOLD"},
        {"venue": "   "},
        {"executor_identity": ""},
        {"runtime_owner": ""},
        {"authorized_by": ""},
        {"authorization_reason": ""},
    ],
)
def test_invalid_or_unbounded_grant_is_rejected(overrides: dict[str, Any]) -> None:
    authority, _, backend = _repositories()
    with pytest.raises(ValueError):
        _grant(authority, **overrides)
    assert backend.grants == []


def test_revoked_grant_is_denied() -> None:
    authority, kill_switch, _ = _repositories()
    grant = _grant(authority)
    authority.revoke(
        grant_id=grant.grant_id,
        revoked_ts_utc=NOW,
        revoked_by="operator-7",
        revocation_reason="stop",
    )
    with pytest.raises(ExecutionLiveAuthorityDeniedError):
        _require(authority, kill_switch)


def test_revocation_retry_is_idempotent_without_mutating_history() -> None:
    authority, _, backend = _repositories()
    grant = _grant(authority)
    kwargs = {
        "grant_id": grant.grant_id,
        "revoked_ts_utc": NOW,
        "revoked_by": "operator-7",
        "revocation_reason": "stop",
    }
    first = authority.revoke(**kwargs)
    second = authority.revoke(**kwargs)
    assert first == second
    assert len(backend.revocations) == 1


def test_revocation_retry_without_explicit_timestamp_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, _, backend = _repositories()
    grant = _grant(authority)
    clock_values = iter((NOW, NOW + timedelta(seconds=1)))
    monkeypatch.setattr(
        "src.executor.execution_live_authority_v1.trusted_clock.utc_now",
        lambda: next(clock_values),
    )
    first = authority.revoke(
        grant_id=grant.grant_id,
        revoked_by="operator-7",
        revocation_reason="stop",
    )
    second = authority.revoke(
        grant_id=grant.grant_id,
        revoked_by="operator-7",
        revocation_reason="stop",
    )
    assert first == second
    assert len(backend.revocations) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("trading_account_id", 8),
        ("venue", "kraken"),
        ("side", "SELL"),
        ("executor_identity", "other-executor"),
        ("runtime_owner", "other-host"),
    ],
)
def test_wrong_non_market_identity_is_denied(field: str, value: Any) -> None:
    authority, kill_switch, _ = _repositories()
    _grant(authority)
    with pytest.raises(ExecutionLiveAuthorityDeniedError):
        _require(authority, kill_switch, **{field: value})


def test_exact_market_grant_matches_only_its_market() -> None:
    authority, kill_switch, _ = _repositories()
    _grant(authority)
    with pytest.raises(ExecutionLiveAuthorityDeniedError):
        _require(authority, kill_switch, market="ETH-EUR")


def test_wildcard_market_grant_matches_other_markets() -> None:
    authority, kill_switch, _ = _repositories()
    expected = _grant(authority, market=None)
    assert _require(authority, kill_switch, market="ETH-EUR").grant_id == expected.grant_id


def test_exact_effective_grant_overrides_wildcard() -> None:
    authority, kill_switch, _ = _repositories()
    _grant(authority, market=None)
    exact = _grant(authority, market="BTC-EUR")
    assert _require(authority, kill_switch).grant_id == exact.grant_id


@pytest.mark.parametrize("market", ["BTC-EUR", None])
def test_multiple_same_precedence_effective_grants_fail_closed(market: str | None) -> None:
    authority, kill_switch, _ = _repositories()
    _grant(authority, market=market)
    _grant(authority, market=market)
    with pytest.raises(ExecutionLiveAuthorityAmbiguousError):
        _require(authority, kill_switch)


def test_no_kill_events_is_not_engaged_and_engaged_denies_valid_grant() -> None:
    authority, kill_switch, _ = _repositories()
    _grant(authority)
    assert _require(authority, kill_switch)
    kill_switch.append_event(
        state=KILL_SWITCH_ENGAGED, actor="operator-7", reason="emergency"
    )
    with pytest.raises(ExecutionLiveAuthorityDeniedError, match="KILL_SWITCH_ENGAGED"):
        _require(authority, kill_switch)


def test_disengaged_after_engaged_allows_valid_grant() -> None:
    authority, kill_switch, _ = _repositories()
    expected = _grant(authority)
    kill_switch.append_event(
        state=KILL_SWITCH_ENGAGED, actor="operator-7", reason="emergency"
    )
    kill_switch.append_event(
        state=KILL_SWITCH_DISENGAGED, actor="operator-8", reason="reviewed clear"
    )
    assert _require(authority, kill_switch).grant_id == expected.grant_id


def test_disengaged_without_grant_remains_denied() -> None:
    authority, kill_switch, _ = _repositories()
    kill_switch.append_event(
        state=KILL_SWITCH_DISENGAGED, actor="operator-8", reason="reviewed clear"
    )
    with pytest.raises(ExecutionLiveAuthorityDeniedError):
        _require(authority, kill_switch)


class _FailingKillSwitch:
    def is_engaged(self) -> bool:
        raise OSError("database unavailable")


class _FailingAuthority:
    def resolve_effective(self, **_kwargs: Any):
        raise OSError("database unavailable")


def test_kill_switch_repository_failure_denies() -> None:
    authority, _, _ = _repositories()
    _grant(authority)
    with pytest.raises(ExecutionLiveAuthorityDeniedError, match="CHECK_FAILED"):
        _require(authority, _FailingKillSwitch())  # type: ignore[arg-type]


def test_authority_repository_failure_denies() -> None:
    _, kill_switch, _ = _repositories()
    with pytest.raises(ExecutionLiveAuthorityDeniedError, match="CHECK_FAILED"):
        _require(_FailingAuthority(), kill_switch)  # type: ignore[arg-type]
