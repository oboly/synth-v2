from __future__ import annotations

"""Read-only repository/host preflight for the 4h chain DB binding."""

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Mapping, Sequence

from src.common.synth_chain_4h_db_binding_v1 import (
    BINDING_PROFILE,
    BINDING_PROFILE_ENV,
    ENV_DATABASE,
    ENV_HOST,
    ENV_PASSWORD_FILE,
    ENV_PORT,
    ENV_USER,
    EXPECTED_DATABASE,
    EXPECTED_HOST,
    EXPECTED_PASSWORD_FILE,
    EXPECTED_PORT,
    EXPECTED_SECRET_GROUP,
    EXPECTED_SECRET_MODE,
    EXPECTED_SECRET_OWNER,
    EXPECTED_USER,
    ChainDatabaseBinding,
    ChainDatabaseBindingError,
    generic_fallback_variables,
    load_chain_database_binding,
)
from src.operations.run_native_short_systemd_equivalence_preflight_v1 import (
    SERVICE_REL_PATH,
    _parse_unit,
)
from src.operations.run_synth_chain_4h_db_grant_preflight_v1 import (
    load_candidate_config,
)


RUNNER_NAME = "run_synth_chain_4h_db_environment_preflight_v1"
EXPECTED_SERVICE_ENVIRONMENT = {
    BINDING_PROFILE_ENV: BINDING_PROFILE,
    ENV_HOST: EXPECTED_HOST,
    ENV_PORT: str(EXPECTED_PORT),
    ENV_USER: EXPECTED_USER,
    ENV_DATABASE: EXPECTED_DATABASE,
    ENV_PASSWORD_FILE: str(EXPECTED_PASSWORD_FILE),
}


class EnvironmentPreflightError(ValueError):
    pass


@dataclass(frozen=True)
class EnvironmentPreflightResult:
    binding: ChainDatabaseBinding
    generic_variables: tuple[str, ...]
    repository_unit_equivalent: bool
    grant_preflight_invocable: bool


def _unit_environment(service_path: Path) -> dict[str, str]:
    try:
        content = service_path.read_bytes()
    except OSError as exc:
        raise EnvironmentPreflightError("REPOSITORY_SERVICE_UNIT_UNREADABLE") from exc
    parsed = _parse_unit(content)
    if parsed.get(("Service", "EnvironmentFile"), ()):
        raise EnvironmentPreflightError("REPOSITORY_SERVICE_ENVIRONMENT_FILE_FORBIDDEN")

    result: dict[str, str] = {}
    for value in parsed.get(("Service", "Environment"), ()):
        key, separator, item = value.partition("=")
        if not separator or key in result:
            raise EnvironmentPreflightError(
                "REPOSITORY_SERVICE_ENVIRONMENT_INVALID"
            )
        result[key] = item
    return result


def _validate_repository_unit(service_path: Path) -> dict[str, str]:
    environment = _unit_environment(service_path)
    expected = {
        key: environment.get(key)
        for key in EXPECTED_SERVICE_ENVIRONMENT
    }
    if (
        expected[BINDING_PROFILE_ENV] != BINDING_PROFILE
        or expected[ENV_USER] != EXPECTED_USER
        or expected[ENV_DATABASE] != EXPECTED_DATABASE
        or not expected[ENV_HOST]
        or not expected[ENV_PORT]
        or not expected[ENV_PASSWORD_FILE]
    ):
        raise EnvironmentPreflightError(
            "REPOSITORY_SERVICE_DB_BINDING_MISMATCH"
        )
    try:
        port = int(str(expected[ENV_PORT]))
    except ValueError as exc:
        raise EnvironmentPreflightError(
            "REPOSITORY_SERVICE_DB_BINDING_MISMATCH"
        ) from exc
    if not 1 <= port <= 65535 or not Path(
        str(expected[ENV_PASSWORD_FILE])
    ).is_absolute():
        raise EnvironmentPreflightError(
            "REPOSITORY_SERVICE_DB_BINDING_MISMATCH"
        )
    forbidden = {
        "SYNTH_CHAIN_4H_DB_PASSWORD",
        "DB_HOST",
        "DB_PORT",
        "DB_USER",
        "DB_PASSWORD",
        "DB_NAME",
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "MYSQL_DATABASE",
    }
    if forbidden.intersection(environment):
        raise EnvironmentPreflightError(
            "REPOSITORY_SERVICE_GENERIC_OR_INLINE_SECRET_FORBIDDEN"
        )
    return {key: str(value) for key, value in expected.items()}


