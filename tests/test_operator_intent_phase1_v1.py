"""
Tests for operator_intent Phase 1 (Issue #262, parent #254).

Uses shared-memory SQLite (file::memory:?cache=shared), mirroring the
convention in tests/test_account_provisioning_service_v1.py, so command and
read paths run against a real (if lightweight) relational schema rather than
mocks.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import src.operator_intent.contracts_v1 as oi_contracts
from src.operator_intent.contracts_v1 import (
    AuthenticatedProfileIdentity,
    DuplicateActiveIntent,
    InvalidLifecycleTransition,
    IntentStatus,
    IntentType,
    OptimisticConcurrencyConflict,
    UnauthorizedOperatorIntentAccess,
    UnresolvedCanonicalIdentity,
)
from src.operator_intent.operator_intent_repository_v1 import SqliteOperatorIntentRepository
from src.operator_intent.operator_intent_service_v1 import OperatorIntentService


_NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)
_DB_COUNTER = [0]


def _next_db() -> str:
    _DB_COUNTER[0] += 1
    return f"opint_test_{_DB_COUNTER[0]}"


def _shared_conn(db_name: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_name}?mode=memory&cache=shared", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _seed_schema(db_name: str) -> sqlite3.Connection:
    conn = _shared_conn(db_name)
    SqliteOperatorIntentRepository(conn).create_schema()
    conn.commit()
    return conn


def _seed_user(conn: sqlite3.Connection, email: str) -> int:
    conn.execute("INSERT INTO app_user (email_normalized) VALUES (?)", (email,))
    conn.commit()
    return int(conn.execute("SELECT app_user_id FROM app_user WHERE email_normalized = ?", (email,)).fetchone()[0])


def _seed_profile(conn: sqlite3.Connection, profile_code: str) -> int:
    conn.execute("INSERT INTO app_profile (profile_code) VALUES (?)", (profile_code,))
    conn.commit()
    return int(
        conn.execute("SELECT app_profile_id FROM app_profile WHERE profile_code = ?", (profile_code,)).fetchone()[0]
    )


def _seed_access(conn: sqlite3.Connection, *, app_user_id: int, app_profile_id: int) -> None:
    conn.execute(
        "INSERT INTO app_user_profile_access (app_user_id, app_profile_id, access_role) VALUES (?, ?, 'OWNER')",
        (app_user_id, app_profile_id),
    )
    conn.commit()


def _seed_account(conn: sqlite3.Connection, *, account_code: str, venue: str = "bitvavo") -> int:
    conn.execute("INSERT INTO trading_account (account_code, venue) VALUES (?, ?)", (account_code, venue))
    conn.commit()
    return int(
        conn.execute(
            "SELECT trading_account_id FROM trading_account WHERE account_code = ?", (account_code,)
        ).fetchone()[0]
    )


def _seed_link(conn: sqlite3.Connection, *, app_profile_id: int, trading_account_id: int, status: str = "ACTIVE") -> None:
    conn.execute(
        """
        INSERT INTO app_profile_trading_account_link (app_profile_id, trading_account_id, link_status)
        VALUES (?, ?, ?)
        """,
        (app_profile_id, trading_account_id, status),
    )
    conn.commit()


def _service() -> OperatorIntentService:
    return OperatorIntentService(repo_factory=SqliteOperatorIntentRepository)


class _Fixture:
    """One fully-linked user/profile/account, ready to hold operator intent.

    conn_factory() opens a fresh connection to the same shared-memory DB on
    every call (mirroring test_account_provisioning_service_v1.py), because
    the service closes each connection it is given. self.conn is a separate,
    long-lived handle used only for direct test-side seeding/assertions.
    """

    def __init__(self, conn: sqlite3.Connection, *, db_name: str, email: str, profile_code: str, account_code: str, venue: str = "bitvavo"):
        self.conn = conn
        self.db_name = db_name
        self.app_user_id = _seed_user(conn, email)
        self.app_profile_id = _seed_profile(conn, profile_code)
        _seed_access(conn, app_user_id=self.app_user_id, app_profile_id=self.app_profile_id)
        self.trading_account_id = _seed_account(conn, account_code=account_code, venue=venue)
        _seed_link(conn, app_profile_id=self.app_profile_id, trading_account_id=self.trading_account_id)
        self.venue = venue
        self.identity = AuthenticatedProfileIdentity(
            app_user_id=self.app_user_id, app_profile_id=self.app_profile_id, profile_code=profile_code
        )

    def conn_factory(self) -> sqlite3.Connection:
        return _shared_conn(self.db_name)


def _make_fixture(db_name: str, **kwargs) -> _Fixture:
    conn = _seed_schema(db_name)
    kwargs["db_name"] = db_name
    return _Fixture(conn, **kwargs)


# ---------------------------------------------------------------------------
# Multi-account / multi-user / multi-venue isolation
# ---------------------------------------------------------------------------


def test_same_market_two_users_hold_independent_intents() -> None:
    db = _next_db()
    conn = _seed_schema(db)
    hugo = _Fixture(conn, db_name=db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    ada = _Fixture(conn, db_name=db, email="ada@example.com", profile_code="ada", account_code="ada-bitvavo")
    svc = _service()

    hugo_intent = svc.create_intent(
        identity=hugo.identity, trading_account_id=hugo.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
        conn_factory=hugo.conn_factory, now_utc=_NOW,
    )
    ada_intent = svc.create_intent(
        identity=ada.identity, trading_account_id=ada.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.DO_NOT_ADD.value,
        conn_factory=ada.conn_factory, now_utc=_NOW,
    )

    assert hugo_intent.operator_intent_id != ada_intent.operator_intent_id
    assert hugo_intent.intent_type == "BUY_PRIORITY"
    assert ada_intent.intent_type == "DO_NOT_ADD"

    hugo_reads = svc.read_current_intents(
        identity=hugo.identity, trading_account_id=hugo.trading_account_id, venue="bitvavo",
        conn_factory=hugo.conn_factory,
    )
    assert [r.operator_intent_id for r in hugo_reads] == [hugo_intent.operator_intent_id]

    ada_reads = svc.read_current_intents(
        identity=ada.identity, trading_account_id=ada.trading_account_id, venue="bitvavo",
        conn_factory=ada.conn_factory,
    )
    assert [r.operator_intent_id for r in ada_reads] == [ada_intent.operator_intent_id]


def test_same_user_two_trading_accounts_hold_independent_intents() -> None:
    db = _next_db()
    conn = _seed_schema(db)
    app_user_id = _seed_user(conn, "hugo@example.com")
    app_profile_id = _seed_profile(conn, "hugo")
    _seed_access(conn, app_user_id=app_user_id, app_profile_id=app_profile_id)
    account_a = _seed_account(conn, account_code="hugo-bitvavo-a")
    account_b = _seed_account(conn, account_code="hugo-bitvavo-b")
    _seed_link(conn, app_profile_id=app_profile_id, trading_account_id=account_a)
    _seed_link(conn, app_profile_id=app_profile_id, trading_account_id=account_b)
    identity = AuthenticatedProfileIdentity(app_user_id=app_user_id, app_profile_id=app_profile_id, profile_code="hugo")
    svc = _service()

    intent_a = svc.create_intent(
        identity=identity, trading_account_id=account_a, venue="bitvavo", canonical_market="WLD-EUR",
        intent_type=IntentType.BUY_PRIORITY.value, conn_factory=lambda: _shared_conn(db), now_utc=_NOW,
    )
    intent_b = svc.create_intent(
        identity=identity, trading_account_id=account_b, venue="bitvavo", canonical_market="WLD-EUR",
        intent_type=IntentType.BUY_PRIORITY.value, conn_factory=lambda: _shared_conn(db), now_utc=_NOW,
    )

    assert intent_a.operator_intent_id != intent_b.operator_intent_id
    assert intent_a.trading_account_id == account_a
    assert intent_b.trading_account_id == account_b

    reads_a = svc.read_current_intents(
        identity=identity, trading_account_id=account_a, venue="bitvavo", conn_factory=lambda: _shared_conn(db),
    )
    reads_b = svc.read_current_intents(
        identity=identity, trading_account_id=account_b, venue="bitvavo", conn_factory=lambda: _shared_conn(db),
    )
    assert [r.operator_intent_id for r in reads_a] == [intent_a.operator_intent_id]
    assert [r.operator_intent_id for r in reads_b] == [intent_b.operator_intent_id]


def test_same_market_across_venues_is_independent_scope(monkeypatch) -> None:
    """Venue is part of scope: the same account/market pair on two supported
    venues must not collide. Phase 1 ships with one supported venue
    (bitvavo); this proves the scope key itself is venue-aware rather than
    assuming a single-venue world, by temporarily allowing a second venue
    code the way a later venue-onboarding change would."""
    monkeypatch.setattr(oi_contracts, "SUPPORTED_VENUES", frozenset({"bitvavo", "otherventest"}))

    db = _next_db()
    conn = _seed_schema(db)
    app_user_id = _seed_user(conn, "hugo@example.com")
    app_profile_id = _seed_profile(conn, "hugo")
    _seed_access(conn, app_user_id=app_user_id, app_profile_id=app_profile_id)
    account_bitvavo = _seed_account(conn, account_code="hugo-bitvavo", venue="bitvavo")
    account_other = _seed_account(conn, account_code="hugo-other", venue="otherventest")
    _seed_link(conn, app_profile_id=app_profile_id, trading_account_id=account_bitvavo)
    _seed_link(conn, app_profile_id=app_profile_id, trading_account_id=account_other)
    identity = AuthenticatedProfileIdentity(app_user_id=app_user_id, app_profile_id=app_profile_id, profile_code="hugo")
    svc = _service()

    intent_a = svc.create_intent(
        identity=identity, trading_account_id=account_bitvavo, venue="bitvavo", canonical_market="WLD-EUR",
        intent_type=IntentType.BUY_PRIORITY.value, conn_factory=lambda: _shared_conn(db), now_utc=_NOW,
    )
    intent_b = svc.create_intent(
        identity=identity, trading_account_id=account_other, venue="otherventest", canonical_market="WLD-EUR",
        intent_type=IntentType.BUY_PRIORITY.value, conn_factory=lambda: _shared_conn(db), now_utc=_NOW,
    )
    assert intent_a.venue == "bitvavo"
    assert intent_b.venue == "otherventest"
    assert intent_a.operator_intent_id != intent_b.operator_intent_id


def test_unauthorized_account_access_fails_closed() -> None:
    db = _next_db()
    conn = _seed_schema(db)
    owner = _Fixture(conn, db_name=db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    stranger_user_id = _seed_user(conn, "stranger@example.com")
    stranger_profile_id = _seed_profile(conn, "stranger")
    _seed_access(conn, app_user_id=stranger_user_id, app_profile_id=stranger_profile_id)
    # Stranger has no app_profile_trading_account_link to owner's account at all.
    stranger_identity = AuthenticatedProfileIdentity(
        app_user_id=stranger_user_id, app_profile_id=stranger_profile_id, profile_code="stranger"
    )
    svc = _service()

    with pytest.raises(UnauthorizedOperatorIntentAccess):
        svc.create_intent(
            identity=stranger_identity, trading_account_id=owner.trading_account_id, venue="bitvavo",
            canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
            conn_factory=owner.conn_factory, now_utc=_NOW,
        )
    with pytest.raises(UnauthorizedOperatorIntentAccess):
        svc.read_current_intents(
            identity=stranger_identity, trading_account_id=owner.trading_account_id, venue="bitvavo",
            conn_factory=owner.conn_factory,
        )

    # No row was created by the failed attempt.
    owner_reads = svc.read_current_intents(
        identity=owner.identity, trading_account_id=owner.trading_account_id, venue="bitvavo",
        conn_factory=owner.conn_factory,
    )
    assert owner_reads == ()


def test_unauthorized_user_with_no_profile_access_fails_closed() -> None:
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    ghost_identity = AuthenticatedProfileIdentity(app_user_id=99999, app_profile_id=fx.app_profile_id, profile_code="hugo")
    svc = _service()

    with pytest.raises(UnauthorizedOperatorIntentAccess):
        svc.create_intent(
            identity=ghost_identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
            canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
            conn_factory=fx.conn_factory, now_utc=_NOW,
        )


def test_profile_slug_is_not_authoritative_persistence_key() -> None:
    """The stored scope is keyed on trading_account_id (a BIGINT FK), not on
    profile_code. Renaming the profile_code must not change intent identity."""
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    svc = _service()
    intent = svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    fx.conn.execute("UPDATE app_profile SET profile_code = 'hugo-renamed' WHERE app_profile_id = ?", (fx.app_profile_id,))
    fx.conn.commit()

    renamed_identity = AuthenticatedProfileIdentity(
        app_user_id=fx.app_user_id, app_profile_id=fx.app_profile_id, profile_code="hugo-renamed"
    )
    reads = svc.read_current_intents(
        identity=renamed_identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        conn_factory=fx.conn_factory,
    )
    assert [r.operator_intent_id for r in reads] == [intent.operator_intent_id]


def test_same_user_different_authorized_profiles_preserve_distinct_profile_audit_context() -> None:
    """A single app_user_id may hold access to more than one app_profile
    (the existing account model already supports this via
    app_user_profile_access). The effective authorized profile context —
    not just the user — must be preserved in both current-state and
    revision-history audit fields."""
    db = _next_db()
    conn = _seed_schema(db)
    app_user_id = _seed_user(conn, "hugo@example.com")
    profile_a_id = _seed_profile(conn, "hugo-personal")
    profile_b_id = _seed_profile(conn, "hugo-work")
    _seed_access(conn, app_user_id=app_user_id, app_profile_id=profile_a_id)
    _seed_access(conn, app_user_id=app_user_id, app_profile_id=profile_b_id)
    account_a = _seed_account(conn, account_code="hugo-personal-bitvavo")
    account_b = _seed_account(conn, account_code="hugo-work-bitvavo")
    _seed_link(conn, app_profile_id=profile_a_id, trading_account_id=account_a)
    _seed_link(conn, app_profile_id=profile_b_id, trading_account_id=account_b)
    identity_a = AuthenticatedProfileIdentity(app_user_id=app_user_id, app_profile_id=profile_a_id, profile_code="hugo-personal")
    identity_b = AuthenticatedProfileIdentity(app_user_id=app_user_id, app_profile_id=profile_b_id, profile_code="hugo-work")
    svc = _service()

    intent_a = svc.create_intent(
        identity=identity_a, trading_account_id=account_a, venue="bitvavo", canonical_market="WLD-EUR",
        intent_type=IntentType.BUY_PRIORITY.value, conn_factory=lambda: _shared_conn(db), now_utc=_NOW,
    )
    intent_b = svc.create_intent(
        identity=identity_b, trading_account_id=account_b, venue="bitvavo", canonical_market="WLD-EUR",
        intent_type=IntentType.BUY_PRIORITY.value, conn_factory=lambda: _shared_conn(db), now_utc=_NOW,
    )

    assert intent_a.created_by_app_user_id == app_user_id
    assert intent_b.created_by_app_user_id == app_user_id
    assert intent_a.created_by_app_profile_id == profile_a_id
    assert intent_b.created_by_app_profile_id == profile_b_id
    assert intent_a.created_by_app_profile_id != intent_b.created_by_app_profile_id

    updated_a = svc.update_intent(
        identity=identity_a, operator_intent_id=intent_a.operator_intent_id, expected_version=1,
        priority=7, conn_factory=lambda: _shared_conn(db), now_utc=_NOW,
    )
    assert updated_a.updated_by_app_profile_id == profile_a_id

    history_a = svc.read_revision_history(
        identity=identity_a, operator_intent_id=intent_a.operator_intent_id, conn_factory=lambda: _shared_conn(db),
    )
    assert [r.actor_app_profile_id for r in history_a] == [profile_a_id, profile_a_id]
    history_b = svc.read_revision_history(
        identity=identity_b, operator_intent_id=intent_b.operator_intent_id, conn_factory=lambda: _shared_conn(db),
    )
    assert [r.actor_app_profile_id for r in history_b] == [profile_b_id]


# ---------------------------------------------------------------------------
# Canonical identity validation
# ---------------------------------------------------------------------------


def test_canonical_identity_validation_rejects_bad_inputs() -> None:
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    svc = _service()

    with pytest.raises(UnresolvedCanonicalIdentity):
        svc.create_intent(
            identity=fx.identity, trading_account_id=fx.trading_account_id, venue="unsupported_venue",
            canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
            conn_factory=fx.conn_factory, now_utc=_NOW,
        )
    with pytest.raises(UnresolvedCanonicalIdentity):
        svc.create_intent(
            identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
            canonical_market="not a market", intent_type=IntentType.BUY_PRIORITY.value,
            conn_factory=fx.conn_factory, now_utc=_NOW,
        )
    with pytest.raises(ValueError):
        svc.create_intent(
            identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
            canonical_market="WLD-EUR", intent_type="NOT_A_REAL_INTENT_TYPE",
            conn_factory=fx.conn_factory, now_utc=_NOW,
        )
    # Linked-but-nonexistent trading_account_id (e.g. a dangling link row):
    # authorization passes the link check, but the account itself cannot be
    # resolved, so this must fail closed as unresolved identity, not silently
    # proceed.
    _seed_link(fx.conn, app_profile_id=fx.app_profile_id, trading_account_id=999999)
    with pytest.raises(UnresolvedCanonicalIdentity):
        svc.create_intent(
            identity=fx.identity, trading_account_id=999999, venue="bitvavo",
            canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
            conn_factory=fx.conn_factory, now_utc=_NOW,
        )


def test_venue_mismatch_between_request_and_account_fails_closed() -> None:
    db = _next_db()
    conn = _seed_schema(db)
    app_user_id = _seed_user(conn, "hugo@example.com")
    app_profile_id = _seed_profile(conn, "hugo")
    _seed_access(conn, app_user_id=app_user_id, app_profile_id=app_profile_id)
    trading_account_id = _seed_account(conn, account_code="hugo-bitvavo", venue="bitvavo")
    _seed_link(conn, app_profile_id=app_profile_id, trading_account_id=trading_account_id)
    identity = AuthenticatedProfileIdentity(app_user_id=app_user_id, app_profile_id=app_profile_id, profile_code="hugo")
    svc = _service()

    # Sanity: matching venue succeeds before we introduce the mismatch.
    svc.read_current_intents(
        identity=identity, trading_account_id=trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", conn_factory=lambda: _shared_conn(db),
    )

    # Force account venue to something else than what the request will use.
    conn.execute("UPDATE trading_account SET venue = 'othervenue' WHERE trading_account_id = ?", (trading_account_id,))
    conn.commit()
    with pytest.raises(UnresolvedCanonicalIdentity):
        svc.read_current_intents(
            identity=identity, trading_account_id=trading_account_id, venue="bitvavo", conn_factory=lambda: _shared_conn(db),
        )


# ---------------------------------------------------------------------------
# Duplicate / conflicting active intent
# ---------------------------------------------------------------------------


def test_duplicate_active_intent_same_scope_fails_closed() -> None:
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    svc = _service()
    svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    with pytest.raises(DuplicateActiveIntent):
        svc.create_intent(
            identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
            canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
            conn_factory=fx.conn_factory, now_utc=_NOW,
        )
    # Only one row exists — the failed attempt did not leak a partial write.
    reads = svc.read_current_intents(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        conn_factory=fx.conn_factory,
    )
    assert len(reads) == 1


def test_contradictory_intent_types_persist_without_decision_semantics() -> None:
    """Phase 1 validates structurally only. Two different intent_type values
    for the same market/account may both stay open — reconciling the
    contradiction is decision_gate's job in a later phase, not Phase 1's."""
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    svc = _service()
    buy = svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    do_not_add = svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.DO_NOT_ADD.value,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    reads = svc.read_current_intents(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        conn_factory=fx.conn_factory,
    )
    assert {r.operator_intent_id for r in reads} == {buy.operator_intent_id, do_not_add.operator_intent_id}


def test_cannot_create_intent_directly_in_terminal_status() -> None:
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    svc = _service()
    with pytest.raises(InvalidLifecycleTransition):
        svc.create_intent(
            identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
            canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
            status=IntentStatus.CANCELLED.value, conn_factory=fx.conn_factory, now_utc=_NOW,
        )


# ---------------------------------------------------------------------------
# Optimistic concurrency
# ---------------------------------------------------------------------------


def test_optimistic_concurrency_conflict_prevents_lost_update() -> None:
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    svc = _service()
    created = svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value, priority=1,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    assert created.version == 1

    first_update = svc.update_intent(
        identity=fx.identity, operator_intent_id=created.operator_intent_id, expected_version=1,
        priority=5, conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    assert first_update.version == 2
    assert first_update.priority == 5

    # A second writer that read the intent before the first update still
    # thinks the version is 1 — its write must fail, not silently overwrite.
    with pytest.raises(OptimisticConcurrencyConflict):
        svc.update_intent(
            identity=fx.identity, operator_intent_id=created.operator_intent_id, expected_version=1,
            priority=9, conn_factory=fx.conn_factory, now_utc=_NOW,
        )

    current = svc.read_current_intents(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        conn_factory=fx.conn_factory,
    )[0]
    assert current.priority == 5
    assert current.version == 2


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_cancel_intent_is_explicit_and_terminal() -> None:
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    svc = _service()
    created = svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    cancelled = svc.cancel_intent(
        identity=fx.identity, operator_intent_id=created.operator_intent_id, expected_version=1,
        reason="operator changed mind", conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    assert cancelled.status == IntentStatus.CANCELLED.value
    assert cancelled.reason == "operator changed mind"

    with pytest.raises(InvalidLifecycleTransition):
        svc.cancel_intent(
            identity=fx.identity, operator_intent_id=created.operator_intent_id, expected_version=2,
            conn_factory=fx.conn_factory, now_utc=_NOW,
        )

    # A cancelled scope is open again for a fresh intent.
    recreated = svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    assert recreated.operator_intent_id != created.operator_intent_id


# ---------------------------------------------------------------------------
# "Current intents" read model must exclude terminal rows (dedicated,
# isolated cases per intent-status; the cancel/expire/supersede tests above
# also cover this inline as part of their own lifecycle assertions).
# ---------------------------------------------------------------------------


def test_cancelled_intent_disappears_from_read_current_intents() -> None:
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    svc = _service()
    created = svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    svc.cancel_intent(
        identity=fx.identity, operator_intent_id=created.operator_intent_id, expected_version=1,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    assert svc.read_current_intents(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        conn_factory=fx.conn_factory,
    ) == ()
    assert svc.read_intent_by_id(
        identity=fx.identity, operator_intent_id=created.operator_intent_id, conn_factory=fx.conn_factory,
    ).status == IntentStatus.CANCELLED.value


def test_expired_intent_disappears_from_read_current_intents() -> None:
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    svc = _service()
    created = svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
        expires_ts_utc=_NOW + timedelta(hours=1), conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    svc.expire_due_intents(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        conn_factory=fx.conn_factory, now_utc=_NOW + timedelta(hours=2),
    )
    assert svc.read_current_intents(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        conn_factory=fx.conn_factory,
    ) == ()
    assert svc.read_intent_by_id(
        identity=fx.identity, operator_intent_id=created.operator_intent_id, conn_factory=fx.conn_factory,
    ).status == IntentStatus.EXPIRED.value


def test_superseded_old_intent_disappears_from_read_current_intents_replacement_visible() -> None:
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    svc = _service()
    original = svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.REENTRY_WATCH.value,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    replacement = svc.supersede_intent(
        identity=fx.identity, operator_intent_id=original.operator_intent_id, expected_version=1,
        new_intent_type=IntentType.BUY_LADDER_REQUESTED.value, conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    all_current = svc.read_current_intents(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        conn_factory=fx.conn_factory,
    )
    assert [r.operator_intent_id for r in all_current] == [replacement.operator_intent_id]
    assert svc.read_intent_by_id(
        identity=fx.identity, operator_intent_id=original.operator_intent_id, conn_factory=fx.conn_factory,
    ).status == IntentStatus.SUPERSEDED.value


def test_revision_history_contains_full_terminal_lifecycle() -> None:
    """History must retain terminal events even though read_current_intents
    no longer surfaces the terminal row itself."""
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    svc = _service()
    created = svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    svc.update_intent(
        identity=fx.identity, operator_intent_id=created.operator_intent_id, expected_version=1,
        priority=2, conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    svc.cancel_intent(
        identity=fx.identity, operator_intent_id=created.operator_intent_id, expected_version=2,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    history = svc.read_revision_history(
        identity=fx.identity, operator_intent_id=created.operator_intent_id, conn_factory=fx.conn_factory,
    )
    assert [r.event_type for r in history] == ["CREATED", "UPDATED", "CANCELLED"]
    assert history[-1].status == IntentStatus.CANCELLED.value


# ---------------------------------------------------------------------------
# Expiration
# ---------------------------------------------------------------------------


def test_expired_current_intent_transitions_via_explicit_command() -> None:
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    svc = _service()
    created = svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.REENTRY_WATCH.value,
        expires_ts_utc=_NOW + timedelta(hours=1), conn_factory=fx.conn_factory, now_utc=_NOW,
    )

    # Not yet due.
    result_early = svc.expire_due_intents(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    assert result_early.expired_intent_ids == ()

    later = _NOW + timedelta(hours=2)
    result_due = svc.expire_due_intents(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        conn_factory=fx.conn_factory, now_utc=later,
    )
    assert result_due.expired_intent_ids == (created.operator_intent_id,)

    # The expired intent is terminal — it must not leak through the "current
    # intents" read model, only through the explicit by-id / history reads.
    current = svc.read_current_intents(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        conn_factory=fx.conn_factory,
    )
    assert current == ()

    by_id = svc.read_intent_by_id(
        identity=fx.identity, operator_intent_id=created.operator_intent_id, conn_factory=fx.conn_factory,
    )
    assert by_id.status == IntentStatus.EXPIRED.value

    # A scope with an expired intent is open again for a fresh one.
    recreated = svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.REENTRY_WATCH.value,
        conn_factory=fx.conn_factory, now_utc=later,
    )
    assert recreated.operator_intent_id != created.operator_intent_id

    reads_after_recreate = svc.read_current_intents(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        conn_factory=fx.conn_factory,
    )
    assert [r.operator_intent_id for r in reads_after_recreate] == [recreated.operator_intent_id]


def test_set_and_clear_expiration() -> None:
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    svc = _service()
    created = svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    assert created.expires_ts_utc is None

    with_expiry = svc.set_expiration(
        identity=fx.identity, operator_intent_id=created.operator_intent_id, expected_version=1,
        expires_ts_utc=_NOW + timedelta(days=1), conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    assert with_expiry.expires_ts_utc is not None

    cleared = svc.clear_expiration(
        identity=fx.identity, operator_intent_id=created.operator_intent_id, expected_version=2,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    assert cleared.expires_ts_utc is None
    assert cleared.version == 3


# ---------------------------------------------------------------------------
# Supersession / append-only revision history
# ---------------------------------------------------------------------------


def test_supersede_intent_creates_lineage_and_append_only_history() -> None:
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    svc = _service()
    original = svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.REENTRY_WATCH.value, reason="watching pullback",
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    replacement = svc.supersede_intent(
        identity=fx.identity, operator_intent_id=original.operator_intent_id, expected_version=1,
        new_intent_type=IntentType.BUY_LADDER_REQUESTED.value, reason="reclaim confirmed",
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )

    assert replacement.intent_type == "BUY_LADDER_REQUESTED"
    assert replacement.supersedes_intent_id == original.operator_intent_id

    old_history = svc.read_revision_history(
        identity=fx.identity, operator_intent_id=original.operator_intent_id, conn_factory=fx.conn_factory,
    )
    assert [r.event_type for r in old_history] == ["CREATED", "SUPERSEDED"]
    assert old_history[-1].status == IntentStatus.SUPERSEDED.value

    new_history = svc.read_revision_history(
        identity=fx.identity, operator_intent_id=replacement.operator_intent_id, conn_factory=fx.conn_factory,
    )
    assert [r.event_type for r in new_history] == ["CREATED"]

    # The superseded old intent is terminal — it must not leak through the
    # "current intents" read model for its old (account, venue, market,
    # intent_type) scope.
    old_scope_current = svc.read_current_intents(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.REENTRY_WATCH.value, conn_factory=fx.conn_factory,
    )
    assert old_scope_current == ()

    old_current = svc.read_intent_by_id(
        identity=fx.identity, operator_intent_id=original.operator_intent_id, conn_factory=fx.conn_factory,
    )
    assert old_current.status == IntentStatus.SUPERSEDED.value
    assert old_current.superseded_by_intent_id == replacement.operator_intent_id

    # The replacement intent, in its own (new intent_type) scope, remains visible.
    new_scope_current = svc.read_current_intents(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.BUY_LADDER_REQUESTED.value, conn_factory=fx.conn_factory,
    )
    assert [r.operator_intent_id for r in new_scope_current] == [replacement.operator_intent_id]


def test_revision_history_is_append_only_and_unauthorized_read_fails_closed() -> None:
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    svc = _service()
    created = svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.BUY_PRIORITY.value,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    svc.update_intent(
        identity=fx.identity, operator_intent_id=created.operator_intent_id, expected_version=1,
        priority=3, conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    svc.cancel_intent(
        identity=fx.identity, operator_intent_id=created.operator_intent_id, expected_version=2,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    history = svc.read_revision_history(
        identity=fx.identity, operator_intent_id=created.operator_intent_id, conn_factory=fx.conn_factory,
    )
    assert [r.event_type for r in history] == ["CREATED", "UPDATED", "CANCELLED"]
    assert [r.revision_version for r in history] == [1, 2, 3]

    stranger_user_id = _seed_user(fx.conn, "stranger@example.com")
    stranger_profile_id = _seed_profile(fx.conn, "stranger")
    _seed_access(fx.conn, app_user_id=stranger_user_id, app_profile_id=stranger_profile_id)
    stranger_identity = AuthenticatedProfileIdentity(
        app_user_id=stranger_user_id, app_profile_id=stranger_profile_id, profile_code="stranger"
    )
    with pytest.raises(UnauthorizedOperatorIntentAccess):
        svc.read_revision_history(
            identity=stranger_identity, operator_intent_id=created.operator_intent_id, conn_factory=fx.conn_factory,
        )


# ---------------------------------------------------------------------------
# Wallet-zero independence
# ---------------------------------------------------------------------------


def test_wallet_balance_reaching_zero_never_implicitly_removes_intent() -> None:
    """Phase 1 has no wallet/balance coupling at all: operator_intent survives
    untouched regardless of wallet state, because nothing in this module
    reads or reacts to wallet balance."""
    db = _next_db()
    fx = _make_fixture(db, email="hugo@example.com", profile_code="hugo", account_code="hugo-bitvavo")
    svc = _service()
    created = svc.create_intent(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        canonical_market="WLD-EUR", intent_type=IntentType.HOLD_ONLY.value,
        conn_factory=fx.conn_factory, now_utc=_NOW,
    )
    # No wallet table, wallet column, or wallet call exists anywhere in this
    # package — there is nothing to "go to zero" that could cascade.
    for module_path in (
        _ROOT / "src" / "operator_intent" / "contracts_v1.py",
        _ROOT / "src" / "operator_intent" / "operator_intent_repository_v1.py",
        _ROOT / "src" / "operator_intent" / "operator_intent_service_v1.py",
    ):
        text = module_path.read_text().lower()
        assert "wallet" not in text
        assert "balance" not in text

    reads = svc.read_current_intents(
        identity=fx.identity, trading_account_id=fx.trading_account_id, venue="bitvavo",
        conn_factory=fx.conn_factory,
    )
    assert [r.operator_intent_id for r in reads] == [created.operator_intent_id]
    assert reads[0].intent_type == IntentType.HOLD_ONLY.value
    assert reads[0].status == IntentStatus.ACTIVE.value


# ---------------------------------------------------------------------------
# Layer boundary: no selection_engine / decision_gate / execution_planner /
# executor / broker / order dependency, in either direction.
# ---------------------------------------------------------------------------


_FORBIDDEN_DOWNSTREAM_FRAGMENTS = (
    "decision_gate",
    "execution_planner",
    "executor",
    "broker",
    "order_submit",
    "place_order",
)


def _collect_imports(path: Path) -> list[str]:
    """Mirrors tests/test_pipeline_contract_boundaries_v1.py::_collect_imports
    — checks actual import statements (AST), not docstrings/comments, so the
    module's own plain-text safety markers (e.g. 'decision_gate=none') don't
    false-positive this guard."""
    import ast

    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


def test_operator_intent_package_has_no_forbidden_downstream_imports() -> None:
    package_dir = _ROOT / "src" / "operator_intent"
    for py_file in sorted(package_dir.glob("*.py")):
        imports = _collect_imports(py_file)
        for imp in imports:
            for fragment in _FORBIDDEN_DOWNSTREAM_FRAGMENTS:
                assert fragment not in imp, f"{py_file} must not import {fragment!r} — found in {imp!r}"


def test_selection_engine_does_not_import_operator_intent() -> None:
    selection_dir = _ROOT / "src" / "selection"
    if not selection_dir.exists():
        pytest.skip("src/selection not present in this checkout")
    offending = []
    for py_file in selection_dir.rglob("*.py"):
        text = py_file.read_text()
        if "operator_intent" in text:
            offending.append(str(py_file))
    assert offending == [], f"selection_engine must not reference operator_intent: {offending}"
