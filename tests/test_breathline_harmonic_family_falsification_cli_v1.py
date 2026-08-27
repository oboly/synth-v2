from __future__ import annotations

import json
import sys
from pathlib import Path

import src.research.run_breathline_harmonic_family_falsification_v1 as runner


def test_bind_cli_to_manifest_records_exact_user_facing_invocation(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    raw_args = [
        "--source-run-dir",
        "data/research/bullish_breathline_canonical_4h_v1/source-run",
        "--run-id",
        "harmonic-v1-test",
    ]

    implementation_hash = "a" * 64
    payload = runner._bind_cli_to_manifest(
        out_dir=out_dir,
        manifest={
            "runner_name": runner.RUNNER_NAME,
            "registry_version": "1.0.1",
            "analyzer_source_sha256": implementation_hash,
        },
        raw_args=raw_args,
    )

    expected = [
        sys.executable,
        "-m",
        "src.research.run_breathline_harmonic_family_falsification_v1",
        *raw_args,
    ]
    assert payload["cli"] == expected
    assert payload["implementation_source_sha256"] == implementation_hash
    assert len(payload["analysis_core_source_sha256"]) == 64
    assert len(payload["cli_wrapper_source_sha256"]) == 64

    stored = json.loads((out_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert stored["cli"] == expected
    assert stored["runner_name"] == runner.RUNNER_NAME
    assert stored["implementation_source_sha256"] == implementation_hash
    assert stored["analysis_core_source_sha256"] == payload["analysis_core_source_sha256"]
    assert stored["cli_wrapper_source_sha256"] == payload["cli_wrapper_source_sha256"]