def run_preflight(
    *,
    environ: Mapping[str, str],
    service_path: Path,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> EnvironmentPreflightResult:
    expected_environment = _validate_repository_unit(service_path)
    try:
        binding = load_chain_database_binding(
            environ,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
    except ChainDatabaseBindingError as exc:
        raise EnvironmentPreflightError(str(exc)) from None

    configured = {
        BINDING_PROFILE_ENV: binding.profile,
        ENV_HOST: binding.host,
        ENV_PORT: str(binding.port),
        ENV_USER: binding.user,
        ENV_DATABASE: binding.database,
        ENV_PASSWORD_FILE: str(binding.password_file),
    }
    if configured != expected_environment:
        raise EnvironmentPreflightError("ACTIVE_DB_BINDING_UNIT_MISMATCH")

    try:
        grant_config = load_candidate_config(
            environ,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
    except ValueError as exc:
        raise EnvironmentPreflightError(
            "GRANT_PREFLIGHT_CANDIDATE_CONFIG_UNAVAILABLE"
        ) from exc
    grant_equivalent = (
        grant_config.host == binding.host
        and grant_config.port == binding.port
        and grant_config.user == binding.user
        and grant_config.password == binding.password
        and grant_config.database == binding.database
        and grant_config.password_file == str(binding.password_file)
    )
    if not grant_equivalent:
        raise EnvironmentPreflightError(
            "GRANT_PREFLIGHT_CANDIDATE_CONFIG_MISMATCH"
        )

    return EnvironmentPreflightResult(
        binding=binding,
        generic_variables=generic_fallback_variables(environ),
        repository_unit_equivalent=True,
        grant_preflight_invocable=True,
    )


def _safety_markers() -> str:
    return (
        "host_mutations=0 systemd_mutations=0 database_writes=0 "
        "credential_changes=0 writer_invocations=0 snapshot_publications=0 "
        "broker_private_calls=0 broker_writes=0 order_submission=0 "
        "live_orders=0 decision_gate=none execution_planner=none executor=none"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only 4h chain database binding and secret-file preflight."
    )
    parser.add_argument("--checkout-path", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    print(
        f"STARTED runner={RUNNER_NAME} mode=read_only scope=chain_db_binding "
        "worker_count=1",
        flush=True,
    )
    print(_safety_markers(), flush=True)
    try:
        result = run_preflight(
            environ=os.environ,
            service_path=args.checkout_path.resolve() / SERVICE_REL_PATH,
        )
    except EnvironmentPreflightError as exc:
        print(
            f"FAILED runner={RUNNER_NAME} reason={exc} {_safety_markers()}",
            file=sys.stderr,
            flush=True,
        )
        return 1

    binding = result.binding
    metadata = binding.secret_metadata
    if metadata is None:
        print(
            f"FAILED runner={RUNNER_NAME} reason=SECRET_METADATA_UNAVAILABLE "
            f"{_safety_markers()}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    generic = ",".join(result.generic_variables) or "none"
    print(
        f"binding_profile={binding.profile} endpoint={binding.host} "
        f"port={binding.port} username={binding.user} database={binding.database}",
        flush=True,
    )
    print(
        f"secret_path={binding.password_file} secret_file_type={metadata.file_type} "
        f"secret_owner={metadata.owner} secret_group={metadata.group} "
        f"secret_mode={metadata.mode:04o} secret_symlink={str(metadata.is_symlink).lower()}",
        flush=True,
    )
    print(
        f"generic_fallback_variables={generic} "
        "generic_fallback_policy=ignored_by_active_closed_profile "
        f"repository_unit_equivalent={str(result.repository_unit_equivalent).lower()} "
        f"grant_preflight_invocable={str(result.grant_preflight_invocable).lower()}",
        flush=True,
    )
    print(
        f"secret_contract_owner={EXPECTED_SECRET_OWNER} "
        f"secret_contract_group={EXPECTED_SECRET_GROUP} "
        f"secret_contract_mode={EXPECTED_SECRET_MODE:04o}",
        flush=True,
    )
    print(f"FINISHED runner={RUNNER_NAME} status=PASS {_safety_markers()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
