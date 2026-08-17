from datetime import datetime, timedelta, timezone

import pytest

from src.executor.execution_live_authority_v1 import (
    _require_resolved_grant_match,
    _row_to_grant,
    _row_to_revocation,
    _validated_revocation_timestamp,
)


AS_OF_UTC = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def test_mariadb_naive_grant_timestamps_normalize_to_aware_utc() -> None:
    row = {
        "executor_live_authority_grant_id": 7,
        "trading_account_id": 17,
        "venue": "bitvavo",
        "side": "BUY",
        "market": "BTC-EUR",
        "executor_identity": "shared-executor-v1",
        "runtime_owner": "executor-host",
        "effective_from_ts_utc": datetime(2026, 8, 17, 11, 0),
        "effective_until_ts_utc": datetime(2026, 8, 17, 13, 0),
        "authorized_by": "operator-7",
        "authorization_reason": "bounded UTC regression",
        "created_ts_utc": datetime(2026, 8, 17, 10, 59),
    }

    grant = _row_to_grant(row)

    assert grant.effective_from_ts_utc == datetime(
        2026, 8, 17, 11, 0, tzinfo=timezone.utc
    )
    assert grant.effective_until_ts_utc == datetime(
        2026, 8, 17, 13, 0, tzinfo=timezone.utc
    )
    assert grant.created_ts_utc == datetime(
        2026, 8, 17, 10, 59, tzinfo=timezone.utc
    )

    resolved = _require_resolved_grant_match(
        grant,
        trading_account_id=17,
        venue="bitvavo",
        side="BUY",
        expected_market="BTC-EUR",
        executor_identity="shared-executor-v1",
        runtime_owner="executor-host",
        as_of_ts_utc=AS_OF_UTC,
    )
    assert resolved == grant


def test_mariadb_naive_revocation_timestamp_matches_aware_retry_identity() -> None:
    row = {
        "executor_live_authority_revocation_id": 11,
        "executor_live_authority_grant_id": 7,
        "revoked_ts_utc": datetime(2026, 8, 17, 12, 0),
        "revoked_by": "operator-7",
        "revocation_reason": "stop",
        "created_ts_utc": datetime(2026, 8, 17, 12, 0),
    }

    revocation = _row_to_revocation(row)

    assert revocation.revoked_ts_utc == AS_OF_UTC
    assert revocation.created_ts_utc == AS_OF_UTC


def test_future_revocation_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be in the future"):
        _validated_revocation_timestamp(
            AS_OF_UTC + timedelta(microseconds=1),
            AS_OF_UTC,
        )


def test_naive_past_revocation_timestamp_is_normalized_and_allowed() -> None:
    naive_past = datetime(2026, 8, 17, 11, 59, 59)
    assert _validated_revocation_timestamp(naive_past, AS_OF_UTC) == datetime(
        2026, 8, 17, 11, 59, 59, tzinfo=timezone.utc
    )
