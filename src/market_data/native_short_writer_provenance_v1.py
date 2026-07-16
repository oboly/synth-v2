from __future__ import annotations

"""Pure provenance contract for every native SHORT writer-capable invocation."""

import os
import re
import socket
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


PROVENANCE_CONTRACT_VERSION = "native_short_writer_provenance_v1"
CANONICAL_REPOSITORY_WRITER_OWNER = "synth-chain-4h"
TEST_REPOSITORY_COMMIT_SHA = "0" * 40
TEST_WRITER_ENTRYPOINT = "tests/native_short_writer_provenance_v1"

CHAIN_TRIGGER_TYPE = "SCHEDULED_4H_MARKET_CHAIN"
MANUAL_MAP_TRIGGER_TYPE = "MANUAL_NATIVE_SHORT_MAP_LEDGER_CANARY"
MANUAL_SCOPE_STATUS_TRIGGER_TYPE = "MANUAL_NATIVE_SHORT_SCOPE_STATUS"
MANUAL_MAP_LEVEL_TRIGGER_TYPE = "MANUAL_NATIVE_SHORT_MAP_LEVEL_STATUS"
MANUAL_SCOPE_SEED_TRIGGER_TYPE = "MANUAL_NATIVE_SHORT_SCOPE_SEED_CANARY"
TEST_TRIGGER_TYPE = "TEST"

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_CHAIN_ENTRYPOINTS = frozenset(
    {
        "scripts/run_chain_4h.sh",
        "scripts/run_native_short_scope_status_chain_once.sh",
        "src.market_data.run_native_short_scope_status_chain_v1",
    }
)
_MANUAL_ENTRYPOINT_CONTRACTS = {
    "src.market_data.run_native_short_map_materializer_v1": (
        "run_native_short_map_materializer_v1",
        MANUAL_MAP_TRIGGER_TYPE,
    ),
    "src.market_data.run_native_short_map_level_status_materializer_v1": (
        "run_native_short_map_level_status_materializer_v1",
        MANUAL_MAP_LEVEL_TRIGGER_TYPE,
    ),
    "src.market_data.run_native_short_scope_status_chain_v1": (
        "run_native_short_scope_status_chain_v1",
        MANUAL_SCOPE_STATUS_TRIGGER_TYPE,
    ),
    "src.market_data.run_native_short_map_scope_seed_canary_v1": (
        "native_short_map_scope_seed_canary_v1",
        MANUAL_SCOPE_SEED_TRIGGER_TYPE,
    ),
}
_PRODUCTION_RUNNERS = frozenset(
    {
        "run_native_short_map_materializer_v1",
        "run_native_short_map_level_status_materializer_v1",
        "run_native_short_scope_status_chain_v1",
        "native_short_map_scope_seed_canary_v1",
    }
)


class NativeShortWriterExecutionMode(StrEnum):
    CHAIN = "CHAIN"
    MANUAL = "MANUAL"
    TEST = "TEST"


class NativeShortWriterProvenanceState(StrEnum):
    ATTRIBUTABLE = "ATTRIBUTABLE"
    LEGACY_UNATTRIBUTED = "LEGACY_UNATTRIBUTED"
    INVALID_PROVENANCE = "INVALID_PROVENANCE"


class NativeShortWriterProvenanceError(ValueError):
    pass


def _required_text(value: str | None, field: str, *, maximum: int) -> str:
    normalized = "" if value is None else str(value).strip()
    if not normalized:
        raise NativeShortWriterProvenanceError(f"PROVENANCE_REQUIRED field={field}")
    if len(normalized) > maximum:
        raise NativeShortWriterProvenanceError(
            f"PROVENANCE_TOO_LONG field={field} maximum={maximum}"
        )
    return normalized


@dataclass(frozen=True)
class NativeShortWriterProvenance:
    writer_entrypoint: str
    repository_writer_owner: str
    runner_name: str
    runner_version: str
    execution_mode: NativeShortWriterExecutionMode | str
    invocation_uuid: str
    repository_commit_sha: str
    host_name: str
    process_id: int
    trigger_type: str
    trigger_ref: str
    provenance_contract_version: str = PROVENANCE_CONTRACT_VERSION


