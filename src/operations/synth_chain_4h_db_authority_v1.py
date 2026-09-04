from __future__ import annotations

"""Exact MariaDB authority contract for the market-only 4h processing chain."""

from dataclasses import dataclass
import re
from typing import Iterable, Mapping


IDENTITY_NAME = "synth_chain_4h_writer"
IDENTITY_HOST = "192.168.1.%"
EXPECTED_GRANT_IDENTITY = f"{IDENTITY_NAME}@{IDENTITY_HOST}"
OPERATIONAL_DATABASE = "synth"

SELECT = "SELECT"
INSERT = "INSERT"
UPDATE = "UPDATE"
DELETE = "DELETE"


def _privileges(*values: str) -> frozenset[str]:
    return frozenset(values)


# Derived from scripts/run_chain_4h.sh and every SQL execution site reachable
# from that wrapper. Keep the grant artifact and preflight tests synchronized
# with this mapping.
REQUIRED_OBJECT_PRIVILEGES: Mapping[str, frozenset[str]] = {
    "advice_state": _privileges(SELECT, INSERT, UPDATE),
    "aplus_table1_report": _privileges(SELECT),
    "aplus_table1_row": _privileges(SELECT),
    "asset": _privileges(SELECT),
    "asset_interval_quality": _privileges(SELECT, INSERT, UPDATE),
    "canonical_fib_zone_map_publication_v1": _privileges(SELECT, INSERT),
    "canonical_fib_zone_map_v1": _privileges(SELECT, INSERT),
    "canonical_fib_zone_map_latest_v1": _privileges(SELECT),
    "execution_zone_context": _privileges(SELECT, INSERT, UPDATE, DELETE),
    "feat_candle": _privileges(SELECT, INSERT, UPDATE),
    "fib_observation_v2": _privileges(SELECT, INSERT, UPDATE),
    "market_price_snapshot": _privileges(SELECT),
    "native_short_map_generation_event_v1": _privileges(SELECT, INSERT),
    "native_short_map_level_status_v1": _privileges(SELECT, INSERT, DELETE),
    # Append-only prospective target-event ledger, reachable from the shared
    # terminal-transition hook in native_short_scope_status_materializer_v1
    # (_append_terminal_target_events -> append_native_short_map_level_target_
    # events_for_map), which runs unconditionally on every genuine COMPLETED
    # lifecycle transition. The coverage table's SELECT is always reached
    # this way (error 1142 confirmed in production on gurkdb, 2026-08-02,
    # when it was still missing). Its own INSERT (establish_or_fetch_
    # target_event_coverage_for_map) is not granted: the production chain
    # entrypoint (run_native_short_scope_status_chain_v1 /
    # scripts/run_native_short_scope_status_chain_once.sh) never exposes or
    # supplies a non-None target_event_coverage_watermark_utc, so that
    # establishment branch is not reachable under this identity today -- see
    # docs/ops/synth_chain_4h_database_least_privilege_contract_v1.md for the
    # exact call-graph trace and the required re-review if that ever
    # changes. The event
    # table's SELECT/INSERT (fetch_native_short_map_level_target_events_for_map
    # / insert_native_short_map_level_target_events) are granted because the
    # shared hook's own docstring explicitly anticipates reading coverage
    # "established ... by an earlier standalone run" under a different
    # identity, after which this identity's terminal-transition hook appends
    # events for that already-covered map -- a real, designed reachability
    # path, not a hypothetical one. Neither table is ever issued an UPDATE or
    # DELETE (both modules are append-only by design); the reporting-only
    # view native_short_map_level_target_event_current_state_v1 is not
    # referenced by any runtime code path and is intentionally not granted.
    "native_short_map_level_target_event_coverage_v1": _privileges(SELECT),
    "native_short_map_level_target_event_v1": _privileges(SELECT, INSERT),
    "native_short_map_lifecycle_event_v1": _privileges(SELECT, INSERT),
    "native_short_map_scope_v1": _privileges(SELECT),
    "native_short_map_v1": _privileges(SELECT, INSERT),
    "native_short_materializer_run_v1": _privileges(SELECT, INSERT, UPDATE),
    # AUTO_ONBOARD_SCOPES runs unconditionally at the start of every scheduled
    # run_native_short_scope_status_chain_v1 invocation that omits explicit
    # symbols (the production entrypoint), via native_short_auto_onboarding_v1
    # .reconcile_ready_scopes -> execute_scope_administration. That call
    # always reads this table's idempotency ledger first (read_existing_
    # operation / read_scope_state_snapshot, both unconditional), then inserts
    # one immutable terminal ledger row (_insert_operation) whenever a READY
    # market is actually onboarded to SUPPORTED (error 1142 confirmed in
    # production on gurkdb, 2026-09-04, when SELECT was still missing). Rows
    # are never UPDATEd or DELETEd once committed.
    "native_short_scope_admin_operation_v1": _privileges(SELECT, INSERT),
    "native_short_scope_cadence_config_v1": _privileges(SELECT),
    "native_short_scope_observation_v1": _privileges(SELECT, INSERT),
    "native_short_scope_status_v1": _privileges(SELECT, INSERT, UPDATE),
    "native_short_scope_support_event_v1": _privileges(SELECT),
    "obs_market_candle": _privileges(SELECT),
    "paper_advice_observation": _privileges(SELECT, INSERT, UPDATE),
    "ranking_state": _privileges(SELECT, INSERT, UPDATE),
    "selection_state": _privileges(SELECT, INSERT, UPDATE),
    "signal_engine_state": _privileges(SELECT, INSERT, UPDATE),
    "strategy_runtime_component": _privileges(INSERT),
    "strategy_runtime_snapshot": _privileges(INSERT),
    "trade_setup_filter_observation": _privileges(SELECT, INSERT, UPDATE),
    "trade_setup_policy_preview_observation": _privileges(SELECT, INSERT, UPDATE),
    "v_asset_interval_quality_v3": _privileges(SELECT),
    "venue_market": _privileges(SELECT),
    "vw_paper_advice_execution_zone_context_v1": _privileges(SELECT),
    "zone_observation_v2": _privileges(SELECT, INSERT, UPDATE),
}


