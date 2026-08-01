from __future__ import annotations

from tests.writer_auth_support import make_test_authorization
_NS_AUTH = make_test_authorization("native_short_4h_chain")

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.market_data import native_short_fib_context_snapshot_v1 as snapshot
from src.market_data.native_short_context_snapshot_import_v1 import (
    RESULT_INSTALLED,
    RESULT_UNCHANGED,
    SnapshotImportError,
    StaleSnapshotError,
    WrongHostError,
    import_snapshot,
)


AS_OF = datetime(2026, 7, 16, 12, tzinfo=UTC)
HOST = "odroid"


@pytest.fixture(autouse=True)
def _authorized_writer_context(monkeypatch):
    from tests.writer_auth_support import install_authorized_writer_context
    install_authorized_writer_context(monkeypatch)
    monkeypatch.setattr(
        "src.market_data.native_short_fib_context_snapshot_v1._publication_identity_ids",
        lambda: (os.getuid(), os.getgid()),
    )


def _scope(symbol="BTC", **overrides):
    row = {
        "scope_id": 1,
        "venue": "bitvavo",
        "symbol": symbol,
        "quote_currency": "EUR",
        "fib_trading_horizon": "SHORT",
        "primary_interval": "4h",
        "supporting_interval": "1h",
        "scope_support_state": "NOT_SUPPORTED",
        "scope_reason_code": "SCOPE_NOT_SUPPORTED",
    }
    row.update(overrides)
    return row


def _build(*, symbol="BTC"):
    return snapshot.build_snapshot(
        scopes=[_scope(symbol=symbol)],
        maps_by_id={},
        levels_by_map_id={},
    )


def _publish(output_dir: Path, *, symbol="BTC", publication_ts_utc: datetime) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir.chmod(0o2750)
    build = _build(symbol=symbol)
    snapshot.publish_snapshot(
        build,
        output_dir=output_dir,
        generated_ts_utc=publication_ts_utc,
        publication_ts_utc=publication_ts_utc,
        authorization=_NS_AUTH,
    )


def _import(staged: Path, canonical: Path, *, expected_host: str = HOST, actual_host: str = HOST):
    return import_snapshot(
        staged_root=staged,
        canonical_root=canonical,
        expected_host=expected_host,
        actual_host=actual_host,
    )


def test_valid_import_installs_snapshot(tmp_path):
    staged = tmp_path / "staged"
    canonical = tmp_path / "canonical"
    _publish(staged, symbol="BTC", publication_ts_utc=AS_OF)

    result = _import(staged, canonical)

    assert result.result == RESULT_INSTALLED
    installed = snapshot.validate_published_snapshot(canonical)
    assert installed.snapshot_id == result.snapshot_id
    assert (canonical / "manifest_v1.json").is_file()


def test_corrupt_manifest_rejected_and_canonical_untouched(tmp_path):
    staged = tmp_path / "staged"
    canonical = tmp_path / "canonical"
    _publish(staged, symbol="BTC", publication_ts_utc=AS_OF)
    _publish(canonical, symbol="SOL", publication_ts_utc=AS_OF - timedelta(hours=8))
    before = (canonical / "manifest_v1.json").read_bytes()

    manifest_path = staged / "manifest_v1.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["content_digest"] = "sha256:" + "0" * 64
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(snapshot.SnapshotContractError):
        _import(staged, canonical)

    assert (canonical / "manifest_v1.json").read_bytes() == before


def test_corrupt_csv_rejected_and_canonical_untouched(tmp_path):
    staged = tmp_path / "staged"
    canonical = tmp_path / "canonical"
    _publish(staged, symbol="BTC", publication_ts_utc=AS_OF)
    _publish(canonical, symbol="SOL", publication_ts_utc=AS_OF - timedelta(hours=8))
    before = (canonical / "manifest_v1.json").read_bytes()

    manifest = json.loads((staged / "manifest_v1.json").read_text())
    rows_path = staged / manifest["rows_csv"]
    os.chmod(rows_path, 0o640)
    rows_path.write_bytes(rows_path.read_bytes() + b"garbage,row\n")
    os.chmod(rows_path, 0o440)

    with pytest.raises(snapshot.SnapshotContractError):
        _import(staged, canonical)

    assert (canonical / "manifest_v1.json").read_bytes() == before


