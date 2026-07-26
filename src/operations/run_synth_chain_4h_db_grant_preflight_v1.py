from __future__ import annotations

"""Read-only MariaDB grant preflight for the dedicated 4h market-chain writer.

Safety boundary:
database_writes=0 ddl_statements=0 dml_statements=0 credential_changes=0
writer_invocations=0 canonical_publication=0 host_mutations=0
broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0
decision_gate=none execution_planner=none executor=none
"""

import argparse
from dataclasses import dataclass, field
import sys
from typing import Any, Callable, Mapping, Sequence

import pymysql
from pymysql.cursors import DictCursor

from src.common.synth_chain_4h_db_binding_v1 import (
    BINDING_PROFILE_ENV,
    DEDICATED_ENV_KEYS,
    ENV_DATABASE,
    ENV_HOST,
    ENV_PASSWORD_FILE,
    ENV_PORT,
    ENV_USER,
    ChainDatabaseBindingError,
    load_chain_database_binding,
)
from src.operations.synth_chain_4h_db_authority_v1 import (
    EXPECTED_GRANT_IDENTITY,
    IDENTITY_NAME,
    OPERATIONAL_DATABASE,
    REQUIRED_OBJECT_PRIVILEGES,
    GrantAudit,
    audit_grants,
)


RUNNER_NAME = "run_synth_chain_4h_db_grant_preflight_v1"
REQUIRED_ENV_KEYS = (BINDING_PROFILE_ENV, *DEDICATED_ENV_KEYS)

READ_ONLY_SQL = (
    "START TRANSACTION READ ONLY",
    (
        "SELECT USER() AS authenticated_identity, "
        "CURRENT_USER() AS grant_identity, DATABASE() AS database_name"
    ),
    "SHOW GRANTS",
)


class PreflightConfigurationError(ValueError):
    pass


class PreflightConnectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidateDatabaseConfig:
    host: str
    port: int
    user: str
    password: str = field(repr=False)
    database: str
    password_file: str = ""


@dataclass(frozen=True)
class GrantPreflightResult:
    authenticated_identity: str
    grant_identity: str
    database_name: str
    grant_statements: tuple[str, ...]
    audit: GrantAudit


ConnectFn = Callable[..., Any]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only SHOW GRANTS preflight for the dedicated "
            "synth-chain-4h database identity"
        )
    )
    return parser.parse_args(argv)


def load_candidate_config(
    environ: Mapping[str, str] | None = None,
    *,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> CandidateDatabaseConfig:
    try:
        binding = load_chain_database_binding(
            environ,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
    except ChainDatabaseBindingError as exc:
        raise PreflightConfigurationError(str(exc)) from None
    return CandidateDatabaseConfig(
        host=binding.host,
        port=binding.port,
        user=binding.user,
        password=binding.password,
        database=binding.database,
        password_file=str(binding.password_file),
    )


def _first_value(row: Any) -> Any:
    if isinstance(row, dict):
        if not row:
            return None
        return next(iter(row.values()))
    if isinstance(row, (tuple, list)):
        return row[0] if row else None
    return row


def _identity_fields(row: Any) -> tuple[str, str, str]:
    if not isinstance(row, dict):
        raise PreflightConnectionError("IDENTITY_QUERY_ROW_INVALID")
    return (
        str(row.get("authenticated_identity") or ""),
        str(row.get("grant_identity") or ""),
        str(row.get("database_name") or ""),
    )


def run_preflight(
    config: CandidateDatabaseConfig,
    *,
    connect: ConnectFn = pymysql.connect,
) -> GrantPreflightResult:
    try:
        conn = connect(
            host=config.host,
            port=config.port,
            user=config.user,
            password=config.password,
            database=config.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
        )
    except Exception as exc:
        raise PreflightConnectionError(
            f"DATABASE_CONNECTION_FAILED error_type={type(exc).__name__}"
        ) from None

    try:
        with conn.cursor() as cur:
            cur.execute(READ_ONLY_SQL[0])
            cur.execute(READ_ONLY_SQL[1])
            identity_row = cur.fetchone()
            cur.execute(READ_ONLY_SQL[2])
            grant_rows = tuple(cur.fetchall())
        authenticated_identity, grant_identity, database_name = _identity_fields(
            identity_row
        )
        grant_statements = tuple(
            str(value)
            for row in grant_rows
            if (value := _first_value(row)) is not None
        )
        audit = audit_grants(
            grant_identity=grant_identity,
            database_name=database_name,
            grant_statements=grant_statements,
        )
        return GrantPreflightResult(
            authenticated_identity=authenticated_identity,
            grant_identity=grant_identity,
            database_name=database_name,
            grant_statements=grant_statements,
            audit=audit,
        )
    except PreflightConnectionError:
        raise
    except Exception as exc:
        raise PreflightConnectionError(
            f"READ_ONLY_GRANT_QUERY_FAILED error_type={type(exc).__name__}"
        ) from None
    finally:
        cleanup_errors: list[str] = []
        try:
            conn.rollback()
        except Exception as exc:
            cleanup_errors.append(f"rollback={type(exc).__name__}")
        try:
            conn.close()
        except Exception as exc:
            cleanup_errors.append(f"close={type(exc).__name__}")
        if cleanup_errors:
            raise PreflightConnectionError(
                "READ_ONLY_CONNECTION_CLEANUP_FAILED "
                + ",".join(cleanup_errors)
            ) from None


def _csv(values: tuple[str, ...]) -> str:
    return ",".join(values) if values else "none"


def main(argv: Sequence[str] | None = None) -> int:
    parse_args(argv)
    print(
        f"STARTED runner={RUNNER_NAME} mode=read_only worker_count=1 "
        f"identity_name={IDENTITY_NAME} required_objects={len(REQUIRED_OBJECT_PRIVILEGES)}",
        flush=True,
    )
    print(
        "database_writes=0 ddl_statements=0 dml_statements=0 "
        "credential_changes=0 writer_invocations=0 canonical_publication=0 "
        "host_mutations=0 broker_private_calls=0 broker_writes=0 "
        "order_submission=0 live_orders=0 decision_gate=none "
        "execution_planner=none executor=none",
        flush=True,
    )
    try:
        config = load_candidate_config()
        result = run_preflight(config)
    except (PreflightConfigurationError, PreflightConnectionError) as exc:
        print(
            f"FAILED runner={RUNNER_NAME} reason={exc} "
            "database_writes=0 ddl_statements=0 dml_statements=0",
            file=sys.stderr,
            flush=True,
        )
        return 1

    print(
        f"authenticated_identity={result.authenticated_identity or 'EMPTY'} "
        f"grant_identity={result.grant_identity or 'EMPTY'} "
        f"expected_grant_identity={EXPECTED_GRANT_IDENTITY} "
        f"database_name={result.database_name or 'EMPTY'} "
        f"grant_statement_count={len(result.grant_statements)}",
        flush=True,
    )
    if not result.audit.passed:
        print(
            f"FAILED runner={RUNNER_NAME} reason=GRANT_CONTRACT_MISMATCH "
            f"missing={_csv(result.audit.missing)} "
            f"unexpected={_csv(result.audit.unexpected)} "
            f"violations={_csv(result.audit.violations)} "
            "database_writes=0 ddl_statements=0 dml_statements=0",
            file=sys.stderr,
            flush=True,
        )
        return 1

    print(
        f"FINISHED runner={RUNNER_NAME} status=PASS "
        f"required_objects={len(REQUIRED_OBJECT_PRIVILEGES)} "
        "database_writes=0 ddl_statements=0 dml_statements=0 "
        "credential_changes=0",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
