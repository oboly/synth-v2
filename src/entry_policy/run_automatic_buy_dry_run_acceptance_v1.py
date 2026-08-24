"""Issue #471: bounded DRY_RUN-only automatic BUY acceptance producer.

Composes the exact canonical path end to end:

    caller-controlled source/setup evidence
    -> automatic_buy_source_runtime_input_writer_v1 (immutable runtime input)
    -> automatic_buy_runtime_repository_v1.build_runtime_item_v1
       (canonical Issue #474 decision-gate-owned account allocation evidence,
       #279 strategy bucket, #318 account protection, venue constraints)
    -> automatic_buy_runtime_orchestrator_v1.evaluate_automatic_buy_runtime_item_v1
       (candidate -> automatic_buy_gate_v1 -> automatic_buy_planner_v1 -> audit)
    -> a persisted shared #206 executor handoff, forced DRY_RUN.

The persisted handoff always uses ``executor_mode=DRY_RUN``,
``runtime_owner=gurkdb`` and ``executor_identity=shared-executor-v1``. DRY_RUN
intake never resolves executor credentials, never requires LIVE authority,
and never calls a broker; ``executor_credential_binding_id`` is always NULL
for DRY_RUN by construction of ``ExecutionHandoffRepositoryV1.intake``.

Operator/JSON input may only describe source/market/setup evidence and the
identity needed to locate canonical account evidence (see
``automatic_buy_source_runtime_input_writer_v1.AutomaticBuySourceRuntimeInputRequestV1``).
It cannot express account enablement, mode, LIVE flag, execution permission,
balances, exposure, or protection state -- those fields do not exist on the
input contract, and any attempt to supply them in the JSON payload is
rejected before a DB connection is even opened.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
live_authority=0
credential_calls=0
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

from src.common.db import get_db_connection
from src.entry_policy.automatic_buy_runtime_audit_writer_v1 import AutomaticBuyIdempotencyPayloadConflictError
from src.entry_policy.automatic_buy_runtime_orchestrator_v1 import (
    PLANNER_STATE_STAGED,
    evaluate_automatic_buy_runtime_item_v1,
)
from src.entry_policy.automatic_buy_runtime_repository_v1 import (
    AutomaticBuyRuntimeRepositoryError,
    build_runtime_item_v1,
)
from src.entry_policy.automatic_buy_execution_handoff_application_v1 import (
    AutomaticBuyExecutorHandoffError,
    submit_automatic_buy_plan_to_shared_handoff_v1,
)
from src.entry_policy.automatic_buy_source_runtime_input_writer_v1 import (
    AutomaticBuyCanonicalZoneSourceRequestV1,
    AutomaticBuyCanonicalZoneUniverseSourceRequestV1,
    AutomaticBuyFreshSourceCandidateRequestV1,
    AutomaticBuySourceRuntimeInputConflictError,
    AutomaticBuySourceRuntimeInputRequestV1,
    AutomaticBuySourceRuntimeInputWriterError,
    resolve_canonical_zone_source_runtime_input_request_v1,
    resolve_first_actionable_canonical_zone_source_runtime_input_request_v1,
    resolve_fresh_source_runtime_input_request_v1,
    write_automatic_buy_source_runtime_input_v1,
)
from src.entry_policy.automatic_buy_runtime_contract_v1 import AutomaticBuyRuntimeContractError
from src.executor.execution_handoff_v1 import RUNTIME_MODE_DRY_RUN, ExecutionHandoffRepositoryV1

RUNNER_NAME: Final[str] = "run_automatic_buy_dry_run_acceptance_v1"

# Not caller-configurable. The CLI exposes no flag for any of these.
EXECUTOR_MODE: Final[str] = RUNTIME_MODE_DRY_RUN
RUNTIME_OWNER: Final[str] = "gurkdb"
EXECUTOR_IDENTITY: Final[str] = "shared-executor-v1"

SAFETY_MARKERS: Final[dict[str, int]] = {
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "live_authority": 0,
}

ALLOWED_INPUT_KEYS: Final[frozenset[str]] = frozenset({
    "evaluation_ts_utc",
    "trading_account_id",
    "venue",
    "asset_id",
    "market",
    "strategy_bucket_id",
    "strategy_id",
    "strategy_version",
    "setup_id",
    "setup_ready",
    "current_price",
    "entry_zone_low",
    "entry_zone_high",
    "re_entry_zone_low",
    "re_entry_zone_high",
    "setup_evidence_id",
    "setup_observed_ts_utc",
    "source_provenance",
})
_OPTIONAL_INPUT_KEYS: Final[frozenset[str]] = frozenset({
    "entry_zone_low", "entry_zone_high", "re_entry_zone_low", "re_entry_zone_high",
})
_REQUIRED_INPUT_KEYS: Final[frozenset[str]] = ALLOWED_INPUT_KEYS - _OPTIONAL_INPUT_KEYS
FRESH_SOURCE_INPUT_KEYS: Final[frozenset[str]] = frozenset({
    "trading_account_id",
    "venue",
    "asset_id",
    "market",
    "strategy_bucket_id",
    "strategy_id",
    "strategy_version",
    "setup_id",
    "setup_ready",
    "entry_zone_low",
    "entry_zone_high",
    "re_entry_zone_low",
    "re_entry_zone_high",
})
_FRESH_SOURCE_REQUIRED_INPUT_KEYS: Final[frozenset[str]] = (
    FRESH_SOURCE_INPUT_KEYS - _OPTIONAL_INPUT_KEYS
)
CANONICAL_ZONE_SOURCE_INPUT_KEYS: Final[frozenset[str]] = frozenset({
    "trading_account_id",
    "venue",
    "asset_id",
    "market",
    "strategy_bucket_id",
    "strategy_id",
    "strategy_version",
})
CANONICAL_ZONE_UNIVERSE_SOURCE_INPUT_KEYS: Final[frozenset[str]] = frozenset({
    "trading_account_id", "venue", "strategy_bucket_id", "strategy_id", "strategy_version",
})


class AutomaticBuyDryRunAcceptanceCliError(ValueError):
    pass


class AutomaticBuyDryRunAcceptanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class AutomaticBuyDryRunAcceptanceResultV1:
    runtime_input_id: int
    source_snapshot_key: str
    candidate_state: str
    gate_state: str | None
    gate_reason: str | None
    planner_state: str
    planner_reason: str | None
    handoff_id: int | None
    plan_reference_id: str | None
    plan_content_hash: str | None
    executor_mode: str
    runtime_owner: str
    executor_identity: str
    safety_markers: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "runtime_input_id": self.runtime_input_id,
            "source_snapshot_key": self.source_snapshot_key,
            "candidate_state": self.candidate_state,
            "gate_state": self.gate_state,
            "gate_reason": self.gate_reason,
            "planner_state": self.planner_state,
            "planner_reason": self.planner_reason,
            "handoff_id": self.handoff_id,
            "plan_reference_id": self.plan_reference_id,
            "plan_content_hash": self.plan_content_hash,
            "executor_mode": self.executor_mode,
            "runtime_owner": self.runtime_owner,
            "executor_identity": self.executor_identity,
            "safety_markers": dict(self.safety_markers),
        }


def _load_audit_reasons(conn: Any, *, idempotency_key: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT candidate_reason_code, gate_reason_code, planner_reason_code
            FROM automatic_buy_evaluation_audit_v1
            WHERE idempotency_key = %s
            LIMIT 1
            """,
            (idempotency_key,),
        )
        row = cur.fetchone()
    if row is None:
        raise AutomaticBuyDryRunAcceptanceError("AUDIT_EVIDENCE_MISSING")
    return dict(row)


