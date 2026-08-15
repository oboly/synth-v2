"""Backward-compatible import path for the shared executor resolver."""
from src.executor.execution_credential_scope_v1 import (  # noqa: F401
    BINDING_STATUS_ACTIVE,
    CREDENTIAL_STATUS_ACTIVE,
    TRADE_EXECUTION_SCOPE,
    CredentialScopeBinding,
    CredentialScopeDeniedError,
    ExecutorCredentialScopeRepository,
    _SCOPE_SELECT,
    _assert_credential_identity_match,
    _legacy_db_cursor,
    _row_to_binding,
    _unwrap_cursor,
)
