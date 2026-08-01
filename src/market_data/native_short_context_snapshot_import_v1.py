from __future__ import annotations

"""Odroid-side import contract for the persisted native SHORT context snapshot.

This module owns the consumer-side half of the distribution boundary: taking
an already-fetched (staged) copy of gurkdb's canonical publication and, after
full schema/digest/identity validation, atomically installing it into the
local canonical path that Profit Plan reads.

It does not fetch, transport, or publish anything itself. It does not select
maps, calculate Fib geometry, evaluate candles, touch the database, call a
broker, or make account-aware decisions. It never deletes a previously
installed valid snapshot; the only mutable pointer is the canonical
manifest, and it is swapped last, atomically, only after the new snapshot
directory has been fully copied and independently re-validated in place.
"""

import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.market_data.native_short_fib_context_snapshot_v1 import (
    BUNDLE_NAME,
    MANIFEST_NAME,
    ROWS_NAME,
    SnapshotContractError,
    assert_no_symlink_components,
    validate_published_snapshot,
)


IMPORTER_NAME = "native_short_context_snapshot_import_v1"
IMPORTER_VERSION = "0.1"

RESULT_INSTALLED = "INSTALLED"
RESULT_UNCHANGED = "UNCHANGED"

SAFETY_MARKERS: dict[str, int | str | bool] = {
    "broker_private_calls": 0,
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "account_awareness": 0,
    "db_writes": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
    "market_truth_calculated": False,
}


class SnapshotImportError(ValueError):
    pass


class StaleSnapshotError(SnapshotImportError):
    pass


class WrongHostError(SnapshotImportError):
    pass


@dataclass(frozen=True)
class ImportResult:
    result: str
    snapshot_id: str
    content_digest: str
    publication_ts_utc: str
    row_count: int


def _path_lexists(path: Path) -> bool:
    return os.path.lexists(path)


def assert_expected_host(expected_host: str, actual_host: str) -> None:
    if not expected_host:
        raise WrongHostError("--expected-host is required; import fails closed without it")
    if expected_host != actual_host:
        raise WrongHostError(f"host mismatch: expected={expected_host} actual={actual_host}")