# Semantic deny-list for high-risk repository objects. Exact-set comparison
# rejects every unexpected object, including objects not listed here. This set
# exists to make diagnostics explicit for known account/decision/execution
# authority and intentionally exempts market-derived execution_zone_context.
FORBIDDEN_AUTHORITY_OBJECTS = frozenset(
    {
        "account_asset",
        "account_open_order_snapshot",
        "app_profile",
        "app_profile_trading_account_link",
        "app_user_profile_access",
        "decision_gate_audit_log",
        "execution_ladder_leg",
        "execution_ladder_profile",
        "execution_plan",
        "execution_plan_audit_log",
        "execution_plan_leg",
        "execution_sizing_rule",
        "execution_sizing_variable_ref",
        "executor_action_audit_log",
        "executor_result_audit_log",
        "trading_account_balance_snapshot",
        "trading_account_credential",
    }
)

ADMINISTRATIVE_PRIVILEGES = frozenset(
    {
        "ALL",
        "ALL PRIVILEGES",
        "ALTER",
        "ALTER ROUTINE",
        "CREATE",
        "CREATE ROLE",
        "CREATE ROUTINE",
        "CREATE TABLESPACE",
        "CREATE TEMPORARY TABLES",
        "CREATE USER",
        "CREATE VIEW",
        "DROP",
        "EVENT",
        "EXECUTE",
        "FILE",
        "GRANT OPTION",
        "INDEX",
        "LOCK TABLES",
        "PROCESS",
        "PROXY",
        "RELOAD",
        "REPLICATION CLIENT",
        "REPLICATION SLAVE",
        "SET USER",
        "SHOW DATABASES",
        "SHUTDOWN",
        "SUPER",
        "TRIGGER",
    }
)

_GRANT_RE = re.compile(
    r"^GRANT\s+(?P<privileges>.+?)\s+ON\s+(?P<object>.+?)\s+TO\s+",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedGrant:
    database: str
    object_name: str
    privileges: frozenset[str]
    grant_option: bool
    source: str


@dataclass(frozen=True)
class GrantAudit:
    grant_identity: str
    database_name: str
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]
    violations: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.missing and not self.unexpected and not self.violations


class GrantParseError(ValueError):
    pass


