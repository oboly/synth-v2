from __future__ import annotations

import pytest

from src.executor.manual_execution_operator_identity_v1 import (
    BITVAVO_OPERATOR_ID_ENV,
    OperatorIdentityNotConfiguredError,
    resolve_operator_id,
)


def test_missing_env_fails_closed() -> None:
    with pytest.raises(OperatorIdentityNotConfiguredError, match="MISSING_BITVAVO_OPERATOR_ID"):
        resolve_operator_id(env={})


def test_non_integer_env_fails_closed() -> None:
    with pytest.raises(OperatorIdentityNotConfiguredError, match="INVALID_BITVAVO_OPERATOR_ID"):
        resolve_operator_id(env={BITVAVO_OPERATOR_ID_ENV: "not-an-int"})


def test_non_positive_env_fails_closed() -> None:
    with pytest.raises(OperatorIdentityNotConfiguredError):
        resolve_operator_id(env={BITVAVO_OPERATOR_ID_ENV: "0"})
    with pytest.raises(OperatorIdentityNotConfiguredError):
        resolve_operator_id(env={BITVAVO_OPERATOR_ID_ENV: "-5"})


def test_valid_env_resolves_explicit_operator_id() -> None:
    assert resolve_operator_id(env={BITVAVO_OPERATOR_ID_ENV: "12345"}) == 12345
