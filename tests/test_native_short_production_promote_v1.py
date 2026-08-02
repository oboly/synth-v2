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

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(list(argv))
        return self.return_code


def _patch_deterministic_seams(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rollout_rc: int = 0,
    chain_rc: int = 0,
) -> tuple[_RolloutMainRecorder, list[tuple[Any, ...]]]:
    monkeypatch.setattr(
        promote,
        "inspect_running_repository_source",
        lambda: NativeShortRepositorySourceState(head_sha=FIXED_HEAD, status_porcelain=""),
    )
    monkeypatch.setattr(
        promote, "_commit_timestamp_utc", lambda repo_root, commit: FIXED_TIMESTAMP
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
