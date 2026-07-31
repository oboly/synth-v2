from __future__ import annotations

from pathlib import Path

from src.operations import run_native_short_systemd_equivalence_preflight_v1 as preflight


ROOT = Path(__file__).parent.parent


def _installed_state(
    unit: str,
    *,
    content: bytes | None = None,
    load_state: str = "loaded",
    drop_in_paths: str = "",
    unit_file_state: str = "disabled",
    active_state: str = "inactive",
) -> preflight.UnitState:
    return preflight.UnitState(
        unit=unit,
        load_state=load_state,
        fragment_path=f"/etc/systemd/system/{unit}" if load_state == "loaded" else "",
        drop_in_paths=drop_in_paths,
        unit_file_state=unit_file_state,
        active_state=active_state,
        content=content,
    )


def _canonical_states() -> dict[str, preflight.UnitState]:
    service = (ROOT / preflight.SERVICE_REL_PATH).read_bytes()
    timer = (ROOT / preflight.TIMER_REL_PATH).read_bytes()
    states = {
        preflight.SERVICE_UNIT: _installed_state(preflight.SERVICE_UNIT, content=service),
        preflight.TIMER_UNIT: _installed_state(preflight.TIMER_UNIT, content=timer),
    }
    for unit in preflight.LEGACY_UNITS:
        states[unit] = _installed_state(
            unit,
            content=None,
            load_state="not-found",
            unit_file_state="",
        )
    return states


def _run(states: dict[str, preflight.UnitState]) -> dict[str, preflight.CheckResult]:
    results = preflight.run_preflight(
        checkout_path=ROOT,
        systemctl="/usr/bin/systemctl",
        unit_loader=lambda unit, _systemctl: states[unit],
    )
    return {result.name: result for result in results}


def test_exact_canonical_inactive_pair_passes() -> None:
    results = _run(_canonical_states())
    assert results
    assert {result.status for result in results.values()} == {preflight.STATUS_PASS}
    assert "EnvironmentFile=()" in results["repository_service_contract"].detail
    assert "disabled/inactive" in results["timer_enabled_active_state"].detail


def test_timer_activates_service_only_on_timer_expiry() -> None:
    timer = (ROOT / preflight.TIMER_REL_PATH).read_bytes()
    fields = preflight._parse_unit(timer)

    assert fields.get(("Unit", "Requires"), ()) == ()
    assert fields.get(("Unit", "Wants"), ()) == ()
    assert fields.get(("Timer", "Unit")) == (preflight.SERVICE_UNIT,)
    assert preflight.EXPECTED_TIMER_FIELDS[("Unit", "Requires")] == ()
    assert preflight.EXPECTED_TIMER_FIELDS[("Unit", "Wants")] == ()
    assert _run(_canonical_states())["timer_activation_dependencies"].status == preflight.STATUS_PASS


def test_missing_service_and_drifted_timer_report_mismatch() -> None:
    states = _canonical_states()
    states[preflight.SERVICE_UNIT] = _installed_state(
        preflight.SERVICE_UNIT,
        content=None,
        load_state="not-found",
        unit_file_state="",
    )
    old_timer = states[preflight.TIMER_UNIT].content
    assert old_timer is not None
    states[preflight.TIMER_UNIT] = _installed_state(
        preflight.TIMER_UNIT,
        content=old_timer.replace(b"ConditionHost=gurkdb\n", b""),
    )

    results = _run(states)

    assert results["service_presence"].status == preflight.STATUS_FAIL
    assert results["service_content_sha256"].status == preflight.STATUS_FAIL
    assert results["service_user_group"].status == preflight.STATUS_FAIL
    assert results["timer_content_sha256"].status == preflight.STATUS_FAIL
    assert results["timer_host_condition"].status == preflight.STATUS_FAIL


