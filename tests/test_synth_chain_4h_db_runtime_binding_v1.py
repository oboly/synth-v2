from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
from dotenv import load_dotenv

from src.common import db_core_v1
from src.common import synth_chain_4h_db_binding_v1 as binding
from src.operations import run_synth_chain_4h_db_environment_preflight_v1 as preflight
from src.operations import run_synth_chain_4h_db_grant_preflight_v1 as grant_preflight


ROOT = Path(__file__).parent.parent


def _secret(tmp_path: Path, value: str = "dedicated-secret\n") -> Path:
    path = tmp_path / "chain-password"
    path.write_text(value, encoding="utf-8")
    path.chmod(binding.EXPECTED_SECRET_MODE)
    return path


def _environment(secret: Path, **overrides: str) -> dict[str, str]:
    values = {
        binding.BINDING_PROFILE_ENV: binding.BINDING_PROFILE,
        binding.ENV_HOST: binding.EXPECTED_HOST,
        binding.ENV_PORT: str(binding.EXPECTED_PORT),
        binding.ENV_USER: binding.EXPECTED_USER,
        binding.ENV_DATABASE: binding.EXPECTED_DATABASE,
        binding.ENV_PASSWORD_FILE: str(secret),
    }
    values.update(overrides)
    return values


def _load(environ: dict[str, str]) -> binding.ChainDatabaseBinding:
    return binding.load_chain_database_binding(
        environ,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )


def _service_with_secret(tmp_path: Path, secret: Path) -> Path:
    source = (ROOT / preflight.SERVICE_REL_PATH).read_text(encoding="utf-8")
    source = source.replace(str(binding.EXPECTED_PASSWORD_FILE), str(secret))
    path = tmp_path / "synth-chain-4h.service"
    path.write_text(source, encoding="utf-8")
    return path


def test_exact_dedicated_identity_and_generic_env_isolation(tmp_path: Path) -> None:
    secret = _secret(tmp_path)
    resolved = _load(
        _environment(
            secret,
            DB_HOST="generic-db",
            DB_PORT="9999",
            DB_USER="synth",
            DB_PASSWORD="generic-secret",
            DB_NAME="other",
        )
    )
    assert (
        resolved.host,
        resolved.port,
        resolved.user,
        resolved.database,
        resolved.password,
    ) == (
        binding.EXPECTED_HOST,
        binding.EXPECTED_PORT,
        binding.EXPECTED_USER,
        binding.EXPECTED_DATABASE,
        "dedicated-secret",
    )
    assert binding.generic_fallback_variables(
        _environment(secret, DB_USER="synth", DB_PASSWORD="generic-secret")
    ) == ("DB_USER", "DB_PASSWORD")


def test_generic_dotenv_values_cannot_override_dedicated_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = _secret(tmp_path)
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "DB_HOST=generic-dotenv-host\n"
        "DB_PORT=9999\n"
        "DB_USER=synth\n"
        "DB_PASSWORD=generic-dotenv-value\n"
        "DB_NAME=other\n",
        encoding="utf-8",
    )
    for key in binding.GENERIC_DB_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in _environment(secret).items():
        monkeypatch.setenv(key, value)

    load_dotenv(dotenv_path=dotenv_path, override=False)
    resolved = _load(os.environ)

    assert resolved.host == binding.EXPECTED_HOST
    assert resolved.user == binding.EXPECTED_USER
    assert resolved.database == binding.EXPECTED_DATABASE
    assert resolved.password == "dedicated-secret"
    assert os.environ["DB_USER"] == "synth"


def test_missing_binding_profile_fails_even_with_dedicated_values(
    tmp_path: Path,
) -> None:
    environ = _environment(_secret(tmp_path))
    del environ[binding.BINDING_PROFILE_ENV]
    with pytest.raises(binding.ChainDatabaseBindingError, match="PROFILE_MISSING"):
        _load(environ)


