from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.market_data import native_short_fib_context_snapshot_v1 as snapshot
from src.operations import run_native_short_snapshot_filesystem_preflight_v1 as preflight
from tests.test_native_short_fib_context_snapshot_v1 import AS_OF, _build
from tests.writer_auth_support import (
    install_authorized_writer_context,
    make_test_authorization,
)


_AUTHORIZATION = make_test_authorization("native_short_4h_chain")


@pytest.fixture(autouse=True)
def _authorized_writer_context(monkeypatch: pytest.MonkeyPatch) -> None:
    install_authorized_writer_context(monkeypatch)
    monkeypatch.setattr(
        snapshot,
        "_publication_identity_ids",
        lambda: (os.getuid(), os.getgid()),
    )


def _identity_contract() -> tuple[preflight.Identity, preflight.Identity, int]:
    uid = os.getuid()
    gid = os.getgid()
    publisher = preflight.Identity("gurk", uid, frozenset({gid}))
    consumer = preflight.Identity("theone", uid + 10_000, frozenset({gid}))
    return publisher, consumer, gid


def _publish(root: Path) -> snapshot.PublicationResult:
    root.mkdir()
    published = snapshot.publish_snapshot(
        _build(),
        output_dir=root,
        generated_ts_utc=AS_OF,
        publication_ts_utc=AS_OF,
        authorization=_AUTHORIZATION,
    )
    for parent in root.parents:
        if parent == Path("/tmp"):
            break
        if parent.lstat().st_uid == os.getuid():
            parent.chmod(0o750)
    return published


def _inspect(root: Path, *, consumer: preflight.Identity | None = None) -> preflight.PreflightResult:
    publisher, default_consumer, gid = _identity_contract()
    return preflight.inspect_snapshot_filesystem(
        root,
        publisher=publisher,
        consumers=(consumer or default_consumer,),
        reader_gid=gid,
        reader_group=preflight.READER_GROUP,
    )


def _failed(result: preflight.PreflightResult) -> set[str]:
    return {check.name for check in result.checks if check.status == preflight.FAIL}


def test_valid_snapshot_proves_consumer_read_and_write_rejection(tmp_path: Path) -> None:
    root = tmp_path / "native"
    _publish(root)

    result = _inspect(root)

    assert result.result == preflight.PASS
    assert _failed(result) == set()
    assert {evidence.mode for evidence in result.paths} >= {
        "0440",
        "0600",
        "0640",
        "2550",
        "2750",
    }


def test_corrupted_snapshot_fails_digest_validation(tmp_path: Path) -> None:
    root = tmp_path / "native"
    published = _publish(root)
    published.rows_path.chmod(snapshot.MANIFEST_MODE)
    published.rows_path.write_bytes(b"corrupt")
    published.rows_path.chmod(snapshot.IMMUTABLE_ARTIFACT_MODE)

    result = _inspect(root)

    assert result.result == preflight.FAIL
    assert "snapshot_digest" in _failed(result)


def test_same_uid_consumer_is_rejected_even_when_modes_are_read_only(tmp_path: Path) -> None:
    root = tmp_path / "native"
    _publish(root)
    publisher, _, gid = _identity_contract()
    same_uid_consumer = preflight.Identity("reporting-as-gurk", publisher.uid, frozenset({gid}))

    result = _inspect(root, consumer=same_uid_consumer)

    assert "same_uid_conflicts" in _failed(result)
    assert "consumer_write_rejection:reporting-as-gurk" in _failed(result)


def test_consumer_without_reader_group_cannot_read(tmp_path: Path) -> None:
    root = tmp_path / "native"
    _publish(root)
    _, consumer, _ = _identity_contract()
    ungrouped = preflight.Identity(consumer.name, consumer.uid, frozenset({consumer.uid}))

    result = _inspect(root, consumer=ungrouped)

    assert "reader_group_membership" in _failed(result)
    assert f"consumer_read:{consumer.name}" in _failed(result)


@pytest.mark.parametrize("mode", [0o660, 0o646])
def test_group_or_world_write_is_rejected(tmp_path: Path, mode: int) -> None:
    root = tmp_path / "native"
    published = _publish(root)
    published.manifest_path.chmod(mode)

    result = _inspect(root)

    assert "canonical_modes" in _failed(result)
    assert "group_world_write" in _failed(result)
    if mode & 0o020:
        assert "consumer_write_rejection:theone" in _failed(result)


def test_symlink_artifact_is_rejected_without_following_it(tmp_path: Path) -> None:
    root = tmp_path / "native"
    published = _publish(root)
    outside = tmp_path / "outside.csv"
    outside.write_text("outside", encoding="utf-8")
    published.rows_path.parent.chmod(snapshot.SNAPSHOTS_DIR_MODE)
    published.rows_path.unlink()
    published.rows_path.symlink_to(outside)
    published.rows_path.parent.chmod(snapshot.IMMUTABLE_SNAPSHOT_DIR_MODE)

    result = _inspect(root)

    assert "snapshot_tree_symlinks" in _failed(result)
    assert "snapshot_digest" in _failed(result)
    assert outside.read_text(encoding="utf-8") == "outside"


def test_extended_acl_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "native"
    published = _publish(root)
    real_listxattr = preflight.os.listxattr

    def listxattr(path: Path, *, follow_symlinks: bool = False) -> list[str]:
        if Path(path) == published.manifest_path:
            return ["system.posix_acl_access"]
        return list(real_listxattr(path, follow_symlinks=follow_symlinks))

    monkeypatch.setattr(preflight.os, "listxattr", listxattr)

    result = _inspect(root)

    assert "extended_acls" in _failed(result)


def test_preflight_module_has_no_mutating_filesystem_calls() -> None:
    source = Path(
        "src/operations/run_native_short_snapshot_filesystem_preflight_v1.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "chmod(",
        "chown(",
        "mkdir(",
        "replace(",
        "unlink(",
        "write_text(",
        "write_bytes(",
    ):
        assert forbidden not in source
