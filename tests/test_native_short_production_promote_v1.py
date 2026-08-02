"""Tests for the canonical native SHORT production activation wrapper
(``src.operations.run_native_short_production_promote_v1``).

This module is a narrow adapter: it derives immutable request identity from
the verified installed checkout and delegates unchanged to the existing
rollout CLI (``run_native_short_scope_administration_rollout_v1``) and the
canonical 4h chain script. These tests exercise the adapter's own contract
(argument derivation, symbol pre-check, stop-before-chain-on-failure,
determinism for idempotent reruns) via monkeypatched seams; they do not
re-test the rollout CLI's or the shared authorization module's own
mechanics, which are covered in their own test files.
"""
from __future__ import annotations

import json
import os
from typing import Any

import pytest

from src.market_data.native_short_repository_source_identity_v1 import (
    NativeShortRepositorySourceState,
)
import src.operations.run_native_short_production_promote_v1 as promote


FIXED_HEAD = "a" * 40
FIXED_TIMESTAMP = "2026-08-02T10:00:00Z"


class _RolloutMainRecorder:
    def __init__(self, return_code: int) -> None:
        self.return_code = return_code
        self.calls: list[list[str]] = []
        # One (execution_mode, capability_id) env snapshot per call, captured
        # from inside the call itself -- proves what the rollout CLI actually
        # observed, not just what the wrapper intended to set.
        self.env_snapshots: list[tuple[str | None, str | None]] = []

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(list(argv))
        self.env_snapshots.append(
            (
                os.environ.get("SYNTH_WRITER_EXECUTION_MODE"),
                os.environ.get("SYNTH_WRITER_CAPABILITY_ID"),
            )
        )
        return self.return_code


def _patch_readiness(
    monkeypatch: pytest.MonkeyPatch,
    *,
    hard_blockers: list[str] | None = None,
    warnings: list[str] | None = None,
) -> None:
    """Readiness is real, read-only, and reaches the network/DB; every
    promote test other than the readiness-integration tests below must stub
    it to a deterministic outcome so it never depends on host/DB state."""
    outcome = promote.readiness.ReadinessOutcome(
        hard_blockers=list(hard_blockers or []),
        warnings=list(warnings or []),
    )
    monkeypatch.setattr(promote.readiness, "evaluate_readiness", lambda: outcome)


def _patch_deterministic_seams(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rollout_rc: int = 0,
    chain_rc: int = 0,
    readiness_hard_blockers: list[str] | None = None,
    readiness_warnings: list[str] | None = None,
) -> tuple[_RolloutMainRecorder, list[tuple[Any, ...]]]:
    monkeypatch.setattr(
        promote,
        "inspect_running_repository_source",
        lambda: NativeShortRepositorySourceState(head_sha=FIXED_HEAD, status_porcelain=""),
    )
    monkeypatch.setattr(
        promote, "_commit_timestamp_utc", lambda repo_root, commit: FIXED_TIMESTAMP
    )
    _patch_readiness(
        monkeypatch, hard_blockers=readiness_hard_blockers, warnings=readiness_warnings
    )
    recorder = _RolloutMainRecorder(rollout_rc)
    monkeypatch.setattr(promote.rollout_cli, "main", recorder)

    chain_calls: list[tuple[Any, ...]] = []

    def fake_run_chain(repository_root):
        chain_calls.append((repository_root,))
        return chain_rc

    monkeypatch.setattr(promote, "_run_chain", fake_run_chain)
    return recorder, chain_calls


def _last_stdout_json(capsys: pytest.CaptureFixture) -> dict:
    out = capsys.readouterr().out.strip().splitlines()
    return json.loads(out[-1])


def test_unapproved_symbol_rejected_before_repository_inspection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def _boom():
        raise AssertionError("repository must not be inspected for an unapproved symbol")

    monkeypatch.setattr(promote, "inspect_running_repository_source", _boom)
    rc = promote.main(["FOOCOIN"])
    assert rc == 2
    doc = _last_stdout_json(capsys)
    assert doc["event"] == "FAILED"
    assert doc["reason_code"] == "UNAPPROVED_SYMBOL"


