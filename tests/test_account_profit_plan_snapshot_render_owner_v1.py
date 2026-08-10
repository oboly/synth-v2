from __future__ import annotations

import fcntl
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import src.reporting.run_account_profit_plan_snapshot_render_owner_v1 as owner
from src.market_data.native_short_fib_context_snapshot_v1 import (
    BUNDLE_NAME,
    CSV_FIELDS,
    ROW_SCHEMA_VERSION,
    ROWS_NAME,
    SCHEMA_VERSION,
    canonical_json_bytes,
    render_rows_csv,
)


def _write_native_snapshot(root: Path, *, symbol: str = "BTC") -> tuple[Path, dict[str, object]]:
    row = {field: "" for field in CSV_FIELDS}
    row.update(
        {
            "symbol": symbol,
            "venue": "bitvavo",
            "quote_currency": "EUR",
            "fib_trading_horizon": "SHORT",
            "primary_interval": "4h",
            "supporting_interval": "1h",
            "context_status": "NATIVE_SHORT_CONTEXT_AVAILABLE",
            "context_freshness_status": "FRESH",
            "scope_support_state": "SUPPORTED",
        }
    )
    semantic_digest = hashlib.sha256(canonical_json_bytes({"rows": [row]})).hexdigest()
    snapshot_id = f"nsctx-v1-{semantic_digest[:24]}"
    snapshot_dir = root / "snapshots" / snapshot_id
    snapshot_dir.mkdir(parents=True)
    rows_payload = render_rows_csv([row])
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "row_schema_version": ROW_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "content_digest": f"sha256:{semantic_digest}",
        "row_count": 1,
    }
    bundle_payload = canonical_json_bytes({"envelope": envelope, "rows": [row]})
    rows_path = snapshot_dir / ROWS_NAME
    bundle_path = snapshot_dir / BUNDLE_NAME
    rows_path.write_bytes(rows_payload)
    bundle_path.write_bytes(bundle_payload)
    manifest: dict[str, object] = {
        **envelope,
        "rows_csv": str(Path("snapshots") / snapshot_id / ROWS_NAME),
        "rows_csv_digest": f"sha256:{hashlib.sha256(rows_payload).hexdigest()}",
        "snapshot_bundle": str(Path("snapshots") / snapshot_id / BUNDLE_NAME),
        "snapshot_bundle_digest": f"sha256:{hashlib.sha256(bundle_payload).hexdigest()}",
    }
    (root / "manifest_v1.json").write_bytes(canonical_json_bytes(manifest))
    return rows_path, manifest


def _args(tmp_path: Path, profile: str = "joost"):
    return owner.parse_args(
        [
            "--account-profile",
            profile,
            "--output-root",
            str(tmp_path / "web"),
            "--native-short-snapshot-root",
            str(tmp_path / "native"),
            "--lock-file",
            str(tmp_path / f"{profile}.lock"),
            "--metadata-path",
            str(tmp_path / "web" / "accounts" / profile / "_runtime" / "profit_plan_render_owner_v1" / "latest_run.json"),
            "--output",
            "none",
        ]
    )


