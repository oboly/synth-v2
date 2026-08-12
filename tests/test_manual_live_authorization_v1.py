from __future__ import annotations

import pytest

from src.executor.manual_live_authorization_v1 import (
    MANUAL_LIVE_AUTHORIZATION_HANDOFF_ID_ENV,
    ManualLiveAuthorizationDeniedError,
    require_manual_live_authorization,
)


def test_default_absent_env_is_denied() -> None:
    with pytest.raises(ManualLiveAuthorizationDeniedError):
        require_manual_live_authorization(handoff_id=42, env={})


def test_wrong_handoff_id_is_denied() -> None:
    with pytest.raises(ManualLiveAuthorizationDeniedError):
        require_manual_live_authorization(
            handoff_id=42, env={MANUAL_LIVE_AUTHORIZATION_HANDOFF_ID_ENV: "41"}
        )


def test_non_empty_but_non_matching_is_denied() -> None:
    with pytest.raises(ManualLiveAuthorizationDeniedError):
        require_manual_live_authorization(
            handoff_id=42, env={MANUAL_LIVE_AUTHORIZATION_HANDOFF_ID_ENV: "YES"}
        )


def test_exact_handoff_id_match_is_authorized() -> None:
    require_manual_live_authorization(
        handoff_id=42, env={MANUAL_LIVE_AUTHORIZATION_HANDOFF_ID_ENV: "42"}
    )