def test_missing_password_file_fails(tmp_path: Path) -> None:
    with pytest.raises(binding.ChainDatabaseBindingError, match="FILE_MISSING"):
        _load(_environment(tmp_path / "missing"))


def test_empty_password_file_fails(tmp_path: Path) -> None:
    with pytest.raises(binding.ChainDatabaseBindingError, match="FILE_EMPTY"):
        _load(_environment(_secret(tmp_path, "")))


def test_symlink_secret_is_rejected(tmp_path: Path) -> None:
    target = _secret(tmp_path)
    link = tmp_path / "password-link"
    link.symlink_to(target)
    with pytest.raises(binding.ChainDatabaseBindingError, match="SYMLINK_FORBIDDEN"):
        _load(_environment(link))


def test_non_regular_secret_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "password-directory"
    directory.mkdir()
    with pytest.raises(binding.ChainDatabaseBindingError, match="NOT_REGULAR"):
        _load(_environment(directory))


def test_unsafe_secret_permissions_are_rejected(tmp_path: Path) -> None:
    secret = _secret(tmp_path)
    secret.chmod(0o644)
    with pytest.raises(binding.ChainDatabaseBindingError, match="MODE_INVALID"):
        _load(_environment(secret))


def test_wrong_secret_owner_or_group_is_rejected(tmp_path: Path) -> None:
    secret = _secret(tmp_path)
    with pytest.raises(binding.ChainDatabaseBindingError, match="OWNERSHIP_INVALID"):
        binding.load_chain_database_binding(
            _environment(secret),
            expected_uid=os.getuid() + 1,
            expected_gid=os.getgid(),
        )


def test_broad_synth_identity_cannot_be_selected_or_used_as_fallback(
    tmp_path: Path,
) -> None:
    secret = _secret(tmp_path)
    with pytest.raises(binding.ChainDatabaseBindingError, match="USER_INVALID"):
        _load(_environment(secret, SYNTH_CHAIN_4H_DB_USER="synth"))

    environ = _environment(secret, DB_USER="synth")
    del environ[binding.ENV_USER]
    with pytest.raises(binding.ChainDatabaseBindingError, match="CONFIG_MISSING"):
        _load(environ)


def test_child_process_inherits_exact_nonsecret_binding_without_secret_output(
    tmp_path: Path,
) -> None:
    secret = _secret(tmp_path)
    environment = os.environ.copy()
    environment.update(_environment(secret, DB_USER="synth"))
    code = (
        "import os;"
        "from src.common.synth_chain_4h_db_binding_v1 import "
        "load_chain_database_binding;"
        "c=load_chain_database_binding(expected_uid=os.getuid(),"
        "expected_gid=os.getgid());"
        "print(c.profile,c.host,c.port,c.user,c.database,c.password_file)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert (
        result.stdout.strip()
        == f"synth_chain_4h gurkdb 3306 synth_chain_4h_writer synth {secret}"
    )
    assert "dedicated-secret" not in result.stdout + result.stderr


def test_secret_is_redacted_from_repr_and_errors(tmp_path: Path) -> None:
    secret = _secret(tmp_path, "unique-redaction-secret\n")
    resolved = _load(_environment(secret))
    assert "unique-redaction-secret" not in repr(resolved)

    rendered = str(
        binding.ChainDatabaseBindingError("CHAIN_DB_SECRET_FILE_FORMAT_INVALID")
    )
    assert "unique-redaction-secret" not in rendered