def _renderer(
    calls: list[list[str]],
    *,
    render_id: str,
    delta_status: str,
    symbol: str = "BTC",
):
    def fake_run(command: list[str], check: bool):
        assert check is False
        calls.append(command)
        html_path = Path(command[command.index("--output-html") + 1])
        json_path = Path(command[command.index("--output-json") + 1])
        html_path.write_text(f"<html>{render_id}</html>", encoding="utf-8")
        json_path.write_text(
            json.dumps(
                {
                    "render_id": render_id,
                    "symbols": [
                        {
                            "symbol": symbol,
                            "delta": {"delta_status": delta_status},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0)

    return fake_run


def test_first_second_and_semantic_delta_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rows_path, _ = _write_native_snapshot(tmp_path / "native")
    args = _args(tmp_path)
    calls: list[list[str]] = []

    monkeypatch.setattr(
        owner.subprocess,
        "run",
        _renderer(calls, render_id="render-1", delta_status="NO_PREVIOUS_SNAPSHOT"),
    )
    assert owner.run(args) == 0
    first = json.loads(args.metadata_path.read_text(encoding="utf-8"))
    assert first["previous_snapshot_loaded"] is False
    assert first["delta_status_counts"] == {
        "NO_PREVIOUS_SNAPSHOT": 1,
        "UNCHANGED": 0,
        "UPDATED_NOW": 0,
    }
    assert "--previous-json" not in calls[-1]
    assert calls[-1][calls[-1].index("--native-short-context-rows") + 1] == str(rows_path.resolve())

    monkeypatch.setattr(
        owner.subprocess,
        "run",
        _renderer(calls, render_id="render-2", delta_status="UNCHANGED"),
    )
    assert owner.run(args) == 0
    second = json.loads(args.metadata_path.read_text(encoding="utf-8"))
    assert second["previous_snapshot_loaded"] is True
    assert second["previous_render_id"] == "render-1"
    assert second["current_render_id"] == "render-2"
    assert second["delta_status_counts"]["UNCHANGED"] == 1
    assert "--previous-json" in calls[-1]

    monkeypatch.setattr(
        owner.subprocess,
        "run",
        _renderer(calls, render_id="render-3", delta_status="UPDATED_NOW"),
    )
    assert owner.run(args) == 0
    changed = json.loads(args.metadata_path.read_text(encoding="utf-8"))
    assert changed["previous_render_id"] == "render-2"
    assert changed["current_render_id"] == "render-3"
    assert changed["delta_status_counts"]["UPDATED_NOW"] == 1
    assert changed["safety"] == owner.SAFETY_MARKERS


def test_corrupt_previous_json_fails_before_render_and_preserves_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_native_snapshot(tmp_path / "native")
    args = _args(tmp_path)
    profile_dir = args.output_root / "accounts" / "joost"
    profile_dir.mkdir(parents=True)
    html_path = profile_dir / "profit-plan.html"
    json_path = profile_dir / "profit-plan.json"
    html_path.write_text("last-html", encoding="utf-8")
    json_path.write_text('{"render_id":"old","symbols":"invalid"}', encoding="utf-8")
    before_json = json_path.read_bytes()
    calls: list[list[str]] = []
    monkeypatch.setattr(owner.subprocess, "run", _renderer(calls, render_id="never", delta_status="UNCHANGED"))

    assert owner.run(args) == 1
    assert calls == []
    assert html_path.read_text(encoding="utf-8") == "last-html"
    assert json_path.read_bytes() == before_json
    metadata = json.loads(args.metadata_path.read_text(encoding="utf-8"))
    assert metadata["result"] == "failed"


@pytest.mark.parametrize("mutation", ["digest", "path", "schema", "row_count"])
def test_invalid_manifest_authority_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    _, manifest = _write_native_snapshot(tmp_path / "native")
    if mutation == "digest":
        manifest["rows_csv_digest"] = "sha256:" + "0" * 64
    elif mutation == "path":
        manifest["rows_csv"] = "snapshots/../newest/native_short_fib_context_rows_v1.csv"
    elif mutation == "schema":
        manifest["schema_version"] = "wrong"
    else:
        manifest["row_count"] = 2
    (tmp_path / "native" / "manifest_v1.json").write_bytes(canonical_json_bytes(manifest))
    calls: list[list[str]] = []
    monkeypatch.setattr(owner.subprocess, "run", _renderer(calls, render_id="never", delta_status="UNCHANGED"))

    assert owner.run(_args(tmp_path)) == 1
    assert calls == []


def test_manifest_is_only_snapshot_pointer(tmp_path: Path) -> None:
    expected_rows, _ = _write_native_snapshot(tmp_path / "native")
    newest = tmp_path / "native" / "snapshots" / "nsctx-v1-newest"
    newest.mkdir(parents=True)
    (newest / ROWS_NAME).write_text("newest but unreferenced", encoding="utf-8")

    resolved = owner.validate_native_short_snapshot(tmp_path / "native")
    assert resolved.rows_path == expected_rows.resolve()
    assert resolved.rows_path.parent != newest


def test_profile_outputs_and_metadata_are_isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_native_snapshot(tmp_path / "native")
    calls: list[list[str]] = []
    monkeypatch.setattr(owner.subprocess, "run", _renderer(calls, render_id="joost-1", delta_status="NO_PREVIOUS_SNAPSHOT"))
    assert owner.run(_args(tmp_path, "joost")) == 0
    monkeypatch.setattr(owner.subprocess, "run", _renderer(calls, render_id="hugo-1", delta_status="NO_PREVIOUS_SNAPSHOT"))
    assert owner.run(_args(tmp_path, "hugo")) == 0

    joost = tmp_path / "web" / "accounts" / "joost"
    hugo = tmp_path / "web" / "accounts" / "hugo"
    assert json.loads((joost / "profit-plan.json").read_text(encoding="utf-8"))["render_id"] == "joost-1"
    assert json.loads((hugo / "profit-plan.json").read_text(encoding="utf-8"))["render_id"] == "hugo-1"
    assert (joost / "_runtime" / "profit_plan_render_owner_v1" / "latest_run.json").exists()
    assert (hugo / "_runtime" / "profit_plan_render_owner_v1" / "latest_run.json").exists()


def test_owner_source_guards_architecture_and_safety() -> None:
    source = Path("src/reporting/run_account_profit_plan_snapshot_render_owner_v1.py").read_text(encoding="utf-8")
    shell = Path("scripts/odroid/run_account_profit_plan_snapshot_render_once.sh").read_text(encoding="utf-8")
    combined = source + shell
    assert "run_native_short_fib_context_v1" not in combined
    assert "glob(" not in source
    assert "iterdir()" not in source.split("def validate_native_short_snapshot", 1)[1].split("def validate_profit_plan_snapshot", 1)[0]
    for forbidden in ("src.selection", "src.decision_gate", "src.execution_planner", "src.executor"):
        assert forbidden not in combined
    assert owner.SAFETY_MARKERS["broker_private_calls"] == 0
    assert owner.SAFETY_MARKERS["broker_writes"] == 0
    assert owner.SAFETY_MARKERS["order_submission"] == 0
    assert owner.SAFETY_MARKERS["live_orders"] == 0


def test_reporting_uses_evidence_based_native_snapshot_status(tmp_path: Path) -> None:
    from src.reporting.run_manual_short_trader_profit_plan_v1 import (
        native_short_snapshot_banner,
        summarize_native_short_snapshot_evidence,
    )

    rows_path, _ = _write_native_snapshot(tmp_path / "native")
    evidence = summarize_native_short_snapshot_evidence(
        markets=["BTC-EUR", "IOST-EUR"],
        rows_path=rows_path,
        canonical_status="loaded",
        snapshot_id="nsctx-v1-test",
    )
    assert evidence["canonical_snapshot_status"] == "loaded"
    assert evidence["native_context_available_count"] == 1
    assert evidence["native_context_supported_count"] == 1
    assert evidence["native_context_total_count"] == 2
    assert evidence["unsupported_or_unavailable_markets"] == ["IOST"]
    banner = native_short_snapshot_banner(evidence)
    assert "Canonical native SHORT snapshot loaded" in banner
    assert "Available 1 / supported 1 / total 2" in banner
    assert "Unsupported/unavailable markets: IOST" in banner

    missing_banner = native_short_snapshot_banner(
        {
            **evidence,
            "canonical_snapshot_status": "missing",
        }
    )
    assert "missing or invalid" in missing_banner
    assert "no candle-pipeline cause is inferred" in missing_banner
    source = Path("src/reporting/run_manual_short_trader_profit_plan_v1.py").read_text(encoding="utf-8")
    assert "check candle ETL pipeline" not in source
    assert "candle ETL may need to run" not in source


def test_default_lock_path_never_resolves_under_tmp_or_var_tmp(monkeypatch: pytest.MonkeyPatch) -> None:
    # pytest's own tmp_path fixture lives under the host /tmp, so use a
    # fake, non-filesystem-backed home to prove the *path arithmetic* never
    # routes through /tmp or /var/tmp regardless of the real $HOME.
    monkeypatch.setattr(owner.Path, "home", staticmethod(lambda: Path("/home/faketestuser")))
    lock_path = owner.default_lock_path("joost")
    assert lock_path == Path("/home/faketestuser/.config/synth/runtime/locks/account-profit-plan-snapshot-render-joost.lock")
    for forbidden in owner.LOCK_FORBIDDEN_ROOTS:
        with pytest.raises(ValueError):
            lock_path.relative_to(forbidden)


def test_validate_lock_path_rejects_tmp_and_var_tmp() -> None:
    with pytest.raises(ValueError, match="PrivateTmp"):
        owner.validate_lock_path(Path("/tmp/synth-account-profit-plan-snapshot-render-joost.lock"))
    with pytest.raises(ValueError, match="PrivateTmp"):
        owner.validate_lock_path(Path("/var/tmp/synth-account-profit-plan-snapshot-render-joost.lock"))
    owner.validate_lock_path(Path("/home/theone/.config/synth/runtime/locks/joost.lock"))


def test_missing_lock_file_arg_uses_home_default_outside_tmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # pytest's tmp_path lives under the host /tmp, so a fake $HOME under
    # tmp_path would defeat this test's purpose. /dev/shm is a distinct,
    # writable, non-/tmp, non-/var/tmp mount, so it stands in for a real
    # non-namespaced home directory.
    import shutil
    import tempfile

    fake_home = Path(tempfile.mkdtemp(prefix="synth-profit-plan-home-", dir="/dev/shm"))
    try:
        monkeypatch.setenv("HOME", str(fake_home))
        _write_native_snapshot(tmp_path / "native")
        args = owner.parse_args(
            [
                "--account-profile",
                "joost",
                "--output-root",
                str(tmp_path / "web"),
                "--native-short-snapshot-root",
                str(tmp_path / "native"),
                "--metadata-path",
                str(tmp_path / "web" / "accounts" / "joost" / "_runtime" / "profit_plan_render_owner_v1" / "latest_run.json"),
                "--output",
                "none",
            ]
        )
        assert args.lock_file is None
        calls: list[list[str]] = []
        monkeypatch.setattr(
            owner.subprocess, "run", _renderer(calls, render_id="render-1", delta_status="NO_PREVIOUS_SNAPSHOT")
        )
        assert owner.run(args) == 0
        expected_lock = fake_home / ".config" / "synth" / "runtime" / "locks" / "account-profit-plan-snapshot-render-joost.lock"
        assert expected_lock.exists()
        for forbidden in owner.LOCK_FORBIDDEN_ROOTS:
            with pytest.raises(ValueError):
                expected_lock.relative_to(forbidden)
    finally:
        shutil.rmtree(fake_home, ignore_errors=True)


def test_same_profile_second_run_is_skipped_while_lock_held(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_native_snapshot(tmp_path / "native")
    args = _args(tmp_path, "joost")
    args.lock_file.parent.mkdir(parents=True, exist_ok=True)
    holder = args.lock_file.open("a+b")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        calls: list[list[str]] = []
        monkeypatch.setattr(
            owner.subprocess, "run", _renderer(calls, render_id="render-1", delta_status="NO_PREVIOUS_SNAPSHOT")
        )
        assert owner.run(args) == 0
        assert calls == []
        assert not args.metadata_path.exists()
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()


def test_different_profiles_use_independent_locks_and_do_not_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_native_snapshot(tmp_path / "native")
    joost_args = _args(tmp_path, "joost")
    hugo_args = _args(tmp_path, "hugo")
    joost_args.lock_file.parent.mkdir(parents=True, exist_ok=True)
    holder = joost_args.lock_file.open("a+b")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        calls: list[list[str]] = []
        monkeypatch.setattr(
            owner.subprocess, "run", _renderer(calls, render_id="hugo-1", delta_status="NO_PREVIOUS_SNAPSHOT")
        )
        assert owner.run(hugo_args) == 0
        assert len(calls) == 1
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()


def test_lock_is_held_for_full_render_critical_section(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_native_snapshot(tmp_path / "native")
    args = _args(tmp_path, "joost")
    contention_observed: list[bool] = []

    def fake_run(command: list[str], check: bool):
        assert check is False
        probe = args.lock_file.open("a+b")
        try:
            fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            contention_observed.append(False)
            fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
        except BlockingIOError:
            contention_observed.append(True)
        finally:
            probe.close()
        html_path = Path(command[command.index("--output-html") + 1])
        json_path = Path(command[command.index("--output-json") + 1])
        html_path.write_text("<html>render-1</html>", encoding="utf-8")
        json_path.write_text(
            json.dumps({"render_id": "render-1", "symbols": [{"symbol": "BTC", "delta": {"delta_status": "NO_PREVIOUS_SNAPSHOT"}}]}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(owner.subprocess, "run", fake_run)
    assert owner.run(args) == 0
    assert contention_observed == [True]


def test_explicit_lock_file_override_is_not_rejected_even_under_tmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--lock-file is an explicit, trusted operator choice: the fail-closed
    /tmp guard only applies to the unset-argument default, matching the CLI
    contract already exercised by _args() (whose lock files live under
    pytest's tmp_path, itself typically under the host /tmp)."""
    _write_native_snapshot(tmp_path / "native")
    args = _args(tmp_path, "joost")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        owner.subprocess, "run", _renderer(calls, render_id="render-1", delta_status="NO_PREVIOUS_SNAPSHOT")
    )
    assert owner.run(args) == 0
    assert len(calls) == 1


def test_banner_separates_native_and_canonical_coverage_and_excludes_canonical_supported(
    tmp_path: Path,
) -> None:
    """Issue #223: a canonical-4h-supported symbol (e.g. AAVE) must not be listed
    as unsupported/unavailable in the top coverage banner. Native lifecycle
    coverage and canonical navigation coverage must be reported as separate,
    numerically correct counts, and explicit missing/stale/invalid symbols must
    remain in the unavailable list."""
    from src.reporting.run_manual_short_trader_profit_plan_v1 import (
        native_short_snapshot_banner,
        summarize_native_short_snapshot_evidence,
    )

    rows_path, _ = _write_native_snapshot(tmp_path / "native")
    evidence = summarize_native_short_snapshot_evidence(
        markets=["BTC-EUR", "AAVE-EUR", "MISS-EUR"],
        rows_path=rows_path,
        canonical_status="loaded",
        snapshot_id="nsctx-v1-test",
        canonical_supported_symbols={"AAVE"},
    )
    assert evidence["native_context_available_count"] == 1
    assert evidence["native_context_supported_count"] == 1
    assert evidence["native_context_total_count"] == 3
    assert evidence["canonical_navigation_supported_count"] == 1
    assert evidence["canonical_navigation_supported_markets"] == ["AAVE"]
    # AAVE is canonical-supported: it must not appear in the unsupported/unavailable list.
    assert "AAVE" not in evidence["unsupported_or_unavailable_markets"]
    # MISS has no native and no canonical coverage: it stays explicit/fail-closed.
    assert evidence["unsupported_or_unavailable_markets"] == ["MISS"]

    banner = native_short_snapshot_banner(evidence)
    assert "Available 1 / supported 1 / total 3" in banner
    assert "Canonical 4h navigation coverage: 1 contexts" in banner
    assert "Unsupported/unavailable markets: MISS" in banner
    assert "AAVE" not in banner.split("Unsupported/unavailable markets:")[-1]