def test_no_symbols_requested_rejected(capsys: pytest.CaptureFixture) -> None:
    rc = promote.main([])
    assert rc == 2
    doc = _last_stdout_json(capsys)
    assert doc["event"] == "FAILED"


def test_approved_symbols_success_invokes_rollout_then_chain(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    recorder, chain_calls = _patch_deterministic_seams(monkeypatch)
    rc = promote.main(["eth", "xrp"])
    assert rc == 0
    assert len(recorder.calls) == 1
    argv = recorder.calls[0]
    assert "--write" in argv
    assert argv[argv.index("--repository-commit") + 1] == FIXED_HEAD
    assert argv[argv.index("--requested-at-utc") + 1] == FIXED_TIMESTAMP
    only_symbol_values = [
        argv[i + 1] for i, token in enumerate(argv) if token == "--only-symbol"
    ]
    assert only_symbol_values == ["ETH", "XRP"]
    assert len(chain_calls) == 1

    doc = _last_stdout_json(capsys)
    assert doc["event"] == "SUCCESS"
    assert doc["chain_invoked"] is True
    assert doc["symbols"] == ["ETH", "XRP"]


def test_rollout_failure_stops_before_chain(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    recorder, chain_calls = _patch_deterministic_seams(monkeypatch, rollout_rc=3)
    rc = promote.main(["ETH"])
    assert rc == 3
    assert len(recorder.calls) == 1
    assert chain_calls == []
    doc = _last_stdout_json(capsys)
    assert doc["event"] == "FAILED"
    assert doc["reason_code"] == "ROLLOUT_NOT_SUCCESSFUL"
    assert doc["chain_invoked"] is False


def test_chain_failure_after_rollout_success_is_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    recorder, chain_calls = _patch_deterministic_seams(monkeypatch, rollout_rc=0, chain_rc=5)
    rc = promote.main(["ETH"])
    assert rc == 5
    assert len(chain_calls) == 1
    doc = _last_stdout_json(capsys)
    assert doc["event"] == "FAILED"
    assert doc["reason_code"] == "CHAIN_NOT_SUCCESSFUL"
    assert doc["chain_invoked"] is True


def test_rerun_with_same_inputs_is_fully_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same commit + same symbols + same invoking user must reproduce a
    byte-identical rollout argv across two separate invocations, with no
    persisted run-state file -- the whole point of deriving provenance only
    from fixed inputs (see module docstring)."""
    recorder, _chain_calls = _patch_deterministic_seams(monkeypatch)
    promote.main(["ETH", "XRP"])
    first_argv = recorder.calls[0]
    promote.main(["ETH", "XRP"])
    second_argv = recorder.calls[1]
    assert first_argv == second_argv


def test_actor_id_derived_from_sudo_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUDO_USER", "gurk")
    recorder, _chain_calls = _patch_deterministic_seams(monkeypatch)
    promote.main(["ETH"])
    argv = recorder.calls[0]
    assert argv[argv.index("--actor-id") + 1] == "gurk"


def test_actor_type_and_trigger_type_are_fixed(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder, _chain_calls = _patch_deterministic_seams(monkeypatch)
    promote.main(["ETH"])
    argv = recorder.calls[0]
    assert argv[argv.index("--actor-type") + 1] == "HUMAN_OPERATOR"
    assert argv[argv.index("--trigger-type") + 1] == "MANUAL_CLI"


# ---------------------------------------------------------------------------
# Scoped writer runtime context (SYNTH_WRITER_EXECUTION_MODE /
# SYNTH_WRITER_CAPABILITY_ID): the rollout CLI's authorization boundary reads
# these from the environment and defaults to READ_ONLY (fail closed) when
# SYNTH_WRITER_EXECUTION_MODE is absent. The wrapper must set both only for
# the duration of the bounded rollout call and restore whatever value (or
# absence) preceded it, on both the success and the failure/exception path.
# ---------------------------------------------------------------------------

def test_rollout_observes_production_mode_and_capability_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SYNTH_WRITER_EXECUTION_MODE", raising=False)
    monkeypatch.delenv("SYNTH_WRITER_CAPABILITY_ID", raising=False)
    recorder, _chain_calls = _patch_deterministic_seams(monkeypatch)
    rc = promote.main(["ETH"])
    assert rc == 0
    assert recorder.env_snapshots == [("PRODUCTION", "native_short_4h_chain")]


def test_env_vars_restored_to_absent_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SYNTH_WRITER_EXECUTION_MODE", raising=False)
    monkeypatch.delenv("SYNTH_WRITER_CAPABILITY_ID", raising=False)
    _patch_deterministic_seams(monkeypatch)
    promote.main(["ETH"])
    assert "SYNTH_WRITER_EXECUTION_MODE" not in os.environ
    assert "SYNTH_WRITER_CAPABILITY_ID" not in os.environ


def test_env_vars_restored_to_prior_values_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNTH_WRITER_EXECUTION_MODE", "READ_ONLY")
    monkeypatch.setenv("SYNTH_WRITER_CAPABILITY_ID", "public_price_snapshot")
    _patch_deterministic_seams(monkeypatch)
    promote.main(["ETH"])
    assert os.environ["SYNTH_WRITER_EXECUTION_MODE"] == "READ_ONLY"
    assert os.environ["SYNTH_WRITER_CAPABILITY_ID"] == "public_price_snapshot"


def test_env_vars_restored_after_rollout_failure_return_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SYNTH_WRITER_EXECUTION_MODE", "READ_ONLY")
    monkeypatch.setenv("SYNTH_WRITER_CAPABILITY_ID", "public_price_snapshot")
    _patch_deterministic_seams(monkeypatch, rollout_rc=3)
    rc = promote.main(["ETH"])
    assert rc == 3
    assert os.environ["SYNTH_WRITER_EXECUTION_MODE"] == "READ_ONLY"
    assert os.environ["SYNTH_WRITER_CAPABILITY_ID"] == "public_price_snapshot"


def test_env_vars_restored_after_rollout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNTH_WRITER_EXECUTION_MODE", "READ_ONLY")
    monkeypatch.setenv("SYNTH_WRITER_CAPABILITY_ID", "public_price_snapshot")
    monkeypatch.setattr(
        promote,
        "inspect_running_repository_source",
        lambda: NativeShortRepositorySourceState(head_sha=FIXED_HEAD, status_porcelain=""),
    )
    monkeypatch.setattr(
        promote, "_commit_timestamp_utc", lambda repo_root, commit: FIXED_TIMESTAMP
    )
    _patch_readiness(monkeypatch)

    def _boom(argv: list[str]) -> int:
        raise RuntimeError("simulated rollout crash")

    monkeypatch.setattr(promote.rollout_cli, "main", _boom)

    with pytest.raises(RuntimeError):
        promote.main(["ETH"])

    assert os.environ["SYNTH_WRITER_EXECUTION_MODE"] == "READ_ONLY"
    assert os.environ["SYNTH_WRITER_CAPABILITY_ID"] == "public_price_snapshot"


def test_writer_runtime_context_never_touched_before_or_after_rollout_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scoped context must be active only around the rollout call itself
    -- never before symbol/repository validation, and never left set once
    ``main`` returns."""
    monkeypatch.delenv("SYNTH_WRITER_EXECUTION_MODE", raising=False)
    monkeypatch.delenv("SYNTH_WRITER_CAPABILITY_ID", raising=False)

    def _boom_inspect():
        assert "SYNTH_WRITER_EXECUTION_MODE" not in os.environ
        raise AssertionError("must not reach repository inspection for an unapproved symbol")

    monkeypatch.setattr(promote, "inspect_running_repository_source", _boom_inspect)
    rc = promote.main(["FOOCOIN"])
    assert rc == 2
    assert "SYNTH_WRITER_EXECUTION_MODE" not in os.environ
    assert "SYNTH_WRITER_CAPABILITY_ID" not in os.environ


# ---------------------------------------------------------------------------
# The rollout CLI's own DB-access ordering (verify checkout -> authorize ->
# connect) is unchanged and unweakened: when authorization is denied, no
# database connection is attempted, regardless of the wrapper's env context.
# ---------------------------------------------------------------------------

def test_no_db_connection_attempted_when_authorization_denied(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    import src.common.db as dbmod
    import src.market_data.run_native_short_scope_administration_rollout_v1 as rollout_mod
    import src.operations.writer_capability_authorization_v1 as authmod

    monkeypatch.setattr(
        promote,
        "inspect_running_repository_source",
        lambda: NativeShortRepositorySourceState(head_sha=FIXED_HEAD, status_porcelain=""),
    )
    monkeypatch.setattr(
        promote, "_commit_timestamp_utc", lambda repo_root, commit: FIXED_TIMESTAMP
    )
    _patch_readiness(monkeypatch)
    # verify_repository_commit_sha passes trivially -- checkout identity is
    # not what this test is proving.
    monkeypatch.setattr(rollout_mod, "verify_repository_commit_sha", lambda *a, **k: None)

    def _deny(capability_id, **kwargs):
        raise authmod.AuthorizationDenied(
            capability_id, authmod.ExecutionMode.PRODUCTION, ["denied for test"]
        )

    monkeypatch.setattr(authmod, "enforce_capability_write_authorization", _deny)

    def _boom_get_connection(*args, **kwargs):
        raise AssertionError("DB connection must not be attempted when authorization is denied")

    monkeypatch.setattr(dbmod, "get_connection", _boom_get_connection)

    chain_calls: list[Any] = []
    monkeypatch.setattr(
        promote, "_run_chain", lambda repository_root: chain_calls.append(repository_root) or 0
    )

    rc = promote.main(["ETH"])
    assert rc == 3
    assert chain_calls == []
    doc = _last_stdout_json(capsys)
    assert doc["chain_invoked"] is False


# ---------------------------------------------------------------------------
# Readiness gate and --force.
# ---------------------------------------------------------------------------

def test_readiness_hard_blockers_stop_promotion_before_rollout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    recorder, chain_calls = _patch_deterministic_seams(
        monkeypatch, readiness_hard_blockers=["REQUIRED_OBJECT_MISSING: x"]
    )
    rc = promote.main(["ETH"])
    assert rc == 1
    assert recorder.calls == []
    assert chain_calls == []
    doc = _last_stdout_json(capsys)
    assert doc["event"] == "FAILED"
    assert doc["reason_code"] == "READINESS_HARD_BLOCKERS"
    assert doc["force"] is False
    assert doc["chain_invoked"] is False
    assert "REQUIRED_OBJECT_MISSING: x" in doc["hard_blockers"]


def test_force_continues_past_readiness_hard_blockers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    recorder, chain_calls = _patch_deterministic_seams(
        monkeypatch, readiness_hard_blockers=["REQUIRED_OBJECT_MISSING: x"]
    )
    rc = promote.main(["--force", "ETH"])
    assert rc == 0
    assert len(recorder.calls) == 1
    assert len(chain_calls) == 1
    doc = _last_stdout_json(capsys)
    assert doc["event"] == "SUCCESS"
    assert doc["force"] is True


def test_force_recorded_but_not_folded_into_rollout_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """force=true must be visible in this wrapper's own result document, but
    must never change the rollout request's --metadata: metadata is part of
    the persisted administration request's immutable digest, and an
    already-committed scope (e.g. ETH/XRP, already COMMITTED in production)
    must keep replaying as OPERATION_ALREADY_COMPLETED regardless of whether
    a later invocation happens to pass --force."""
    recorder, _chain_calls = _patch_deterministic_seams(
        monkeypatch, readiness_hard_blockers=["X: y"]
    )
    promote.main(["ETH"])  # not forced; stops before rollout, no call recorded
    promote.main(["--force", "ETH"])
    assert len(recorder.calls) == 1
    argv = recorder.calls[0]
    assert argv[argv.index("--metadata") + 1] == "{}"


def test_warnings_never_block_promotion(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    recorder, chain_calls = _patch_deterministic_seams(
        monkeypatch, readiness_warnings=["PUBLIC_PRICE_STALE: x"]
    )
    rc = promote.main(["ETH"])
    assert rc == 0
    assert len(recorder.calls) == 1
    assert len(chain_calls) == 1
    doc = _last_stdout_json(capsys)
    assert doc["event"] == "SUCCESS"


def test_force_does_not_bypass_unapproved_symbol(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def _boom():
        raise AssertionError("must not evaluate readiness for an unapproved symbol")

    monkeypatch.setattr(promote.readiness, "evaluate_readiness", _boom)
    rc = promote.main(["--force", "FOOCOIN"])
    assert rc == 2
    doc = _last_stdout_json(capsys)
    assert doc["event"] == "FAILED"
    assert doc["reason_code"] == "UNAPPROVED_SYMBOL"
    assert doc["force"] is True


def test_force_does_not_bypass_authorization_denial(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    import src.common.db as dbmod
    import src.market_data.run_native_short_scope_administration_rollout_v1 as rollout_mod
    import src.operations.writer_capability_authorization_v1 as authmod

    monkeypatch.setattr(
        promote,
        "inspect_running_repository_source",
        lambda: NativeShortRepositorySourceState(head_sha=FIXED_HEAD, status_porcelain=""),
    )
    monkeypatch.setattr(
        promote, "_commit_timestamp_utc", lambda repo_root, commit: FIXED_TIMESTAMP
    )
    _patch_readiness(monkeypatch, hard_blockers=["X: y"])
    monkeypatch.setattr(rollout_mod, "verify_repository_commit_sha", lambda *a, **k: None)

    def _deny(capability_id, **kwargs):
        raise authmod.AuthorizationDenied(
            capability_id, authmod.ExecutionMode.PRODUCTION, ["denied for test"]
        )

    monkeypatch.setattr(authmod, "enforce_capability_write_authorization", _deny)

    def _boom_get_connection(*args, **kwargs):
        raise AssertionError("DB connection must not be attempted when authorization is denied")

    monkeypatch.setattr(dbmod, "get_connection", _boom_get_connection)
    chain_calls: list[Any] = []
    monkeypatch.setattr(
        promote, "_run_chain", lambda repository_root: chain_calls.append(repository_root) or 0
    )

    rc = promote.main(["--force", "ETH"])
    assert rc == 3
    assert chain_calls == []
    doc = _last_stdout_json(capsys)
    assert doc["chain_invoked"] is False


def test_force_still_requires_real_db_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--force overrides only the readiness stop; the rollout CLI's own
    inability to connect to the database must still surface as a failure,
    never as a silently-bypassed SUCCESS."""
    recorder, chain_calls = _patch_deterministic_seams(
        monkeypatch, rollout_rc=1, readiness_hard_blockers=["DB_CONNECTION_FAILED: x"]
    )
    rc = promote.main(["--force", "ETH"])
    assert rc == 1
    assert len(recorder.calls) == 1
    assert chain_calls == []


def test_readiness_evaluation_exception_treated_as_blocker_not_bypassed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """If the readiness runner itself cannot evaluate safely, that must never
    be silently treated as ready=true."""
    monkeypatch.setattr(
        promote,
        "inspect_running_repository_source",
        lambda: NativeShortRepositorySourceState(head_sha=FIXED_HEAD, status_porcelain=""),
    )
    monkeypatch.setattr(
        promote, "_commit_timestamp_utc", lambda repo_root, commit: FIXED_TIMESTAMP
    )

    def _boom():
        raise RuntimeError("READINESS_EVALUATION_FAILED")

    monkeypatch.setattr(promote.readiness, "evaluate_readiness", _boom)
    recorder = _RolloutMainRecorder(0)
    monkeypatch.setattr(promote.rollout_cli, "main", recorder)

    rc = promote.main(["ETH"])
    assert rc == 1
    assert recorder.calls == []
    doc = _last_stdout_json(capsys)
    assert doc["reason_code"] == "READINESS_HARD_BLOCKERS"
