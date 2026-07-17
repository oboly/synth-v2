from __future__ import annotations

"""Guards proving the MVP cockpit render path owns only market-only surfaces.

After the linked-profile owner decoupling, run_mvp_dashboard_render_once.sh must:
- still render the entry-candidate dashboard and the about page;
- never invoke the legacy linked-profile refresh path;
- never write Profit Plan (profit-plan.html/json);
- never write linked-profile wallet/open-orders;
- never build or publish native SHORT context;
- never add account-refresh ownership;
- never touch any broker/order/decision/planner/executor path.
"""

import os
import subprocess
import tempfile
from pathlib import Path


SCRIPT_PATH = Path("scripts/odroid/run_mvp_dashboard_render_once.sh")

ENTRY_CANDIDATE_MODULE = "src.reporting.run_entry_candidate_static_dashboard_v1"
ABOUT_PAGE_MODULE = "src.reporting.run_synth_about_page_v1"

# Modules / scripts the cockpit path must never invoke after decoupling.
FORBIDDEN_TOKENS = (
    "run_linked_profile_dashboard_refresh_once",
    "run_account_wallet_dashboard_render_once",
    "run_account_wallet_snapshot_dashboard_render_once",
    "run_manual_short_trader_profit_plan_v1",
    "run_manual_short_trader_dashboard_v1",
    "run_account_wallet_dashboard_v1",
    "run_account_wallet_refresh",
    "run_native_short_fib_context_v1",
    "native_short_context_union",
    "run_broker_balance_snapshot_writer_v1",
    "run_broker_account_position_snapshot_writer_v1",
    "src.decision_gate",
    "src.execution_planner",
    "src.executor",
)


def _write_file(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)


def _prepare_fake_python(fake_bin: Path) -> None:
    _write_file(
        fake_bin / "python",
        """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

log_path = Path(os.environ["FAKE_LOG_PATH"])
with log_path.open("a", encoding="utf-8") as handle:
    handle.write(" ".join(sys.argv[1:]) + "\\n")

args = sys.argv[1:]
if len(args) >= 2 and args[0] == "-m":
    argv = args[2:]
    def arg_value(flag, default=""):
        if flag in argv:
            idx = argv.index(flag)
            if idx + 1 < len(argv):
                return argv[idx + 1]
        return default
    out_html = arg_value("--output-html")
    if out_html:
        p = Path(out_html)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("rendered", encoding="utf-8")
    raise SystemExit(0)
raise SystemExit(0)
""",
        mode=0o755,
    )


def test_cockpit_renders_market_surfaces_and_never_touches_linked_profile() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fake_bin = root / "bin"
        out = root / "www"
        log_path = root / "calls.log"
        _prepare_fake_python(fake_bin)

        entry_html = out / "entry-candidates.html"
        about_html = out / "about.html"
        cockpit_index = out / "index.html"

        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
        env["FAKE_LOG_PATH"] = str(log_path)
        env["SYNTH_ENTRY_CANDIDATE_DASHBOARD_HTML"] = str(entry_html)
        env["SYNTH_ABOUT_PAGE_HTML"] = str(about_html)
        env["SYNTH_COCKPIT_INDEX_HTML"] = str(cockpit_index)
        env["SYNTH_ABOUT_HERO_ASSET_OUTPUT"] = str(out / "hero.png")

        proc = subprocess.run(
            ["bash", str(SCRIPT_PATH)],
            env=env,
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr

        calls = log_path.read_text(encoding="utf-8").splitlines()
        # Legitimate market-only surfaces still render.
        assert any(ENTRY_CANDIDATE_MODULE in line for line in calls)
        assert any(ABOUT_PAGE_MODULE in line for line in calls)
        assert entry_html.exists()
        assert about_html.exists()

        # No forbidden module/script was ever invoked.
        joined = "\n".join(calls)
        for token in FORBIDDEN_TOKENS:
            assert token not in joined, f"cockpit invoked forbidden token: {token}"

        # No Profit Plan / wallet outputs were produced anywhere under the tmp tree.
        produced = {p.name for p in out.rglob("*") if p.is_file()}
        assert "profit-plan.html" not in produced
        assert "profit-plan.json" not in produced
        assert "wallet.html" not in produced
        assert "open-orders-monitor.html" not in produced


def test_cockpit_script_source_has_no_linked_profile_or_short_ownership() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert ENTRY_CANDIDATE_MODULE in source
    assert ABOUT_PAGE_MODULE in source
    # Only executable (non-comment) lines may invoke anything; documentation of the
    # decoupling is allowed to name the retired path in comments.
    executable = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    for token in FORBIDDEN_TOKENS:
        assert token not in executable, f"cockpit script invokes forbidden token: {token}"
    # Explicit ownership marker documents single ownership.
    assert "owned_by=synth-linked-profile-runtime-refresh.timer" in source


def main() -> None:
    for test in (
        test_cockpit_renders_market_surfaces_and_never_touches_linked_profile,
        test_cockpit_script_source_has_no_linked_profile_or_short_ownership,
    ):
        test()
    print("ok")


if __name__ == "__main__":
    main()