def test_unrelated_generic_db_caller_retains_existing_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.delenv(binding.BINDING_PROFILE_ENV, raising=False)
    for key in binding.DEDICATED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DB_HOST", "legacy-host")
    monkeypatch.setenv("DB_PORT", "3308")
    monkeypatch.setenv("DB_USER", "legacy-user")
    monkeypatch.setenv("DB_PASSWORD", "legacy-password")
    monkeypatch.setenv("DB_NAME", "legacy-database")
    monkeypatch.setattr(
        db_core_v1.pymysql,
        "connect",
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    db_core_v1.get_connection()

    assert captured["host"] == "legacy-host"
    assert captured["port"] == 3308
    assert captured["user"] == "legacy-user"
    assert captured["password"] == "legacy-password"
    assert captured["database"] == "legacy-database"


def test_db_core_uses_exact_binding_and_forbids_database_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = _secret(tmp_path)
    for key, value in _environment(secret, DB_USER="synth").items():
        monkeypatch.setenv(key, value)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        db_core_v1,
        "load_chain_database_binding",
        lambda: _load(_environment(secret, DB_USER="synth")),
    )
    monkeypatch.setattr(
        db_core_v1.pymysql,
        "connect",
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    db_core_v1.get_connection()

    assert captured["host"] == binding.EXPECTED_HOST
    assert captured["user"] == binding.EXPECTED_USER
    assert captured["password"] == "dedicated-secret"
    assert captured["database"] == binding.EXPECTED_DATABASE
    with pytest.raises(ValueError, match="DATABASE_OVERRIDE_FORBIDDEN"):
        db_core_v1.get_connection(database="other")


def test_repository_unit_and_environment_preflight_are_exactly_equivalent(
    tmp_path: Path,
) -> None:
    secret = _secret(tmp_path)
    result = preflight.run_preflight(
        environ=_environment(secret, DB_USER="synth"),
        service_path=_service_with_secret(tmp_path, secret),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    assert result.repository_unit_equivalent
    assert result.grant_preflight_invocable
    assert result.generic_variables == ("DB_USER",)


def test_repository_unit_owns_exact_canonical_binding_contract() -> None:
    assert preflight._validate_repository_unit(
        ROOT / preflight.SERVICE_REL_PATH
    ) == preflight.EXPECTED_SERVICE_ENVIRONMENT


def test_host_preflight_output_reports_metadata_without_secret(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    secret = _secret(tmp_path, "output-redaction-value\n")
    resolved = _load(_environment(secret, DB_USER="synth"))
    result = preflight.EnvironmentPreflightResult(
        binding=resolved,
        generic_variables=("DB_USER",),
        repository_unit_equivalent=True,
        grant_preflight_invocable=True,
    )
    monkeypatch.setattr(preflight, "run_preflight", lambda **_kwargs: result)

    assert preflight.main(["--checkout-path", str(ROOT)]) == 0

    output = capsys.readouterr().out
    assert "binding_profile=synth_chain_4h" in output
    assert "endpoint=gurkdb port=3306 username=synth_chain_4h_writer" in output
    assert f"secret_path={secret}" in output
    assert "secret_file_type=regular" in output
    assert "secret_mode=0640" in output
    assert "secret_symlink=false" in output
    assert "generic_fallback_policy=ignored_by_active_closed_profile" in output
    assert "grant_preflight_invocable=true" in output
    assert "output-redaction-value" not in output


def test_grant_preflight_receives_exact_resolved_candidate_config(
    tmp_path: Path,
) -> None:
    secret = _secret(tmp_path)
    config = grant_preflight.load_candidate_config(
        _environment(secret, DB_USER="synth"),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    assert (
        config.host,
        config.port,
        config.user,
        config.password,
        config.database,
        config.password_file,
    ) == (
        binding.EXPECTED_HOST,
        binding.EXPECTED_PORT,
        binding.EXPECTED_USER,
        "dedicated-secret",
        binding.EXPECTED_DATABASE,
        str(secret),
    )


def test_binding_has_no_account_execution_or_broker_layer_coupling() -> None:
    source = (
        ROOT / "src/common/synth_chain_4h_db_binding_v1.py"
    ).read_text(encoding="utf-8").lower()
    for forbidden in (
        "src.account",
        "src.decision_gate",
        "src.execution_planner",
        "src.executor",
        "src.broker",
    ):
        assert forbidden not in source
