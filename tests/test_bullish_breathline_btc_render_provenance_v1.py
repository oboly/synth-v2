from __future__ import annotations

import hashlib
from pathlib import Path

import src.research.run_bullish_breathline_btc_render_canonical_4h_v1 as runner
from src.research import breathline_btc_alt_relationship_registry_v1_0_0_frozen as frozen_registry


EXPECTED_SHA256 = "baa1ff2093ed7d130944595babb67d1f696d1bd36296e442970d3c14dfc8656f"


def test_frozen_registry_snapshot_provenance_is_local_hashable_and_pinned() -> None:
    root = runner.repo_root()
    snapshot = root / runner.FROZEN_RELATIONSHIP_REGISTRY_SOURCE_FILE

    assert snapshot.is_file()
    assert snapshot == Path(frozen_registry.__file__).resolve()
    assert frozen_registry.REGISTRY_VERSION == "1.0.0"
    assert frozen_registry.REFERENCE_SYMBOL == "BTC"
    assert frozen_registry.ALT_SYMBOL == "RENDER"
    assert runner.REGISTRY_VERSION == frozen_registry.REGISTRY_VERSION
    assert runner.SYMBOLS == ("BTC", "RENDER")

    observed = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert observed == EXPECTED_SHA256
    assert runner.EXPECTED_FROZEN_RELATIONSHIP_REGISTRY_SHA256 == EXPECTED_SHA256
    assert runner.registry_source_sha256() == EXPECTED_SHA256


def test_original_prereg_commit_is_audit_metadata_not_runtime_dependency() -> None:
    assert runner.ORIGINAL_RELATIONSHIP_REGISTRY_COMMIT_SHA == (
        "ec9254a9d2bbb4f30f0d61e160ea035e193adfb4"
    )