def test_corrupt_bundle_rejected_and_canonical_untouched(tmp_path):
    staged = tmp_path / "staged"
    canonical = tmp_path / "canonical"
    _publish(staged, symbol="BTC", publication_ts_utc=AS_OF)
    _publish(canonical, symbol="SOL", publication_ts_utc=AS_OF - timedelta(hours=8))
    before = (canonical / "manifest_v1.json").read_bytes()

    manifest = json.loads((staged / "manifest_v1.json").read_text())
    bundle_path = staged / manifest["snapshot_bundle"]
    os.chmod(bundle_path, 0o640)
    bundle_path.write_bytes(b'{"envelope": {}, "rows": []}')
    os.chmod(bundle_path, 0o440)

    with pytest.raises(snapshot.SnapshotContractError):
        _import(staged, canonical)

    assert (canonical / "manifest_v1.json").read_bytes() == before


def test_partial_transfer_missing_bundle_rejected(tmp_path):
    staged = tmp_path / "staged"
    canonical = tmp_path / "canonical"
    _publish(staged, symbol="BTC", publication_ts_utc=AS_OF)
    _publish(canonical, symbol="SOL", publication_ts_utc=AS_OF - timedelta(hours=8))
    before = (canonical / "manifest_v1.json").read_bytes()

    manifest = json.loads((staged / "manifest_v1.json").read_text())
    bundle_path = staged / manifest["snapshot_bundle"]
    os.chmod(bundle_path.parent, 0o750)
    bundle_path.unlink()

    with pytest.raises(snapshot.SnapshotContractError):
        _import(staged, canonical)

    assert (canonical / "manifest_v1.json").read_bytes() == before


def test_stale_older_snapshot_rejected(tmp_path):
    staged = tmp_path / "staged"
    canonical = tmp_path / "canonical"
    _publish(canonical, symbol="BTC", publication_ts_utc=AS_OF)
    _publish(staged, symbol="SOL", publication_ts_utc=AS_OF - timedelta(hours=8))
    before = (canonical / "manifest_v1.json").read_bytes()

    with pytest.raises(StaleSnapshotError):
        _import(staged, canonical)

    assert (canonical / "manifest_v1.json").read_bytes() == before


def test_same_snapshot_idempotent(tmp_path):
    staged = tmp_path / "staged"
    canonical = tmp_path / "canonical"
    _publish(staged, symbol="BTC", publication_ts_utc=AS_OF)
    _publish(canonical, symbol="BTC", publication_ts_utc=AS_OF)

    result = _import(staged, canonical)

    assert result.result == RESULT_UNCHANGED


def test_rollback_preserves_previous_valid_snapshot_on_late_failure(tmp_path, monkeypatch):
    staged = tmp_path / "staged"
    canonical = tmp_path / "canonical"
    _publish(staged, symbol="BTC", publication_ts_utc=AS_OF)
    _publish(canonical, symbol="SOL", publication_ts_utc=AS_OF - timedelta(hours=8))
    before_manifest = (canonical / "manifest_v1.json").read_bytes()
    installed_before = snapshot.validate_published_snapshot(canonical)

    def _boom(path, payload):
        raise OSError("simulated crash during manifest swap")

    monkeypatch.setattr(
        "src.market_data.native_short_context_snapshot_import_v1._atomic_write_manifest",
        _boom,
    )

    with pytest.raises(OSError):
        _import(staged, canonical)

    assert (canonical / "manifest_v1.json").read_bytes() == before_manifest
    installed_after = snapshot.validate_published_snapshot(canonical)
    assert installed_after.snapshot_id == installed_before.snapshot_id


def test_wrong_host_rejected_before_any_write(tmp_path):
    staged = tmp_path / "staged"
    canonical = tmp_path / "canonical"
    _publish(staged, symbol="BTC", publication_ts_utc=AS_OF)

    with pytest.raises(WrongHostError):
        _import(staged, canonical, expected_host="odroid", actual_host="devlap")

    assert not canonical.exists()
