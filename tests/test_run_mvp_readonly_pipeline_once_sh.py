from __future__ import annotations

"""Regression guard for the MVP read-only pipeline after cockpit decoupling.

run_mvp_readonly_pipeline_once.sh must keep its intended stages, must keep
producing the market-only cockpit surfaces (entry-candidates + about via the
cockpit render), must propagate step failure truthfully, and must not regain
linked-profile ownership (linked-profile refresh, Profit Plan, linked-profile
wallet/open-orders, or native SHORT construction) directly or indirectly.
"""

import re
from pathlib import Path


SCRIPTS_DIR = Path("scripts")
PIPELINE = SCRIPTS_DIR / "odroid/run_mvp_readonly_pipeline_once.sh"
COCKPIT_RENDER = SCRIPTS_DIR / "odroid/run_mvp_dashboard_render_once.sh"

# Linked-profile ownership the MVP pipeline must never (re)acquire.
FORBIDDEN_TOKENS = (
    "run_linked_profile_dashboard_refresh_once",
    "run_account_wallet_dashboard_render_once",
    "run_account_wallet_snapshot_dashboard_render_once",
    "run_manual_short_trader_profit_plan_v1",
    "run_native_short_fib_context_v1",
    "native_short_context_union",
    "run_account_wallet_refresh",
    "run_market_price_snapshot_v1",
    "run_candles_etl",
    "run_chain_4h.sh",
    "run_native_short_scope_status_chain",
    "run_market_rotation_pressure_once",
)


def _executable_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")]


def _nested_scripts(text: str) -> list[Path]:
    """Return repo scripts invoked via `bash <path>` on executable lines."""
    found: list[Path] = []
    for line in _executable_lines(text):
        for match in re.findall(r"bash\s+(scripts/[^\s\"']+\.sh)", line):
            found.append(Path(match))
    return found


def _transitive_script_closure(entry: Path) -> set[Path]:
    seen: set[Path] = set()
    stack = [entry]
    while stack:
        current = stack.pop()
        if current in seen or not current.exists():
            continue
        seen.add(current)
        stack.extend(_nested_scripts(current.read_text(encoding="utf-8")))
    return seen


def test_pipeline_stages_present_and_ordered() -> None:
    text = PIPELINE.read_text(encoding="utf-8")
    ordered_markers = [
        "run_broker_balance_snapshot_writer_v1",
        "run_broker_account_position_snapshot_writer_v1",
        "run_decision_gate_position_source_audit_v1",
        "run_mvp_market_context_refresh_once.sh",
        "run_mvp_dashboard_render_once.sh",
    ]
    positions = []
    for marker in ordered_markers:
        idx = text.find(marker)
        assert idx != -1, f"pipeline missing required stage: {marker}"
        positions.append(idx)
    assert positions == sorted(positions), "pipeline stages are out of order"


def test_pipeline_renders_market_cockpit_surfaces() -> None:
    # The cockpit render (invoked by the pipeline) still owns entry-candidates + about.
    assert COCKPIT_RENDER in _transitive_script_closure(PIPELINE)
    cockpit = COCKPIT_RENDER.read_text(encoding="utf-8")
    assert "src.reporting.run_entry_candidate_static_dashboard_v1" in cockpit
    assert "src.reporting.run_synth_about_page_v1" in cockpit


def test_pipeline_propagates_step_failure() -> None:
    text = PIPELINE.read_text(encoding="utf-8")
    # run_step must exit with the failing status (truthful propagation).
    assert 'if [ "$status" -ne 0 ]; then' in text
    assert 'exit "$status"' in text


def test_pipeline_has_no_linked_profile_ownership_direct_or_indirect() -> None:
    closure = _transitive_script_closure(PIPELINE)
    # Prove decoupling propagated: the cockpit render is reached but no forbidden
    # linked-profile path appears on any executable line in the whole closure.
    assert PIPELINE in closure
    for script in sorted(closure):
        executable = "\n".join(_executable_lines(script.read_text(encoding="utf-8")))
        for token in FORBIDDEN_TOKENS:
            assert token not in executable, (
                f"{script} (reachable from MVP pipeline) invokes forbidden token: {token}"
            )


def main() -> None:
    for test in (
        test_pipeline_stages_present_and_ordered,
        test_pipeline_renders_market_cockpit_surfaces,
        test_pipeline_propagates_step_failure,
        test_pipeline_has_no_linked_profile_ownership_direct_or_indirect,
    ):
        test()
    print("ok")


if __name__ == "__main__":
    main()