def validate_native_short_writer_provenance(
    value: NativeShortWriterProvenance,
) -> NativeShortWriterProvenance:
    if not isinstance(value, NativeShortWriterProvenance):
        raise NativeShortWriterProvenanceError("PROVENANCE_OBJECT_REQUIRED")

    contract = _required_text(
        value.provenance_contract_version,
        "provenance_contract_version",
        maximum=40,
    )
    if contract != PROVENANCE_CONTRACT_VERSION:
        raise NativeShortWriterProvenanceError(
            f"PROVENANCE_CONTRACT_UNSUPPORTED value={contract}"
        )
    entrypoint = _required_text(value.writer_entrypoint, "writer_entrypoint", maximum=160)
    owner = _required_text(
        value.repository_writer_owner,
        "repository_writer_owner",
        maximum=96,
    )
    if owner != CANONICAL_REPOSITORY_WRITER_OWNER:
        raise NativeShortWriterProvenanceError(
            f"REPOSITORY_WRITER_OWNER_UNSUPPORTED value={owner}"
        )
    runner_name = _required_text(value.runner_name, "runner_name", maximum=96)
    _required_text(value.runner_version, "runner_version", maximum=32)
    try:
        mode = NativeShortWriterExecutionMode(str(value.execution_mode))
    except ValueError as exc:
        raise NativeShortWriterProvenanceError(
            f"EXECUTION_MODE_UNSUPPORTED value={value.execution_mode}"
        ) from exc

    invocation_uuid = _required_text(value.invocation_uuid, "invocation_uuid", maximum=36)
    try:
        parsed_uuid = uuid.UUID(invocation_uuid)
    except (ValueError, AttributeError) as exc:
        raise NativeShortWriterProvenanceError("INVOCATION_UUID_INVALID") from exc
    if str(parsed_uuid) != invocation_uuid:
        raise NativeShortWriterProvenanceError("INVOCATION_UUID_NOT_CANONICAL")

    commit_sha = _required_text(
        value.repository_commit_sha,
        "repository_commit_sha",
        maximum=40,
    )
    if _SHA_PATTERN.fullmatch(commit_sha) is None:
        raise NativeShortWriterProvenanceError("REPOSITORY_COMMIT_SHA_INVALID")
    _required_text(value.host_name, "host_name", maximum=128)
    if isinstance(value.process_id, bool) or not isinstance(value.process_id, int):
        raise NativeShortWriterProvenanceError("PROCESS_ID_INVALID")
    if value.process_id <= 0 or value.process_id > 4_294_967_295:
        raise NativeShortWriterProvenanceError("PROCESS_ID_INVALID")
    trigger_type = _required_text(value.trigger_type, "trigger_type", maximum=64)
    _required_text(value.trigger_ref, "trigger_ref", maximum=255)

    if mode == NativeShortWriterExecutionMode.CHAIN:
        if entrypoint not in _CHAIN_ENTRYPOINTS:
            raise NativeShortWriterProvenanceError(
                f"CHAIN_ENTRYPOINT_UNSUPPORTED value={entrypoint}"
            )
        if runner_name != "run_native_short_scope_status_chain_v1":
            raise NativeShortWriterProvenanceError(
                f"CHAIN_RUNNER_CONTRADICTION value={runner_name}"
            )
        if trigger_type != CHAIN_TRIGGER_TYPE:
            raise NativeShortWriterProvenanceError(
                f"CHAIN_TRIGGER_CONTRADICTION value={trigger_type}"
            )
        if commit_sha == TEST_REPOSITORY_COMMIT_SHA:
            raise NativeShortWriterProvenanceError("TEST_COMMIT_NOT_ALLOWED_IN_PRODUCTION")
    elif mode == NativeShortWriterExecutionMode.MANUAL:
        expected_manual_contract = _MANUAL_ENTRYPOINT_CONTRACTS.get(entrypoint)
        if expected_manual_contract is None:
            raise NativeShortWriterProvenanceError(
                f"MANUAL_ENTRYPOINT_UNSUPPORTED value={entrypoint}"
            )
        expected_runner_name, expected_trigger_type = expected_manual_contract
        if runner_name != expected_runner_name:
            raise NativeShortWriterProvenanceError(
                "MANUAL_RUNNER_CONTRADICTION "
                f"entrypoint={entrypoint} value={runner_name} expected={expected_runner_name}"
            )
        if trigger_type != expected_trigger_type:
            raise NativeShortWriterProvenanceError(
                "MANUAL_TRIGGER_CONTRADICTION "
                f"entrypoint={entrypoint} value={trigger_type} expected={expected_trigger_type}"
            )
        if commit_sha == TEST_REPOSITORY_COMMIT_SHA:
            raise NativeShortWriterProvenanceError("TEST_COMMIT_NOT_ALLOWED_IN_PRODUCTION")
    else:
        if entrypoint != TEST_WRITER_ENTRYPOINT:
            raise NativeShortWriterProvenanceError(
                f"TEST_ENTRYPOINT_CONTRADICTION value={entrypoint}"
            )
        if trigger_type != TEST_TRIGGER_TYPE:
            raise NativeShortWriterProvenanceError(
                f"TEST_TRIGGER_CONTRADICTION value={trigger_type}"
            )
        if commit_sha != TEST_REPOSITORY_COMMIT_SHA:
            raise NativeShortWriterProvenanceError("TEST_COMMIT_CONTRADICTION")
        if runner_name in _PRODUCTION_RUNNERS:
            raise NativeShortWriterProvenanceError(
                f"TEST_RUNNER_MASQUERADES_AS_PRODUCTION value={runner_name}"
            )
    return value