def run_automatic_buy_dry_run_acceptance_v1(
    conn: Any,
    *,
    request: AutomaticBuySourceRuntimeInputRequestV1,
    handoff_repository: ExecutionHandoffRepositoryV1 | None = None,
) -> AutomaticBuyDryRunAcceptanceResultV1:
    """Run the exact canonical path once for one bounded source snapshot.

    Never permits any executor_mode other than DRY_RUN, any runtime_owner
    other than ``gurkdb``, or any executor_identity other than
    ``shared-executor-v1``. Callers own the DB transaction boundary: on any
    exception raised before the internal commit below, no source-input row,
    audit row, or handoff exists that a caller-side rollback cannot cleanly
    undo (idempotent replay recovers safely either way).
    """
    written_input = write_automatic_buy_source_runtime_input_v1(conn, request=request)
    item = build_runtime_item_v1(conn, runtime_input=written_input)
    outcome = evaluate_automatic_buy_runtime_item_v1(conn, item=item)
    audit_reasons = _load_audit_reasons(conn, idempotency_key=outcome.idempotency_key)
    conn.commit()

    handoff_id: int | None = None
    plan_reference_id: str | None = None
    plan_content_hash: str | None = None

    if outcome.planner_state == PLANNER_STATE_STAGED:
        if outcome.plan is None:
            raise AutomaticBuyDryRunAcceptanceError("STAGED_OUTCOME_MISSING_TYPED_PLAN")
        repository = handoff_repository if handoff_repository is not None else ExecutionHandoffRepositoryV1()
        handoff = submit_automatic_buy_plan_to_shared_handoff_v1(
            plan=outcome.plan,
            account_mode=item.runtime_input.account_mode,
            executor_identity=EXECUTOR_IDENTITY,
            runtime_owner=RUNTIME_OWNER,
            handoff_repository=repository,
            executor_mode_override=EXECUTOR_MODE,
        )
        if handoff.executor_mode != EXECUTOR_MODE:
            raise AutomaticBuyDryRunAcceptanceError("HANDOFF_EXECUTOR_MODE_NOT_DRY_RUN")
        if handoff.executor_credential_binding_id is not None:
            raise AutomaticBuyDryRunAcceptanceError("DRY_RUN_HANDOFF_CREDENTIAL_BINDING_NOT_NULL")
        if handoff.executor_identity != EXECUTOR_IDENTITY or handoff.runtime_owner != RUNTIME_OWNER:
            raise AutomaticBuyDryRunAcceptanceError("HANDOFF_IDENTITY_MISMATCH")
        handoff_id = handoff.handoff_id
        plan_reference_id = handoff.plan_reference_id
        plan_content_hash = handoff.plan_content_hash

    return AutomaticBuyDryRunAcceptanceResultV1(
        runtime_input_id=written_input.automatic_buy_runtime_input_id,
        source_snapshot_key=written_input.source_snapshot_key,
        candidate_state=outcome.candidate_state,
        gate_state=outcome.gate_state,
        gate_reason=audit_reasons.get("gate_reason_code"),
        planner_state=outcome.planner_state,
        planner_reason=audit_reasons.get("planner_reason_code"),
        handoff_id=handoff_id,
        plan_reference_id=plan_reference_id,
        plan_content_hash=plan_content_hash,
        executor_mode=EXECUTOR_MODE,
        runtime_owner=RUNTIME_OWNER,
        executor_identity=EXECUTOR_IDENTITY,
        safety_markers=dict(SAFETY_MARKERS),
    )


