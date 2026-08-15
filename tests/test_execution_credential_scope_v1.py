"""The manual import path is compatibility-only; resolution has one owner."""
from src.executor.execution_credential_scope_v1 import ExecutorCredentialScopeRepository
from src.executor.manual_execution_credential_scope_v1 import ExecutorCredentialScopeRepository as LegacyRepository

def test_manual_credential_scope_path_reexports_canonical_repository() -> None:
    assert LegacyRepository is ExecutorCredentialScopeRepository