def build_process_provenance(
    *,
    writer_entrypoint: str,
    runner_name: str,
    runner_version: str,
    execution_mode: NativeShortWriterExecutionMode | str,
    repository_commit_sha: str,
    trigger_type: str,
    trigger_ref: str,
    invocation_uuid: str | None = None,
) -> NativeShortWriterProvenance:
    """Capture only current process facts; service/timer identity is never inferred."""
    value = NativeShortWriterProvenance(
        writer_entrypoint=writer_entrypoint,
        repository_writer_owner=CANONICAL_REPOSITORY_WRITER_OWNER,
        runner_name=runner_name,
        runner_version=runner_version,
        execution_mode=execution_mode,
        invocation_uuid=invocation_uuid or str(uuid.uuid4()),
        repository_commit_sha=repository_commit_sha,
        host_name=socket.gethostname(),
        process_id=os.getpid(),
        trigger_type=trigger_type,
        trigger_ref=trigger_ref,
    )
    return validate_native_short_writer_provenance(value)


def build_explicit_test_provenance(
    *,
    runner_name: str = "native_short_writer_test_v1",
    invocation_uuid: str = "00000000-0000-4000-8000-000000000001",
    trigger_ref: str = "native-short-test-suite",
) -> NativeShortWriterProvenance:
    """Return deterministic TEST-only provenance that validation forbids in production modes."""
    return validate_native_short_writer_provenance(
        NativeShortWriterProvenance(
            writer_entrypoint=TEST_WRITER_ENTRYPOINT,
            repository_writer_owner=CANONICAL_REPOSITORY_WRITER_OWNER,
            runner_name=runner_name,
            runner_version="test-v1",
            execution_mode=NativeShortWriterExecutionMode.TEST,
            invocation_uuid=invocation_uuid,
            repository_commit_sha=TEST_REPOSITORY_COMMIT_SHA,
            host_name="test-host",
            process_id=1,
            trigger_type=TEST_TRIGGER_TYPE,
            trigger_ref=trigger_ref,
        )
    )


def classify_persisted_native_short_writer_provenance(
    row: Mapping[str, Any],
) -> NativeShortWriterProvenanceState:
    if row.get("provenance_contract_version") is None:
        return NativeShortWriterProvenanceState.LEGACY_UNATTRIBUTED
    try:
        validate_native_short_writer_provenance(
            NativeShortWriterProvenance(
                provenance_contract_version=str(row["provenance_contract_version"]),
                writer_entrypoint=str(row.get("writer_entrypoint") or ""),
                repository_writer_owner=str(row.get("repository_writer_owner") or ""),
                runner_name=str(row.get("runner_name") or ""),
                runner_version=str(row.get("runner_version") or ""),
                execution_mode=str(row.get("execution_mode") or ""),
                invocation_uuid=str(row.get("run_uuid") or row.get("invocation_uuid") or ""),
                repository_commit_sha=str(row.get("repository_commit_sha") or ""),
                host_name=str(row.get("host_name") or ""),
                process_id=row.get("process_id"),
                trigger_type=str(row.get("trigger_type") or ""),
                trigger_ref=str(row.get("trigger_ref") or ""),
            )
        )
    except (KeyError, NativeShortWriterProvenanceError):
        return NativeShortWriterProvenanceState.INVALID_PROVENANCE
    return NativeShortWriterProvenanceState.ATTRIBUTABLE
