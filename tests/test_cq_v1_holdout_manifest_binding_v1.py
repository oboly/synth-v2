from __future__ import annotations

import hashlib

import pytest

from src.research.run_cq_v1_holdout_comparison_v1 import (
    PENDING_MANIFEST_SHA256,
    _validate_manifest_file_binding,
)


def test_manifest_file_binding_refuses_pending_protocol_hash(tmp_path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    protocol = {"inputs": {"frozen_manifest_sha256": PENDING_MANIFEST_SHA256}}
    with pytest.raises(ValueError, match="FROZEN_MANIFEST_NOT_YET_PINNED"):
        _validate_manifest_file_binding(protocol, manifest)


def test_manifest_file_binding_accepts_only_exact_pinned_bytes(tmp_path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"frozen":true}\n', encoding="utf-8")
    expected = hashlib.sha256(manifest.read_bytes()).hexdigest()
    protocol = {"inputs": {"frozen_manifest_sha256": expected}}
    assert _validate_manifest_file_binding(protocol, manifest) == expected

    manifest.write_text('{"frozen":false}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="FROZEN_MANIFEST_FILE_SHA256_MISMATCH"):
        _validate_manifest_file_binding(protocol, manifest)