def test_semantic_drift_is_reported_by_field() -> None:
    states = _canonical_states()
    service = states[preflight.SERVICE_UNIT].content
    assert service is not None
    changed = (
        service.replace(b"User=gurk\n", b"User=other\n")
        .replace(b"Group=gurk\n", b"Group=other\n")
        .replace(b"WorkingDirectory=/home/gurk/projects/synth-v2\n", b"WorkingDirectory=/tmp\n")
        .replace(
            b"ExecStart=/bin/bash /home/gurk/projects/synth-v2/scripts/run_chain_4h.sh\n",
            b"ExecStart=/usr/bin/false\n",
        )
    )
    states[preflight.SERVICE_UNIT] = _installed_state(
        preflight.SERVICE_UNIT,
        content=changed,
    )

    results = _run(states)

    assert results["service_user_group"].status == preflight.STATUS_FAIL
    assert "actual=('other',)" in results["service_user_group"].detail
    assert results["service_working_directory"].status == preflight.STATUS_FAIL
    assert results["service_command"].status == preflight.STATUS_FAIL


def test_environment_authorization_lock_cadence_and_host_drift_fail() -> None:
    states = _canonical_states()
    service = states[preflight.SERVICE_UNIT].content
    timer = states[preflight.TIMER_UNIT].content
    assert service is not None and timer is not None
    service = (
        service.replace(
            b"# EnvironmentFile is intentionally absent.",
            b"EnvironmentFile=/tmp/unsafe.env\n# EnvironmentFile is intentionally absent.",
        )
        .replace(b"SYNTH_CHAIN_4H_LOCK_FILE=/tmp/synth_chain_4h.lock", b"SYNTH_CHAIN_4H_LOCK_FILE=/tmp/other.lock")
        .replace(b"ExecStartPre=/home/gurk/projects/synth-v2/.venv/bin/python", b"ExecStartPre=/usr/bin/python")
    )
    timer = (
        timer.replace(b"ConditionHost=gurkdb", b"ConditionHost=other")
        .replace(b"00,04,08,12,16,20:12:00 UTC", b"*:00:00 UTC")
    )
    states[preflight.SERVICE_UNIT] = _installed_state(preflight.SERVICE_UNIT, content=service)
    states[preflight.TIMER_UNIT] = _installed_state(preflight.TIMER_UNIT, content=timer)

    results = _run(states)

    for name in (
        "service_authorization",
        "service_environment_files",
        "service_environment",
        "service_lock",
        "timer_cadence",
        "timer_host_condition",
    ):
        assert results[name].status == preflight.STATUS_FAIL


def test_drop_ins_enabled_active_state_and_legacy_units_fail_closed() -> None:
    states = _canonical_states()
    timer = states[preflight.TIMER_UNIT]
    states[preflight.TIMER_UNIT] = _installed_state(
        preflight.TIMER_UNIT,
        content=timer.content,
        drop_in_paths="/etc/systemd/system/synth-chain-4h.timer.d/override.conf",
        unit_file_state="enabled",
        active_state="active",
    )
    states[preflight.LEGACY_UNITS[1]] = _installed_state(
        preflight.LEGACY_UNITS[1],
        content=b"[Timer]\nOnCalendar=hourly\n",
    )

    results = _run(states)

    assert results["timer_drop_ins"].status == preflight.STATUS_FAIL
    assert results["timer_enabled_active_state"].status == preflight.STATUS_FAIL
    assert results["legacy_systemd_units_absent"].status == preflight.STATUS_FAIL


def test_systemctl_loader_uses_show_only(monkeypatch, tmp_path: Path) -> None:
    unit_path = tmp_path / preflight.SERVICE_UNIT
    unit_path.write_bytes(b"[Service]\nUser=gurk\n")
    captured: list[list[str]] = []

    class _Result:
        returncode = 0
        stderr = ""
        stdout = (
            "LoadState=loaded\n"
            f"FragmentPath={unit_path}\n"
            "DropInPaths=\n"
            "UnitFileState=disabled\n"
            "ActiveState=inactive\n"
        )

    def fake_run(command, **_kwargs):
        captured.append(command)
        return _Result()

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    state = preflight._load_unit_state(preflight.SERVICE_UNIT, "/usr/bin/systemctl")

    assert captured == [
        [
            "/usr/bin/systemctl",
            "--system",
            "show",
            preflight.SERVICE_UNIT,
            "--no-pager",
            "--property=LoadState,FragmentPath,DropInPaths,UnitFileState,ActiveState",
        ]
    ]
    assert state.content == unit_path.read_bytes()
    assert state.active_state == "inactive"
