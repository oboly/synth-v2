from __future__ import annotations

"""Caller-ownership guard for run_linked_profile_dashboard_refresh_once.sh.

The legacy linked-profile dashboard refresh pipeline is retained ONLY as a
manual/acceptance workflow. No scheduled/runtime production caller is allowed:
no MVP runner, no linked-profile orchestrator, and no systemd service/timer
ExecStart may invoke it. This test fails if such a caller is introduced later.
"""

from pathlib import Path


REFRESH_SCRIPT_NAME = "run_linked_profile_dashboard_refresh_once.sh"
REFRESH_SCRIPT = Path("scripts/odroid") / REFRESH_SCRIPT_NAME

# The only executable script permitted to invoke the refresh pipeline.
ALLOWED_MANUAL_ACCEPTANCE_CALLERS = {
    Path("scripts/odroid/run_odroid_deployment_acceptance_v1.sh"),
}

# Runtime scripts that must never invoke it (direct guard for the key owners).
RUNTIME_SCRIPTS_MUST_NOT_CALL = (
    Path("scripts/odroid/run_mvp_dashboard_render_once.sh"),
    Path("scripts/odroid/run_mvp_readonly_pipeline_once.sh"),
    Path("scripts/odroid/run_linked_profile_runtime_orchestrator_once.sh"),
)

UNIT_DIRS = (
    Path("deploy/systemd"),
    Path("scripts/odroid/systemd"),
    Path("docs/ops/systemd"),
)


def _executable_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")]


def _invokes_refresh(path: Path) -> bool:
    """True if an executable (non-comment) line references the refresh script."""
    if not path.exists():
        return False
    return any(REFRESH_SCRIPT_NAME in line for line in _executable_lines(path.read_text(encoding="utf-8")))


def test_refresh_script_still_present() -> None:
    assert REFRESH_SCRIPT.is_file(), "linked-profile refresh script must be retained for manual/acceptance use"


def test_only_manual_acceptance_scripts_invoke_refresh() -> None:
    offenders = []
    for script in sorted(Path("scripts").rglob("*.sh")):
        if script in ALLOWED_MANUAL_ACCEPTANCE_CALLERS:
            continue
        if _invokes_refresh(script):
            offenders.append(str(script))
    assert not offenders, (
        "unexpected caller(s) of the linked-profile refresh pipeline "
        f"(only manual/acceptance callers allowed): {offenders}"
    )


def test_allowed_caller_actually_calls_it_and_is_acceptance_only() -> None:
    # Keep the allowlist honest: the named acceptance script must really call it.
    caller = next(iter(ALLOWED_MANUAL_ACCEPTANCE_CALLERS))
    assert _invokes_refresh(caller), f"allowed caller no longer invokes refresh: {caller}"
    assert "acceptance" in caller.name, "allowed caller must be an acceptance workflow"


def test_key_runtime_scripts_do_not_invoke_refresh() -> None:
    for script in RUNTIME_SCRIPTS_MUST_NOT_CALL:
        assert not _invokes_refresh(script), f"runtime script must not invoke refresh: {script}"


def test_no_systemd_unit_owns_refresh() -> None:
    offenders = []
    for unit_dir in UNIT_DIRS:
        if not unit_dir.exists():
            continue
        for unit in sorted(list(unit_dir.glob("*.service")) + list(unit_dir.glob("*.timer"))):
            for line in unit.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("ExecStart") and REFRESH_SCRIPT_NAME in line:
                    offenders.append(str(unit))
    assert not offenders, f"systemd unit(s) must not own the refresh pipeline: {offenders}"



def test_manual_refresh_shares_canonical_orchestrator_lock_domain() -> None:
    manual = REFRESH_SCRIPT.read_text(encoding="utf-8")
    orchestrator = Path("scripts/odroid/run_linked_profile_runtime_orchestrator_once.sh").read_text(encoding="utf-8")
    default_lock = "/tmp/synth-linked-profile-runtime-orchestrator.lock"
    assert default_lock in manual
    assert default_lock in orchestrator
    assert "SYNTH_LINKED_PROFILE_RUNTIME_LOCK" in manual
    assert "SYNTH_LINKED_PROFILE_RUNTIME_LOCK" in orchestrator
    assert "flock -n 9" in manual
    assert "flock -n 9" in orchestrator

def main() -> None:
    for test in (
        test_refresh_script_still_present,
        test_only_manual_acceptance_scripts_invoke_refresh,
        test_allowed_caller_actually_calls_it_and_is_acceptance_only,
        test_key_runtime_scripts_do_not_invoke_refresh,
        test_no_systemd_unit_owns_refresh,
        test_manual_refresh_shares_canonical_orchestrator_lock_domain,
    ):
        test()
    print("ok")


if __name__ == "__main__":
    main()
