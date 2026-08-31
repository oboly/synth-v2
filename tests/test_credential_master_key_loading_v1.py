from __future__ import annotations

import os

import pytest

import src.account_provisioning.credential_crypto_v1 as credential_crypto
from src.account_provisioning.credential_crypto_v1 import (
    MASTER_KEY_ENV_VAR,
    generate_test_master_key,
    load_master_key_from_env,
    parse_master_key,
)


def _write_key(path, value: str, mode: int = 0o600) -> None:
    path.write_text(value + "\n", encoding="utf-8")
    os.chmod(path, mode)


def test_env_override_takes_precedence_over_host_file(tmp_path) -> None:
    env_key = generate_test_master_key()
    file_key = generate_test_master_key()
    key_file = tmp_path / "master-key"
    _write_key(key_file, file_key, 0o600)

    assert load_master_key_from_env(
        env={MASTER_KEY_ENV_VAR: env_key},
        file_path=str(key_file),
    ) == parse_master_key(env_key)


def test_host_file_used_when_env_missing(tmp_path) -> None:
    file_key = generate_test_master_key()
    key_file = tmp_path / "master-key"
    _write_key(key_file, file_key, 0o640)

    assert load_master_key_from_env(env={}, file_path=str(key_file)) == parse_master_key(file_key)


def test_missing_env_and_file_fails_closed(tmp_path) -> None:
    with pytest.raises(ValueError, match="^MISSING_MASTER_KEY"):
        load_master_key_from_env(env={}, file_path=str(tmp_path / "missing"))


def test_malformed_host_file_fails_closed_without_secret_leak(tmp_path) -> None:
    secret_marker = "THIS_MUST_NOT_APPEAR"
    key_file = tmp_path / "master-key"
    _write_key(key_file, secret_marker, 0o600)

    with pytest.raises(ValueError) as exc_info:
        load_master_key_from_env(env={}, file_path=str(key_file))

    assert secret_marker not in str(exc_info.value)
    assert "INVALID_MASTER_KEY_FORMAT" in str(exc_info.value)


def test_world_readable_host_file_is_rejected(tmp_path) -> None:
    key_file = tmp_path / "master-key"
    _write_key(key_file, generate_test_master_key(), 0o644)

    with pytest.raises(ValueError, match="^INSECURE_MASTER_KEY_FILE_PERMISSIONS$"):
        load_master_key_from_env(env={}, file_path=str(key_file))


def test_group_writable_host_file_is_rejected(tmp_path) -> None:
    key_file = tmp_path / "master-key"
    _write_key(key_file, generate_test_master_key(), 0o660)

    with pytest.raises(ValueError, match="^INSECURE_MASTER_KEY_FILE_PERMISSIONS$"):
        load_master_key_from_env(env={}, file_path=str(key_file))


def test_symlink_host_file_is_rejected(tmp_path) -> None:
    real_file = tmp_path / "real-key"
    link_file = tmp_path / "master-key"
    _write_key(real_file, generate_test_master_key(), 0o600)
    link_file.symlink_to(real_file)

    with pytest.raises(ValueError, match="^MASTER_KEY_FILE_NOT_REGULAR$"):
        load_master_key_from_env(env={}, file_path=str(link_file))


def test_file_open_uses_no_follow_before_descriptor_validation(tmp_path, monkeypatch) -> None:
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("platform has no O_NOFOLLOW")

    key_file = tmp_path / "master-key"
    file_key = generate_test_master_key()
    _write_key(key_file, file_key, 0o600)
    real_open = os.open
    seen_flags: list[int] = []

    def checked_open(path, flags, *args, **kwargs):
        seen_flags.append(flags)
        assert flags & os.O_NOFOLLOW
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(credential_crypto.os, "open", checked_open)

    assert load_master_key_from_env(env={}, file_path=str(key_file)) == parse_master_key(file_key)
    assert len(seen_flags) == 1


def test_invalid_env_override_does_not_fall_back_to_file(tmp_path) -> None:
    key_file = tmp_path / "master-key"
    _write_key(key_file, generate_test_master_key(), 0o600)

    with pytest.raises(ValueError, match="^INVALID_MASTER_KEY_FORMAT$"):
        load_master_key_from_env(
            env={MASTER_KEY_ENV_VAR: "invalid-override"},
            file_path=str(key_file),
        )
