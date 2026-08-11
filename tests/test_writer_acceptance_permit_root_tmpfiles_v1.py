"""Focused tests for the canonical writer acceptance permit root provisioning.

Verifies the repository-owned systemd-tmpfiles config
(``deploy/tmpfiles.d/synth-writer-acceptance.conf``) declares exactly the
canonical fixed acceptance-permit root with the required owner, group, and
mode, and that the shared authorization module still treats
``/run/synth/writer-acceptance`` as the sole, non-overridable default root.

This module performs no host mutation, no systemd-tmpfiles invocation against
the real filesystem root, and no writer/authorization mutation.
"""
from __future__ import annotations

from pathlib import Path

from src.operations.writer_capability_authorization_v1 import (
    DEFAULT_ACCEPTANCE_PERMIT_ROOT,
)

REPO = Path.cwd()
TMPFILES_CONF = REPO / "deploy/tmpfiles.d/synth-writer-acceptance.conf"

CANONICAL_ROOT = "/run/synth/writer-acceptance"
CANONICAL_PARENT = "/run/synth"


def _parsed_lines() -> list[list[str]]:
    lines: list[list[str]] = []
    for raw in TMPFILES_CONF.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped.split())
    return lines


def _entry_for(path: str) -> list[str]:
    for fields in _parsed_lines():
        if len(fields) >= 2 and fields[1] == path:
            return fields
    raise AssertionError(f"no tmpfiles.d entry found for path={path}")


def test_tmpfiles_conf_exists() -> None:
    assert TMPFILES_CONF.is_file(), f"missing {TMPFILES_CONF}"


def test_acceptance_root_entry_is_exact_contract() -> None:
    fields = _entry_for(CANONICAL_ROOT)
    entry_type, path, mode, owner, group = fields[0], fields[1], fields[2], fields[3], fields[4]
    assert entry_type == "d"
    assert path == CANONICAL_ROOT
    assert mode == "0700"
    assert owner == "gurk"
    assert group == "gurk"


def test_acceptance_root_mode_has_no_group_or_world_bits() -> None:
    fields = _entry_for(CANONICAL_ROOT)
    mode = fields[2]
    # Octal mode string "0700": last two digits must be "00" -- no group or
    # world read/write/execute bits.
    assert mode[-2:] == "00", f"unexpected group/world bits in mode={mode}"


def test_parent_directory_entry_is_not_user_writable() -> None:
    fields = _entry_for(CANONICAL_PARENT)
    entry_type, path, mode, owner, group = fields[0], fields[1], fields[2], fields[3], fields[4]
    assert entry_type == "d"
    assert path == CANONICAL_PARENT
    assert owner == "root"
    assert group == "root"
    # 0755: root-writable only, group/world read+execute, no group/world write.
    assert mode == "0755"


def test_no_other_paths_declared() -> None:
    declared_paths = {fields[1] for fields in _parsed_lines() if len(fields) >= 2}
    assert declared_paths == {CANONICAL_PARENT, CANONICAL_ROOT}


def test_canonical_authorization_module_root_unchanged() -> None:
    assert str(DEFAULT_ACCEPTANCE_PERMIT_ROOT) == CANONICAL_ROOT


def test_authorization_module_root_not_environment_overridable() -> None:
    import src.operations.writer_capability_authorization_v1 as auth_mod

    # The acceptance permit root is a fixed default, not read from any
    # environment variable. Only the permit *path* (ENV_ACCEPTANCE_PERMIT) is
    # environment-suppliable; confirm no root-override env var was introduced.
    env_names = {
        value
        for name, value in vars(auth_mod).items()
        if name.startswith("ENV_") and isinstance(value, str)
    }
    assert "SYNTH_WRITER_ACCEPTANCE_PERMIT_ROOT" not in env_names
    for env_name in env_names:
        assert "PERMIT_ROOT" not in env_name.upper()
