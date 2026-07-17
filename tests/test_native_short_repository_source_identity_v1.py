from __future__ import annotations

from typing import Any, Callable

import pytest

from src.market_data import run_native_short_map_level_status_materializer_v1 as level_runner
from src.market_data import run_native_short_map_materializer_v1 as map_runner
from src.market_data import run_native_short_map_scope_seed_canary_v1 as seed_runner
from src.market_data import run_native_short_scope_status_chain_v1 as chain_runner
from src.market_data.native_short_repository_source_identity_v1 import (
    NativeShortRepositorySourceIdentityError,
    NativeShortRepositorySourceState,
    verify_native_short_repository_source_identity,
)
from src.market_data.native_short_writer_provenance_v1 import (
    CANONICAL_REPOSITORY_WRITER_OWNER,
    CHAIN_TRIGGER_TYPE,
    MANUAL_MAP_TRIGGER_TYPE,
    NativeShortWriterExecutionMode,
    NativeShortWriterProvenance,
    build_explicit_test_provenance,
)


_COMMIT_SHA = "a" * 40
_CLEAN_SOURCE = NativeShortRepositorySourceState(
    head_sha=_COMMIT_SHA,
    status_porcelain="",
)


def _manual_provenance() -> NativeShortWriterProvenance:
    return NativeShortWriterProvenance(
        writer_entrypoint="src.market_data.run_native_short_map_materializer_v1",
        repository_writer_owner=CANONICAL_REPOSITORY_WRITER_OWNER,
        runner_name="run_native_short_map_materializer_v1",
        runner_version="0.1",
        execution_mode=NativeShortWriterExecutionMode.MANUAL,
        invocation_uuid="50000000-0000-4000-8000-000000000001",
        repository_commit_sha=_COMMIT_SHA,
        host_name="test-host",
        process_id=1,
        trigger_type=MANUAL_MAP_TRIGGER_TYPE,
        trigger_ref="source-identity-test",
    )


def _chain_provenance() -> NativeShortWriterProvenance:
    return NativeShortWriterProvenance(
        **{
            **_manual_provenance().__dict__,
            "writer_entrypoint": "scripts/run_chain_4h.sh",
            "runner_name": "run_native_short_scope_status_chain_v1",
            "execution_mode": NativeShortWriterExecutionMode.CHAIN,
            "invocation_uuid": "50000000-0000-4000-8000-000000000002",
            "trigger_type": CHAIN_TRIGGER_TYPE,
            "trigger_ref": "scripts/run_chain_4h.sh",
        }
    )


@pytest.mark.parametrize("provenance", (_manual_provenance(), _chain_provenance()))
def test_matching_clean_repository_head_passes(
    provenance: NativeShortWriterProvenance,
) -> None:
    assert verify_native_short_repository_source_identity(
        provenance,
        inspect_repository_source=lambda: _CLEAN_SOURCE,
    ) is provenance


def test_repository_commit_mismatch_fails_closed() -> None:
    with pytest.raises(
        NativeShortRepositorySourceIdentityError,
        match="REPOSITORY_COMMIT_MISMATCH",
    ):
        verify_native_short_repository_source_identity(
            _manual_provenance(),
            inspect_repository_source=lambda: NativeShortRepositorySourceState(
                head_sha="b" * 40,
                status_porcelain="",
            ),
        )


@pytest.mark.parametrize(
    ("status_porcelain", "expected_counts"),
    (
        ("M  src/market_data/writer.py", "staged=1 unstaged=0 untracked=0"),
        (" M src/market_data/writer.py", "staged=0 unstaged=1 untracked=0"),
        ("?? src/market_data/untracked_writer.py", "staged=0 unstaged=0 untracked=1"),
    ),
)
def test_dirty_repository_source_fails_closed(
    status_porcelain: str,
    expected_counts: str,
) -> None:
    with pytest.raises(
        NativeShortRepositorySourceIdentityError,
        match=expected_counts,
    ):
        verify_native_short_repository_source_identity(
            _manual_provenance(),
            inspect_repository_source=lambda: NativeShortRepositorySourceState(
                head_sha=_COMMIT_SHA,
                status_porcelain=status_porcelain,
            ),
        )