def _unquote_identifier(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == "`" and stripped[-1] == "`":
        return stripped[1:-1].replace("``", "`")
    return stripped


def _parse_object_scope(value: str) -> tuple[str, str]:
    parts = value.strip().split(".", 1)
    if len(parts) != 2:
        raise GrantParseError("GRANT_OBJECT_SCOPE_INVALID")
    return (_unquote_identifier(parts[0]), _unquote_identifier(parts[1]))


def parse_grant_statement(statement: str) -> ParsedGrant:
    normalized = " ".join(statement.strip().split())
    match = _GRANT_RE.match(normalized)
    if match is None:
        raise GrantParseError("GRANT_STATEMENT_UNSUPPORTED")

    privilege_text = match.group("privileges")
    privileges = frozenset(
        part.strip().upper() for part in privilege_text.split(",") if part.strip()
    )
    if not privileges:
        raise GrantParseError("GRANT_PRIVILEGES_EMPTY")
    database, object_name = _parse_object_scope(match.group("object"))
    return ParsedGrant(
        database=database,
        object_name=object_name,
        privileges=privileges,
        grant_option=" WITH GRANT OPTION" in f" {normalized.upper()}",
        source=statement,
    )


def _format_privilege(object_name: str, privilege: str) -> str:
    return f"{OPERATIONAL_DATABASE}.{object_name}:{privilege}"


def audit_grants(
    *,
    grant_identity: str,
    database_name: str,
    grant_statements: Iterable[str],
) -> GrantAudit:
    actual: dict[str, set[str]] = {}
    unexpected: set[str] = set()
    violations: set[str] = set()

    if grant_identity != EXPECTED_GRANT_IDENTITY:
        violations.add(
            "GRANT_IDENTITY_MISMATCH "
            f"expected={EXPECTED_GRANT_IDENTITY} actual={grant_identity or 'EMPTY'}"
        )
    if database_name != OPERATIONAL_DATABASE:
        violations.add(
            "DATABASE_MISMATCH "
            f"expected={OPERATIONAL_DATABASE} actual={database_name or 'EMPTY'}"
        )

    for statement in grant_statements:
        try:
            parsed = parse_grant_statement(statement)
        except GrantParseError as exc:
            violations.add(str(exc))
            continue

        if parsed.grant_option:
            violations.add("GRANT_OPTION_FORBIDDEN")

        if parsed.database == "*" and parsed.object_name == "*":
            if parsed.privileges != {"USAGE"}:
                violations.add(
                    "GLOBAL_AUTHORITY_FORBIDDEN privileges="
                    + ",".join(sorted(parsed.privileges))
                )
            continue

        if parsed.object_name == "*":
            violations.add(
                f"SCHEMA_WILDCARD_FORBIDDEN scope={parsed.database}.*"
            )
            continue

        if parsed.database != OPERATIONAL_DATABASE:
            violations.add(
                f"FOREIGN_DATABASE_AUTHORITY_FORBIDDEN database={parsed.database}"
            )
            continue

        if parsed.privileges & ADMINISTRATIVE_PRIVILEGES:
            violations.add(
                "ADMINISTRATIVE_AUTHORITY_FORBIDDEN object="
                f"{parsed.database}.{parsed.object_name} privileges="
                + ",".join(sorted(parsed.privileges & ADMINISTRATIVE_PRIVILEGES))
            )

        if parsed.object_name in FORBIDDEN_AUTHORITY_OBJECTS:
            violations.add(
                f"FORBIDDEN_OBJECT_AUTHORITY object={parsed.database}.{parsed.object_name}"
            )

        expected = REQUIRED_OBJECT_PRIVILEGES.get(parsed.object_name)
        if expected is None:
            for privilege in parsed.privileges:
                unexpected.add(_format_privilege(parsed.object_name, privilege))
            continue
        actual.setdefault(parsed.object_name, set()).update(parsed.privileges)

    missing: set[str] = set()
    for object_name, expected_privileges in REQUIRED_OBJECT_PRIVILEGES.items():
        actual_privileges = actual.get(object_name, set())
        for privilege in expected_privileges - actual_privileges:
            missing.add(_format_privilege(object_name, privilege))
        for privilege in actual_privileges - expected_privileges:
            unexpected.add(_format_privilege(object_name, privilege))

    return GrantAudit(
        grant_identity=grant_identity,
        database_name=database_name,
        missing=tuple(sorted(missing)),
        unexpected=tuple(sorted(unexpected)),
        violations=tuple(sorted(violations)),
    )