def _read_manifest(path: Path) -> dict[str, Any] | None:
    if not _path_lexists(path):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SnapshotImportError(f"installed canonical manifest is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise SnapshotImportError("installed canonical manifest must contain a top-level JSON object")
    return payload


def _parse_ts(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise SnapshotImportError(f"{label} is missing or invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotImportError(f"{label} is not a valid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise SnapshotImportError(f"{label} must be an absolute UTC timestamp: {value}")
    return parsed.astimezone(UTC)


def evaluate_staged_snapshot(
    staged_root: Path,
    *,
    canonical_root: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Validate the staged bundle and the currently-installed manifest.

    Returns (staged_manifest, installed_manifest_or_none). Raises
    SnapshotImportError (including StaleSnapshotError) without touching the
    canonical path.
    """
    validate_published_snapshot(staged_root)
    staged_manifest = _read_manifest(staged_root / MANIFEST_NAME)
    if staged_manifest is None:
        raise SnapshotImportError(f"staged manifest is missing: {staged_root / MANIFEST_NAME}")

    installed_manifest = _read_manifest(canonical_root / MANIFEST_NAME)
    if installed_manifest is None:
        return staged_manifest, None

    # The installed manifest, if present, must itself be a valid published
    # snapshot before we compare against it — a corrupt canonical state must
    # never be silently overwritten as if it were a routine install.
    validate_published_snapshot(canonical_root)

    if staged_manifest.get("snapshot_id") == installed_manifest.get("snapshot_id"):
        if staged_manifest.get("content_digest") != installed_manifest.get("content_digest"):
            raise SnapshotImportError("snapshot_id collision with different content_digest")
        return staged_manifest, installed_manifest

    staged_ts = _parse_ts(staged_manifest.get("publication_ts_utc"), label="staged publication_ts_utc")
    installed_ts = _parse_ts(installed_manifest.get("publication_ts_utc"), label="installed publication_ts_utc")
    if staged_ts < installed_ts:
        raise StaleSnapshotError(
            f"staged snapshot is older than installed: staged={staged_ts.isoformat()} "
            f"installed={installed_ts.isoformat()}"
        )
    return staged_manifest, installed_manifest


def _copy_snapshot_dir_atomic(
    *,
    staged_snapshot_dir: Path,
    canonical_snapshots_dir: Path,
    snapshot_id: str,
) -> Path:
    target_dir = canonical_snapshots_dir / snapshot_id
    if _path_lexists(target_dir):
        # Directory already present (e.g. re-install of the currently
        # installed snapshot after a same-id/same-digest match); nothing to
        # copy, canonical state is already correct for this snapshot.
        return target_dir
    canonical_snapshots_dir.mkdir(parents=True, exist_ok=True)
    assert_no_symlink_components(canonical_snapshots_dir)
    temp_dir = Path(
        tempfile.mkdtemp(prefix=f".{snapshot_id}.", suffix=".tmp", dir=canonical_snapshots_dir)
    )
    try:
        for name in (ROWS_NAME, BUNDLE_NAME):
            source = staged_snapshot_dir / name
            payload = source.read_bytes()
            dest = temp_dir / name
            dest.write_bytes(payload)
            os.chmod(dest, 0o440)
        os.chmod(temp_dir, 0o550)
        os.rename(temp_dir, target_dir)
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return target_dir


def _atomic_write_manifest(path: Path, payload: bytes) -> None:
    assert_no_symlink_components(path.parent)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fchmod(handle.fileno(), 0o640)
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def import_snapshot(
    *,
    staged_root: Path,
    canonical_root: Path,
    expected_host: str,
    actual_host: str,
) -> ImportResult:
    assert_expected_host(expected_host, actual_host)
    assert_no_symlink_components(staged_root)
    assert_no_symlink_components(canonical_root)

    staged_manifest, installed_manifest = evaluate_staged_snapshot(
        staged_root, canonical_root=canonical_root
    )
    snapshot_id = staged_manifest["snapshot_id"]

    if installed_manifest is not None and installed_manifest.get("snapshot_id") == snapshot_id:
        return ImportResult(
            result=RESULT_UNCHANGED,
            snapshot_id=snapshot_id,
            content_digest=staged_manifest.get("content_digest", ""),
            publication_ts_utc=staged_manifest.get("publication_ts_utc", ""),
            row_count=int(staged_manifest.get("row_count", 0)),
        )

    canonical_root.mkdir(parents=True, exist_ok=True)
    canonical_snapshots_dir = canonical_root / "snapshots"
    staged_snapshot_dir = staged_root / "snapshots" / snapshot_id

    installed_dir = _copy_snapshot_dir_atomic(
        staged_snapshot_dir=staged_snapshot_dir,
        canonical_snapshots_dir=canonical_snapshots_dir,
        snapshot_id=snapshot_id,
    )

    # Re-validate the freshly installed directory in place before the
    # manifest is ever repointed at it. Any failure here aborts before the
    # only mutable pointer (the manifest) is touched, so the previous valid
    # canonical state is untouched.
    for name in (ROWS_NAME, BUNDLE_NAME):
        installed_path = installed_dir / name
        if not installed_path.is_file() or stat.S_ISLNK(installed_path.lstat().st_mode):
            raise SnapshotImportError(f"installed snapshot artifact is unsafe: {installed_path}")

    manifest_payload = staged_root.joinpath(MANIFEST_NAME).read_bytes()
    _atomic_write_manifest(canonical_root / MANIFEST_NAME, manifest_payload)

    # Final independent re-validation of the canonical path exactly as a
    # downstream reader (Profit Plan) would see it.
    validated = validate_published_snapshot(canonical_root)
    if validated.snapshot_id != snapshot_id:
        raise SnapshotImportError("post-install canonical validation identity mismatch")

    return ImportResult(
        result=RESULT_INSTALLED,
        snapshot_id=snapshot_id,
        content_digest=staged_manifest.get("content_digest", ""),
        publication_ts_utc=staged_manifest.get("publication_ts_utc", ""),
        row_count=validated.row_count,
    )
