"""Shared test support for writer-capability authorization.

Provides a way to mint a *real* validated ``WriterMutationAuthorization`` for
tests (via the genuine ACCEPTANCE verification flow over a temporary git
checkout and a permit under an injected permit root), plus a helper to install
an "already authorized" context into a test module so that tests exercising
write mechanics run as if authorization were granted. The authorization denial
paths themselves are covered directly in
``tests/test_writer_capability_authorization_v1.py``.
"""
from __future__ import annotations

import functools
import json
import os
import subprocess
import tempfile
from pathlib import Path

from src.operations.writer_capability_authorization_v1 import (
    ExecutionMode,
    WriterMutationAuthorization,
    verify_writer_execution_authorization,
)

REPO = Path(__file__).resolve().parent.parent

_IDENTITY = {
    "public_price_snapshot": "public-price-snapshot-writer",
    "public_candle_freshness": "public-candle-freshness-writer",
    "market_rotation_pressure": "market-rotation-pressure-writer",
    "native_short_4h_chain": "native-short-4h-chain",
}


@functools.lru_cache(maxsize=1)
def _acceptance_env() -> tuple[Path, str, Path]:
    base = Path(tempfile.mkdtemp(prefix="synth-writer-auth-"))
    repo = base / "checkout"
    repo.mkdir()
    (repo / "f.txt").write_text("x\n", encoding="utf-8")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e",
    }
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=repo, check=True, env=env)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    permits = base / "permits"
    permits.mkdir()
    return repo, head, permits


def make_test_authorization(capability_id: str) -> WriterMutationAuthorization:
    """Mint a genuine validated ACCEPTANCE authorization context for tests."""
    repo, head, permits = _acceptance_env()
    permit = {
        "permit_version": "writer_capability_acceptance_permit_v1",
        "permit_id": "test-permit-0001",
        "issued_at_utc": "2020-01-01T00:00:00Z",
        "expiry_utc": "2999-01-01T00:00:00Z",
        "purpose": "ACCEPTANCE",
        "capability_id": capability_id,
        "capability_identity": _IDENTITY[capability_id],
        "acceptance_host": "devlap",
        "authorized_commit": head,
        "approval_reference": "test",
    }
    permit_path = permits / f"{capability_id}.json"
    permit_path.write_text(json.dumps(permit), encoding="utf-8")
    decision = verify_writer_execution_authorization(
        capability_id=capability_id,
        mode=ExecutionMode.ACCEPTANCE,
        repo_root=REPO,
        checkout_path=repo,
        acceptance_permit_path=permit_path,
        acceptance_permit_root=permits,
        actual_host="devlap",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert decision.allowed, decision.reasons
    assert decision.authorization is not None
    return decision.authorization


def registry_with_auth_file(
    tmp_path: Path,
    capability_id: str,
    auth_file: Path,
    *,
    authorize: bool = False,
    host: str = "devlap",
) -> Path:
    """Write a temporary registry whose capability authorization_guard points at
    ``auth_file``. This exercises the real registry-only production authorization
    path contract without any public/CLI/environment override.
    """
    reg = json.loads(
        (REPO / "deploy/ownership/writer_capability_ownership_v1.json").read_text(encoding="utf-8")
    )
    cap = next(c for c in reg["capabilities"] if c["capability_id"] == capability_id)
    cap["authorization_guard"]["authorization_file"] = str(auth_file)
    if authorize:
        cap["selected_host"] = host
        cap["acceptance_host"] = host
        cap["acceptance_status"] = "ACCEPTED"
        cap["production_runtime_owner"] = host
        cap["production_authorization_status"] = "AUTHORIZED"
        cap["runtime_lifecycle"] = "AUTHORIZED_INACTIVE"
        cap["production_decision_evidence"] = (
            "docs/ops/writer_capability_host_ownership_contract_v1.md#decision"
        )
    path = tmp_path / "registry_with_auth.json"
    path.write_text(json.dumps(reg, indent=2), encoding="utf-8")
    return path


def install_authorized_writer_context(monkeypatch) -> None:
    """Treat the module under test as already-authorized.

    Only the entry acquisition function is patched, and it returns a *genuine*
    validated :class:`WriterMutationAuthorization`. The real low-level guard
    ``require_writer_mutation_authorization`` is never patched, so mechanics
    tests still fail if a runner forgets to thread the context, threads None,
    threads the wrong context, or threads the wrong capability.
    """
    import src.operations.writer_capability_authorization_v1 as authmod

    monkeypatch.setattr(
        authmod,
        "require_capability_write_authorization",
        lambda capability_id, **kwargs: make_test_authorization(capability_id),
    )