def _parse_ts(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise AutomaticBuyDryRunAcceptanceCliError("INVALID_TIMESTAMP_FIELD")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AutomaticBuyDryRunAcceptanceCliError("INVALID_TIMESTAMP_FIELD") from exc
    if parsed.tzinfo is None:
        raise AutomaticBuyDryRunAcceptanceCliError("NAIVE_TIMESTAMP_FIELD")
    return parsed.astimezone(UTC)


def _parse_decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise AutomaticBuyDryRunAcceptanceCliError(f"INVALID_DECIMAL_FIELD:{field}")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise AutomaticBuyDryRunAcceptanceCliError(f"INVALID_DECIMAL_FIELD:{field}") from exc


def _parse_decimal_or_none(value: object, *, field: str) -> Decimal | None:
    if value is None:
        return None
    return _parse_decimal(value, field=field)


def _parse_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AutomaticBuyDryRunAcceptanceCliError(f"INVALID_INTEGER_FIELD:{field}")
    return value


def parse_source_request_from_json(payload: dict[str, Any]) -> AutomaticBuySourceRuntimeInputRequestV1:
    if not isinstance(payload, dict):
        raise AutomaticBuyDryRunAcceptanceCliError("INPUT_JSON_MUST_BE_OBJECT")

    unexpected = set(payload) - ALLOWED_INPUT_KEYS
    if unexpected:
        raise AutomaticBuyDryRunAcceptanceCliError(
            "FORBIDDEN_OR_UNKNOWN_INPUT_FIELDS:" + ",".join(sorted(unexpected))
        )
    missing = _REQUIRED_INPUT_KEYS - set(payload)
    if missing:
        raise AutomaticBuyDryRunAcceptanceCliError(
            "MISSING_REQUIRED_INPUT_FIELDS:" + ",".join(sorted(missing))
        )

    if not isinstance(payload["setup_ready"], bool):
        raise AutomaticBuyDryRunAcceptanceCliError("INVALID_BOOLEAN_FIELD:setup_ready")

    return AutomaticBuySourceRuntimeInputRequestV1(
        evaluation_ts_utc=_parse_ts(payload["evaluation_ts_utc"]),
        trading_account_id=_parse_int(payload["trading_account_id"], field="trading_account_id"),
        venue=str(payload["venue"]),
        asset_id=_parse_int(payload["asset_id"], field="asset_id"),
        market=str(payload["market"]),
        strategy_bucket_id=str(payload["strategy_bucket_id"]),
        strategy_id=str(payload["strategy_id"]),
        strategy_version=str(payload["strategy_version"]),
        setup_id=str(payload["setup_id"]),
        setup_ready=payload["setup_ready"],
        current_price=_parse_decimal(payload["current_price"], field="current_price"),
        entry_zone_low=_parse_decimal_or_none(payload.get("entry_zone_low"), field="entry_zone_low"),
        entry_zone_high=_parse_decimal_or_none(payload.get("entry_zone_high"), field="entry_zone_high"),
        re_entry_zone_low=_parse_decimal_or_none(payload.get("re_entry_zone_low"), field="re_entry_zone_low"),
        re_entry_zone_high=_parse_decimal_or_none(payload.get("re_entry_zone_high"), field="re_entry_zone_high"),
        setup_evidence_id=str(payload["setup_evidence_id"]),
        setup_observed_ts_utc=_parse_ts(payload["setup_observed_ts_utc"]),
        source_provenance=str(payload["source_provenance"]),
    )


def parse_fresh_source_candidate_from_json(payload: dict[str, Any]) -> AutomaticBuyFreshSourceCandidateRequestV1:
    """Parse source/setup identity while forbidding caller price and time facts."""
    if not isinstance(payload, dict):
        raise AutomaticBuyDryRunAcceptanceCliError("INPUT_JSON_MUST_BE_OBJECT")
    unexpected = set(payload) - FRESH_SOURCE_INPUT_KEYS
    if unexpected:
        raise AutomaticBuyDryRunAcceptanceCliError(
            "FORBIDDEN_OR_UNKNOWN_FRESH_SOURCE_FIELDS:" + ",".join(sorted(unexpected))
        )
    missing = _FRESH_SOURCE_REQUIRED_INPUT_KEYS - set(payload)
    if missing:
        raise AutomaticBuyDryRunAcceptanceCliError(
            "MISSING_REQUIRED_FRESH_SOURCE_FIELDS:" + ",".join(sorted(missing))
        )
    if not isinstance(payload["setup_ready"], bool):
        raise AutomaticBuyDryRunAcceptanceCliError("INVALID_BOOLEAN_FIELD:setup_ready")
    return AutomaticBuyFreshSourceCandidateRequestV1(
        trading_account_id=_parse_int(payload["trading_account_id"], field="trading_account_id"),
        venue=str(payload["venue"]),
        asset_id=_parse_int(payload["asset_id"], field="asset_id"),
        market=str(payload["market"]),
        strategy_bucket_id=str(payload["strategy_bucket_id"]),
        strategy_id=str(payload["strategy_id"]),
        strategy_version=str(payload["strategy_version"]),
        setup_id=str(payload["setup_id"]),
        setup_ready=payload["setup_ready"],
        entry_zone_low=_parse_decimal_or_none(payload.get("entry_zone_low"), field="entry_zone_low"),
        entry_zone_high=_parse_decimal_or_none(payload.get("entry_zone_high"), field="entry_zone_high"),
        re_entry_zone_low=_parse_decimal_or_none(payload.get("re_entry_zone_low"), field="re_entry_zone_low"),
        re_entry_zone_high=_parse_decimal_or_none(payload.get("re_entry_zone_high"), field="re_entry_zone_high"),
    )


def parse_canonical_zone_source_request_from_json(payload: dict[str, Any]) -> AutomaticBuyCanonicalZoneSourceRequestV1:
    if not isinstance(payload, dict):
        raise AutomaticBuyDryRunAcceptanceCliError("INPUT_JSON_MUST_BE_OBJECT")
    unexpected = set(payload) - CANONICAL_ZONE_SOURCE_INPUT_KEYS
    if unexpected:
        raise AutomaticBuyDryRunAcceptanceCliError(
            "FORBIDDEN_OR_UNKNOWN_CANONICAL_ZONE_SOURCE_FIELDS:" + ",".join(sorted(unexpected))
        )
    missing = CANONICAL_ZONE_SOURCE_INPUT_KEYS - set(payload)
    if missing:
        raise AutomaticBuyDryRunAcceptanceCliError(
            "MISSING_REQUIRED_CANONICAL_ZONE_SOURCE_FIELDS:" + ",".join(sorted(missing))
        )
    return AutomaticBuyCanonicalZoneSourceRequestV1(
        trading_account_id=_parse_int(payload["trading_account_id"], field="trading_account_id"),
        venue=str(payload["venue"]),
        asset_id=_parse_int(payload["asset_id"], field="asset_id"),
        market=str(payload["market"]),
        strategy_bucket_id=str(payload["strategy_bucket_id"]),
        strategy_id=str(payload["strategy_id"]),
        strategy_version=str(payload["strategy_version"]),
    )


def parse_canonical_zone_universe_source_request_from_json(
    payload: dict[str, Any],
) -> AutomaticBuyCanonicalZoneUniverseSourceRequestV1:
    if not isinstance(payload, dict):
        raise AutomaticBuyDryRunAcceptanceCliError("INPUT_JSON_MUST_BE_OBJECT")
    unexpected = set(payload) - CANONICAL_ZONE_UNIVERSE_SOURCE_INPUT_KEYS
    if unexpected:
        raise AutomaticBuyDryRunAcceptanceCliError(
            "FORBIDDEN_OR_UNKNOWN_CANONICAL_ZONE_UNIVERSE_SOURCE_FIELDS:" + ",".join(sorted(unexpected))
        )
    missing = CANONICAL_ZONE_UNIVERSE_SOURCE_INPUT_KEYS - set(payload)
    if missing:
        raise AutomaticBuyDryRunAcceptanceCliError(
            "MISSING_REQUIRED_CANONICAL_ZONE_UNIVERSE_SOURCE_FIELDS:" + ",".join(sorted(missing))
        )
    return AutomaticBuyCanonicalZoneUniverseSourceRequestV1(
        trading_account_id=_parse_int(payload["trading_account_id"], field="trading_account_id"),
        venue=str(payload["venue"]),
        strategy_bucket_id=str(payload["strategy_bucket_id"]),
        strategy_id=str(payload["strategy_id"]),
        strategy_version=str(payload["strategy_version"]),
    )


def _load_payload(input_json: Path) -> dict[str, Any]:
    text = sys.stdin.read() if str(input_json) == "-" else input_json.read_text()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AutomaticBuyDryRunAcceptanceCliError(f"INVALID_INPUT_JSON:{exc}") from exc
    if not isinstance(payload, dict):
        raise AutomaticBuyDryRunAcceptanceCliError("INPUT_JSON_MUST_BE_OBJECT")
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Bounded DRY_RUN-only automatic BUY acceptance producer. Accepts only "
            "source/market/setup evidence; all account-owned decision-gate evidence "
            "is always sourced from canonical Issue #474 evidence, never from input."
        ),
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--input-json", type=Path,
        help="Path to bounded source/setup evidence JSON, or '-' for stdin.",
    )
    input_group.add_argument(
        "--fresh-source-json", type=Path,
        help=(
            "Path to source/setup identity JSON without price, evidence id, or timestamps; "
            "the latest canonical public price snapshot supplies those facts."
        ),
    )
    input_group.add_argument(
        "--canonical-zone-source-json", type=Path,
        help=(
            "Path to source identity only; canonical current price and the latest completed "
            "4h execution-zone context supply setup facts."
        ),
    )
    input_group.add_argument(
        "--canonical-zone-universe-source-json", type=Path,
        help="Identity only; resolves the first actionable setup from canonical account markets, 4h zones, and prices.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    started_ts = datetime.now(UTC)
    print(f"STARTED runner={RUNNER_NAME} mode=DRY_RUN worker_count=1", flush=True)
    print(
        "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 live_authority=0 "
        "decision_gate=automatic_buy_gate_v1 execution_planner=automatic_buy_planner_v1 "
        "executor=shared_handoff_dry_run_only",
        flush=True,
    )

    try:
        input_json = next(item for item in (
            args.input_json, args.fresh_source_json, args.canonical_zone_source_json,
            args.canonical_zone_universe_source_json,
        ) if item is not None)
        payload = _load_payload(input_json)
        request = parse_source_request_from_json(payload) if args.input_json is not None else None
        fresh_candidate = (
            None if args.fresh_source_json is None else parse_fresh_source_candidate_from_json(payload)
        )
        canonical_zone_candidate = (
            None if args.canonical_zone_source_json is None
            else parse_canonical_zone_source_request_from_json(payload)
        )
        canonical_zone_universe = (
            None if args.canonical_zone_universe_source_json is None
            else parse_canonical_zone_universe_source_request_from_json(payload)
        )
    except (OSError, AutomaticBuyDryRunAcceptanceCliError) as exc:
        print(f"FAILED runner={RUNNER_NAME} result=invalid_input detail={exc}", file=sys.stderr)
        return 1

    try:
        conn = get_db_connection()
    except Exception as exc:  # pragma: no cover - environment-dependent
        print(f"FAILED runner={RUNNER_NAME} result=db_unavailable detail={exc}", file=sys.stderr)
        return 1

    try:
        try:
            if fresh_candidate is not None:
                request = resolve_fresh_source_runtime_input_request_v1(
                    conn,
                    candidate=fresh_candidate,
                    now_utc=datetime.now(UTC),
                )
            if canonical_zone_candidate is not None:
                request = resolve_canonical_zone_source_runtime_input_request_v1(
                    conn,
                    candidate=canonical_zone_candidate,
                    now_utc=datetime.now(UTC),
                )
            if canonical_zone_universe is not None:
                request = resolve_first_actionable_canonical_zone_source_runtime_input_request_v1(
                    conn,
                    universe=canonical_zone_universe,
                    now_utc=datetime.now(UTC),
                )
            assert request is not None
            result = run_automatic_buy_dry_run_acceptance_v1(conn, request=request)
        except (
            AutomaticBuySourceRuntimeInputWriterError,
            AutomaticBuySourceRuntimeInputConflictError,
            AutomaticBuyRuntimeRepositoryError,
            AutomaticBuyRuntimeContractError,
            AutomaticBuyIdempotencyPayloadConflictError,
            AutomaticBuyExecutorHandoffError,
            AutomaticBuyDryRunAcceptanceError,
        ) as exc:
            conn.rollback()
            print(f"FAILED runner={RUNNER_NAME} result=acceptance_failed detail={exc}", file=sys.stderr)
            return 1
    finally:
        conn.close()

    finished_ts = datetime.now(UTC)
    print(json.dumps(result.as_dict(), sort_keys=True), flush=True)
    print(
        f"FINISHED runner={RUNNER_NAME} result=ok "
        f"elapsed_seconds={(finished_ts - started_ts).total_seconds():.3f} "
        f"candidate_state={result.candidate_state} gate_state={result.gate_state} "
        f"planner_state={result.planner_state} handoff_id={result.handoff_id}",
        flush=True,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