def test_unavailable_repository_identity_fails_closed() -> None:
    def unavailable() -> NativeShortRepositorySourceState:
        raise RuntimeError("git unavailable")

    with pytest.raises(
        NativeShortRepositorySourceIdentityError,
        match="REPOSITORY_IDENTITY_UNAVAILABLE",
    ):
        verify_native_short_repository_source_identity(
            _manual_provenance(),
            inspect_repository_source=unavailable,
        )


def test_test_mode_does_not_require_git_checkout() -> None:
    def forbidden() -> NativeShortRepositorySourceState:
        raise AssertionError("TEST provenance must not inspect Git")

    provenance = build_explicit_test_provenance()
    assert verify_native_short_repository_source_identity(
        provenance,
        inspect_repository_source=forbidden,
    ) is provenance


@pytest.mark.parametrize(
    "inspect_repository_source",
    (
        lambda: NativeShortRepositorySourceState("b" * 40, ""),
        lambda: NativeShortRepositorySourceState(_COMMIT_SHA, "M  staged.py"),
        lambda: NativeShortRepositorySourceState(_COMMIT_SHA, " M unstaged.py"),
        lambda: NativeShortRepositorySourceState(_COMMIT_SHA, "?? src/untracked.py"),
        lambda: (_ for _ in ()).throw(RuntimeError("git unavailable")),
    ),
)
def test_manual_runner_source_failure_precedes_database_access(
    monkeypatch: pytest.MonkeyPatch,
    inspect_repository_source: Callable[[], NativeShortRepositorySourceState],
) -> None:
    def forbidden_connection() -> Any:
        raise AssertionError("database touched before source identity verification")

    monkeypatch.setattr(map_runner, "get_connection", forbidden_connection)
    assert map_runner.main(
        [
            "--symbols",
            "BTC",
            "--execution-mode",
            "MANUAL",
            "--repository-commit",
            _COMMIT_SHA,
            "--trigger-ref",
            "source-identity-test",
        ],
        inspect_repository_source=inspect_repository_source,
    ) == 2


@pytest.mark.parametrize(
    ("runner", "argv", "forbidden_name"),
    (
        (
            level_runner,
            [
                "--venue", "bitvavo", "--symbols", "BTC", "--quote-currency", "EUR",
                "--fib-trading-horizon", "SHORT", "--primary-interval", "4h",
                "--supporting-interval", "1h", "--execution-mode", "MANUAL",
                "--repository-commit", _COMMIT_SHA, "--trigger-ref", "level-test",
            ],
            "_start_writer_run",
        ),
        (
            seed_runner,
            [
                "--symbols", "BTC", "--execution-mode", "MANUAL",
                "--repository-commit", _COMMIT_SHA, "--trigger-ref", "seed-test",
            ],
            "get_connection",
        ),
        (
            chain_runner,
            [
                "--venue", "bitvavo", "--quote-currency", "EUR",
                "--fib-trading-horizon", "SHORT", "--primary-interval", "4h",
                "--supporting-interval", "1h", "--execution-mode", "CHAIN",
                "--writer-entrypoint", "scripts/run_chain_4h.sh",
                "--repository-commit", _COMMIT_SHA,
                "--trigger-type", CHAIN_TRIGGER_TYPE,
                "--trigger-ref", "scripts/run_chain_4h.sh",
            ],
            "execute_runtime",
        ),
    ),
)
def test_every_other_production_runner_verifies_source_before_writer_access(
    monkeypatch: pytest.MonkeyPatch,
    runner: Any,
    argv: list[str],
    forbidden_name: str,
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("writer access preceded source identity verification")

    monkeypatch.setattr(runner, forbidden_name, forbidden)
    assert runner.main(
        argv,
        inspect_repository_source=lambda: NativeShortRepositorySourceState(
            head_sha="b" * 40,
            status_porcelain="",
        ),
    ) == 2
