from __future__ import annotations

"""Integrity-gated C1-only final-holdout dataset builder for Issue #593.

This is deliberately separate from the discovery/validation builder. It can open
only the frozen final-holdout split, only for preregistered candidate C1, and only
after the frozen canonical source-content fingerprint verifies successfully.

The holdout has exactly one canonical output location: the directory that
already contains the frozen ``split_manifest_v1.json`` supplied on the command
line. There is deliberately no ``--output-dir`` override, so the holdout cannot
be reopened in a second location by pointing the runner somewhere else.

That per-directory checkpoint is a convenience, not the security boundary: a
caller could copy a byte-identical ``split_manifest_v1.json`` +
``source_integrity_v1.json`` pair into a second directory and try to "open" a
fresh checkpoint namespace there. The actual one-shot gate is a trusted,
non-caller-selectable **opened-state registry** under the repository's
canonical research state hierarchy (``REGISTRY_ROOT`` below), keyed by a
SHA-256 fingerprint of ``(manifest_sha256, source_integrity_composite_sha256,
venue, candidate_id, phase)``. Because the key is derived purely from frozen
content, not from any caller-supplied path, copying the manifest/integrity
pair anywhere resolves to the exact same registry entry and is denied.
"""

import argparse
import hashlib
import json
import os
import signal
import socket
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.research.multi_horizon_rotation_dataset_builder_v1 import observed_asset_ids_at_asof
from src.research.multi_horizon_rotation_replay_v1 import CANDIDATE_SPECS, evaluate_candidate
from src.research.run_multi_horizon_rotation_dataset_builder_v1 import (
    asof_grid,
    build_validation_row,
    chunk_asof_grid_by_utc_day,
    fetch_asset_coverage,
    fetch_candles_for_chunk,
    fetch_rotation_v1_points,
    finalize_artifact_bundle,
    json_default,
    manifest_fingerprint,
    parse_ts,
    reconcile_partial_to_checkpoint,
    replay_candles_at_asof,
    write_json_atomic,
    write_row,
)
from src.research.run_multi_horizon_rotation_source_integrity_v1 import (
    build_integrity_payload,
    verify_existing,
)

RUNNER_NAME = "run_multi_horizon_rotation_c1_final_holdout_builder_v1"
RUNNER_VERSION = "1.0.0"
CANDIDATE_ID = "C1"
PHASE = "final_holdout"
MANIFEST_BASENAME = "split_manifest_v1.json"
INTEGRITY_BASENAME = "source_integrity_v1.json"
RESUMABLE_TERMINAL_STATES = ("RUNNING", "INTERRUPTED")

# Trusted, non-caller-selectable authoritative opened-state registry. This is
# NOT the canonical run directory (which is caller-supplied via --split-manifest)
# and it is never overridable from the CLI or the environment: it is the only
# thing that makes the holdout genuinely one-shot even if the frozen manifest
# and source-integrity artifact are copied byte-for-byte into a second directory.
REGISTRY_ROOT = Path(__file__).resolve().parents[2] / "data" / "research" / "multi_horizon_rotation_c1_final_holdout_registry_v1"


class RunnerInterrupted(Exception):
    def __init__(self, signum: int) -> None:
        self.signum = signum


def emit(message: str) -> None:
    print(message, flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="#593 integrity-gated C1-only final holdout builder")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--split-manifest", required=True)
    parser.add_argument("--source-integrity", required=True)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args(argv)


def load_manifest(path: Path, *, venue: str) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("split manifest must be a JSON object")
    if raw.get("venue") != venue:
        raise ValueError("venue does not match frozen split manifest")
    if raw.get("final_holdout_inspected") is not False:
        raise ValueError("final holdout must still be unopened before this one-shot builder starts")
    splits = raw.get("splits")
    if not isinstance(splits, dict) or PHASE not in splits:
        raise ValueError("split manifest missing final_holdout")
    return raw


def select_c1_spec() -> Any:
    matches = [spec for spec in CANDIDATE_SPECS if spec.candidate_id == CANDIDATE_ID]
    if len(matches) != 1:
        raise ValueError("frozen C1 candidate spec missing or ambiguous")
    return matches[0]


def canonical_run_dir(manifest_path: Path, integrity_path: Path) -> Path:
    """Derive the single canonical run directory and fail closed on any bypass attempt.

    There is no ``--output-dir`` argument. The canonical directory is always
    the directory that holds the frozen ``split_manifest_v1.json`` the caller
    supplied, and the frozen ``source_integrity_v1.json`` must live in that
    exact same directory. This removes the ability to reopen the holdout by
    pointing an alternate output location at an otherwise-unopened manifest.
    """
    if manifest_path.name != MANIFEST_BASENAME:
        raise ValueError(f"--split-manifest must be named {MANIFEST_BASENAME}")
    if integrity_path.name != INTEGRITY_BASENAME:
        raise ValueError(f"--source-integrity must be named {INTEGRITY_BASENAME}")
    manifest_dir = manifest_path.resolve().parent
    integrity_dir = integrity_path.resolve().parent
    if integrity_dir != manifest_dir:
        raise ValueError(
            "source integrity artifact must live in the same canonical run directory "
            "as the frozen split manifest"
        )
    return manifest_dir


def checkpoint_path(canonical_dir: Path) -> Path:
    return canonical_dir / ".final_holdout_c1_checkpoint_v1.json"


def write_checkpoint(
    path: Path,
    *,
    venue: str,
    manifest_sha256: str,
    source_integrity_composite_sha256: str,
    phase_start: datetime,
    phase_end: datetime,
    last_completed_asof: datetime | None,
    asofs_completed: int,
    row_count: int,
    partial_bytes: int,
    source_query_count: int,
    source_rows_read: int,
    terminal_state: str,
) -> None:
    payload = {
        "runner": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "venue": venue,
        "candidate_id": CANDIDATE_ID,
        "manifest_sha256": manifest_sha256,
        "source_integrity_composite_sha256": source_integrity_composite_sha256,
        "phase": PHASE,
        "phase_start": json_default(phase_start),
        "phase_end": json_default(phase_end),
        "last_completed_asof": None if last_completed_asof is None else json_default(last_completed_asof),
        "asofs_completed": asofs_completed,
        "row_count": row_count,
        "partial_bytes": partial_bytes,
        "source_query_count": source_query_count,
        "source_rows_read": source_rows_read,
        "terminal_state": terminal_state,
        "updated_ts_utc": json_default(datetime.now(UTC)),
    }
    write_json_atomic(path, payload)


def load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError("resume requested but checkpoint is missing")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("checkpoint must be a JSON object")
    return raw


def validate_resume_checkpoint(
    checkpoint: dict[str, Any],
    *,
    venue: str,
    manifest_sha256: str,
    source_integrity_composite_sha256: str,
) -> None:
    if checkpoint.get("runner") != RUNNER_NAME or checkpoint.get("runner_version") != RUNNER_VERSION:
        raise ValueError("checkpoint runner/version mismatch")
    if checkpoint.get("venue") != venue:
        raise ValueError("checkpoint venue mismatch")
    if checkpoint.get("candidate_id") != CANDIDATE_ID:
        raise ValueError("checkpoint candidate_id mismatch")
    if checkpoint.get("phase") != PHASE:
        raise ValueError("checkpoint phase mismatch")
    if checkpoint.get("manifest_sha256") != manifest_sha256:
        raise ValueError("checkpoint split manifest mismatch")
    if checkpoint.get("source_integrity_composite_sha256") != source_integrity_composite_sha256:
        raise ValueError("checkpoint source integrity mismatch")
    terminal_state = checkpoint.get("terminal_state")
    if terminal_state not in RESUMABLE_TERMINAL_STATES:
        raise ValueError(
            f"checkpoint terminal_state={terminal_state!r} is not resumable; "
            "only RUNNING or INTERRUPTED checkpoints may be resumed"
        )
    for key in ("asofs_completed", "row_count", "partial_bytes"):
        if int(checkpoint.get(key, -1)) < 0:
            raise ValueError(f"checkpoint {key} must be non-negative")


def mark_checkpoint_terminal(path: Path, *, terminal_state: str) -> None:
    checkpoint = load_checkpoint(path)
    last_raw = checkpoint.get("last_completed_asof")
    write_checkpoint(
        path,
        venue=str(checkpoint["venue"]),
        manifest_sha256=str(checkpoint["manifest_sha256"]),
        source_integrity_composite_sha256=str(checkpoint["source_integrity_composite_sha256"]),
        phase_start=parse_ts(checkpoint["phase_start"]),
        phase_end=parse_ts(checkpoint["phase_end"]),
        last_completed_asof=None if last_raw is None else parse_ts(last_raw),
        asofs_completed=int(checkpoint["asofs_completed"]),
        row_count=int(checkpoint["row_count"]),
        partial_bytes=int(checkpoint["partial_bytes"]),
        source_query_count=int(checkpoint.get("source_query_count", 0)),
        source_rows_read=int(checkpoint.get("source_rows_read", 0)),
        terminal_state=terminal_state,
    )


def registry_key_for(
    *,
    manifest_sha256: str,
    source_integrity_composite_sha256: str,
    venue: str,
    candidate_id: str,
    phase: str,
) -> str:
    """Path-independent fingerprint: identical manifest+integrity content always
    resolves to the same registry entry, regardless of which directory the
    caller supplied them from."""
    material = {
        "manifest_sha256": manifest_sha256,
        "source_integrity_composite_sha256": source_integrity_composite_sha256,
        "venue": venue,
        "candidate_id": candidate_id,
        "phase": phase,
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def registry_entry_path(key: str) -> Path:
    return REGISTRY_ROOT / f"{key}.json"


def load_registry_entry(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("registry entry must be a JSON object")
    return raw


def _registry_payload(
    *,
    venue: str,
    manifest_sha256: str,
    source_integrity_composite_sha256: str,
    terminal_state: str,
    opened_run_dir: str,
) -> dict[str, object]:
    return {
        "runner": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "venue": venue,
        "candidate_id": CANDIDATE_ID,
        "phase": PHASE,
        "manifest_sha256": manifest_sha256,
        "source_integrity_composite_sha256": source_integrity_composite_sha256,
        "terminal_state": terminal_state,
        # Informational only. The registry key above -- not this field -- is
        # what makes reopening from a copied directory impossible.
        "opened_run_dir": opened_run_dir,
        "updated_ts_utc": json_default(datetime.now(UTC)),
    }


def write_registry_entry(
    path: Path,
    *,
    venue: str,
    manifest_sha256: str,
    source_integrity_composite_sha256: str,
    terminal_state: str,
    opened_run_dir: str,
) -> None:
    """Create-or-overwrite. Only safe for transitions on an entry this process
    already knows it owns (terminal-state updates); never used for the initial
    fresh-run open, which must use ``create_registry_entry_exclusive`` instead."""
    write_json_atomic(
        path,
        _registry_payload(
            venue=venue,
            manifest_sha256=manifest_sha256,
            source_integrity_composite_sha256=source_integrity_composite_sha256,
            terminal_state=terminal_state,
            opened_run_dir=opened_run_dir,
        ),
    )


def create_registry_entry_exclusive(
    path: Path,
    *,
    venue: str,
    manifest_sha256: str,
    source_integrity_composite_sha256: str,
    terminal_state: str,
    opened_run_dir: str,
) -> bool:
    """Atomic exclusive-create: write a temp file, fsync it durable, then link it
    into place. ``os.link`` either creates the target or raises ``FileExistsError``
    atomically at the filesystem level -- there is no check-then-create window, so
    two concurrent callers racing on the same fingerprint can never both "win".

    Returns True if this call created the entry, False if another entry (from any
    concurrent or prior caller) already occupies this exact fingerprint -- in which
    case nothing is written or mutated here at all.
    """
    payload = _registry_payload(
        venue=venue,
        manifest_sha256=manifest_sha256,
        source_integrity_composite_sha256=source_integrity_composite_sha256,
        terminal_state=terminal_state,
        opened_run_dir=opened_run_dir,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path = Path(temp_name)
        try:
            os.link(temp_path, path)
        except FileExistsError:
            return False
        return True
    finally:
        if temp_name is not None:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass


def run_lease_path(registry_key: str) -> Path:
    """Deterministic, path-independent lease location derived purely from the
    same authoritative registry key -- never caller-selectable, never derived
    from --split-manifest/--source-integrity paths.

    This is ONE authoritative exclusive run lease shared by both fresh and
    resumed execution of the same opened holdout fingerprint. A fresh runner
    acquires it immediately after winning authoritative registry creation and
    holds it continuously through replay/checkpoint/finalization; a resume
    must acquire the SAME lease before it may reconcile or replay anything.
    This is what prevents a fresh runner and a concurrent --resume of the
    checkpoint it just created from ever running at the same time.
    """
    return REGISTRY_ROOT / f"{registry_key}.run_lease.json"


def acquire_run_lease_exclusive(path: Path, *, registry_key: str) -> bool:
    """Atomic exclusive-create, identical primitive to registry creation: write a
    temp file, fsync it durable, then ``os.link`` it into place. At most one
    concurrent execution (fresh or resumed) of the same opened holdout can ever
    hold the lease.

    Deliberately has NO automatic staleness/timeout recovery: a lease left behind
    by a hard-killed process (SIGKILL, not caught by our SIGINT/SIGTERM handling)
    stays forever and permanently denies further fresh/--resume execution until a
    human clears it. An unsafe automatic timeout could let two live executions run
    concurrently, which is exactly the bug this lease exists to prevent.
    """
    payload = {
        "registry_key": registry_key,
        "runner": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "acquired_ts_utc": json_default(datetime.now(UTC)),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path = Path(temp_name)
        try:
            os.link(temp_path, path)
        except FileExistsError:
            return False
        return True
    finally:
        if temp_name is not None:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass


def release_run_lease(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def mark_registry_terminal(path: Path, *, terminal_state: str, identity: dict[str, str]) -> None:
    """Create-or-update the registry entry into a terminal state.

    Falls back to the caller-supplied identity fields when the entry does not
    exist yet (e.g. it vanished independently of the local checkpoint), so a
    FAILED/INTERRUPTED transition always leaves the fingerprint permanently
    locked rather than silently no-op'ing.
    """
    existing = load_registry_entry(path)
    opened_run_dir = str(existing.get("opened_run_dir", "")) if existing else identity.get("opened_run_dir", "")
    write_registry_entry(
        path,
        venue=identity["venue"],
        manifest_sha256=identity["manifest_sha256"],
        source_integrity_composite_sha256=identity["source_integrity_composite_sha256"],
        terminal_state=terminal_state,
        opened_run_dir=opened_run_dir,
    )


def install_interrupt_handlers() -> dict[int, Any]:
    def handle_interrupt(signum: int, _frame: Any) -> None:
        raise RunnerInterrupted(signum)

    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    for signum in previous:
        signal.signal(signum, handle_interrupt)
    return previous


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(dotenv_path=".env", override=False)
    started = time.perf_counter()
    previous_handlers = install_interrupt_handlers()
    emit(
        f"STARTED runner={RUNNER_NAME} version={RUNNER_VERSION} phase={PHASE} candidate={CANDIDATE_ID} "
        f"workers=1 resume={int(bool(args.resume))} final_holdout_access=GATED"
    )
    emit(
        "SAFETY research_only=1 market_only=1 database_reads=1 database_writes=0 account_awareness=0 "
        "decision_gate=none execution_planner=none executor=none broker_private_calls=0 broker_writes=0 "
        "order_submission=0 live_orders=0"
    )

    conn = None
    partial_path: Path | None = None
    cp_path: Path | None = None
    registry_path: Path | None = None
    registry_identity: dict[str, str] | None = None
    run_lease_held_path: Path | None = None
    opened = False
    last_completed_asof: datetime | None = None
    asofs_completed = 0
    row_count = 0
    source_query_count = 0
    source_rows_read = 0
    try:
        manifest_path = Path(args.split_manifest)
        integrity_path = Path(args.source_integrity)
        canonical_dir = canonical_run_dir(manifest_path, integrity_path)
        artifact_path = canonical_dir / "final_holdout_c1_rows_v1.jsonl"
        partial_path = canonical_dir / ".final_holdout_c1_rows_v1.jsonl.partial"
        summary_path = canonical_dir / "final_holdout_c1_summary_v1.json"
        cp_path = checkpoint_path(canonical_dir)

        manifest = load_manifest(manifest_path, venue=args.venue)
        manifest_sha = manifest_fingerprint(manifest)
        split = manifest["splits"][PHASE]
        phase_start = parse_ts(split["start"])
        phase_end = parse_ts(split["end"])

        checkpoint: dict[str, Any] | None = None
        if args.resume:
            if not cp_path.exists() or not partial_path.exists():
                raise ValueError(
                    "resume requested but the canonical checkpoint and/or partial artifact is missing"
                )
            checkpoint = load_checkpoint(cp_path)
            if checkpoint.get("terminal_state") not in RESUMABLE_TERMINAL_STATES:
                raise ValueError(
                    f"checkpoint terminal_state={checkpoint.get('terminal_state')!r} is not resumable; "
                    "only RUNNING or INTERRUPTED checkpoints may be resumed"
                )
            # The locking key is derived from the checkpoint's OWN recorded identity
            # (not yet-recomputed values), so we can locate -- and if needed fail --
            # the authoritative registry entry even if the DB/integrity step below
            # never succeeds. From this point on the run is "opened": any ordinary
            # failure must permanently lock this fingerprint as FAILED, not leave it
            # silently resumable.
            registry_identity = {
                "venue": args.venue,
                "candidate_id": CANDIDATE_ID,
                "phase": PHASE,
                "manifest_sha256": str(checkpoint["manifest_sha256"]),
                "source_integrity_composite_sha256": str(checkpoint["source_integrity_composite_sha256"]),
            }
            registry_key = registry_key_for(
                manifest_sha256=registry_identity["manifest_sha256"],
                source_integrity_composite_sha256=registry_identity["source_integrity_composite_sha256"],
                venue=args.venue,
                candidate_id=CANDIDATE_ID,
                phase=PHASE,
            )
            registry_path = registry_entry_path(registry_key)
            registry_entry = load_registry_entry(registry_path)
            if registry_entry is None or registry_entry.get("terminal_state") not in RESUMABLE_TERMINAL_STATES:
                raise ValueError(
                    "authoritative opened-state registry entry is missing or not resumable; "
                    "refuses to resume"
                )

            # Exclusive per-registry-entry run lease: at most one concurrent
            # execution (fresh OR resumed) of the same opened holdout may proceed.
            # This is the SAME lease a fresh runner acquires right after it wins
            # authoritative registry creation, so a resume that sees a RUNNING
            # registry/checkpoint while the fresh runner that created them is
            # still active must fail closed right here -- before any partial
            # reconciliation or replay. This is a single atomic exclusive-create
            # (same primitive as registry creation), not a check-then-create
            # sequence, so a second concurrent resume (or a resume racing the
            # still-active fresh runner) can never slip through. It must be
            # acquired BEFORE any partial reconciliation, BEFORE the
            # checkpoint/registry are ever mutated by this process, and BEFORE
            # "opened" is set -- a lost race leaves nothing behind to clean up
            # and must not mark the checkpoint or registry FAILED.
            lease_path = run_lease_path(registry_key)
            if not acquire_run_lease_exclusive(lease_path, registry_key=registry_key):
                raise ValueError(
                    "the run lease for this opened holdout is already held by another "
                    "execution (fresh or resumed); refuses to run concurrently"
                )
            run_lease_held_path = lease_path
            opened = True
        else:
            if artifact_path.exists() or summary_path.exists() or cp_path.exists() or partial_path.exists():
                raise ValueError(
                    "final holdout output already exists in the canonical run directory; "
                    "runner is one-shot and refuses to reopen or overwrite it. Use --resume "
                    "to continue an interrupted RUNNING checkpoint."
                )

        conn = get_db_connection()

        # Hard gate: recompute and verify frozen source content before any holdout
        # candidate replay or forward-label construction is allowed. This must
        # happen on both a fresh run and a resumed run.
        emit("PHASE_STARTED name=verify_frozen_source_integrity")
        gate_started = time.perf_counter()
        current_integrity = build_integrity_payload(
            conn,
            venue=args.venue,
            split_manifest=manifest,
        )
        verify_existing(integrity_path, current_integrity)
        composite_sha = current_integrity["composite_sha256"]
        emit(
            "PHASE_FINISHED name=verify_frozen_source_integrity state=VERIFIED "
            f"composite_sha256={composite_sha} "
            f"elapsed_s={time.perf_counter() - gate_started:.3f}"
        )

        source_span = manifest["source_span"]
        coverage = fetch_asset_coverage(conn, venue=args.venue, through_ts=parse_ts(source_span["end"]))
        pit_index = fetch_rotation_v1_points(conn, venue=args.venue, through_ts=phase_end)
        c1_spec = select_c1_spec()
        spec_by_id = {CANDIDATE_ID: c1_spec}
        full_grid = asof_grid(phase_start, phase_end)

        if args.resume:
            assert checkpoint is not None
            validate_resume_checkpoint(
                checkpoint,
                venue=args.venue,
                manifest_sha256=manifest_sha,
                source_integrity_composite_sha256=composite_sha,
            )
            reconcile_partial_to_checkpoint(partial_path, checkpoint)
            last_raw = checkpoint.get("last_completed_asof")
            last_completed_asof = None if last_raw is None else parse_ts(last_raw)
            asofs_completed = int(checkpoint["asofs_completed"])
            row_count = int(checkpoint["row_count"])
            source_query_count = int(checkpoint.get("source_query_count", 0))
            source_rows_read = int(checkpoint.get("source_rows_read", 0))
            if last_completed_asof is not None:
                if last_completed_asof not in full_grid:
                    raise ValueError("checkpoint last_completed_asof is outside frozen final-holdout grid")
                expected_completed = full_grid.index(last_completed_asof) + 1
                if asofs_completed != expected_completed:
                    raise ValueError(
                        f"checkpoint asofs_completed mismatch: actual={asofs_completed} "
                        f"expected={expected_completed}"
                    )
            elif asofs_completed != 0:
                raise ValueError("checkpoint has completed as-of count without last_completed_asof")
            emit(
                f"RESUME checkpoint={cp_path} last_completed_asof={last_completed_asof} "
                f"asofs_completed={asofs_completed} rows={row_count} partial_bytes={checkpoint['partial_bytes']}"
            )
        else:
            # Authoritative fingerprint-keyed gate: identical manifest + source
            # integrity content resolves to the same registry entry no matter what
            # directory the caller supplied it from, so a byte-identical copy in a
            # second directory cannot open a second checkpoint namespace.
            registry_identity = {
                "venue": args.venue,
                "candidate_id": CANDIDATE_ID,
                "phase": PHASE,
                "manifest_sha256": manifest_sha,
                "source_integrity_composite_sha256": composite_sha,
            }
            registry_key = registry_key_for(
                manifest_sha256=manifest_sha,
                source_integrity_composite_sha256=composite_sha,
                venue=args.venue,
                candidate_id=CANDIDATE_ID,
                phase=PHASE,
            )
            registry_path = registry_entry_path(registry_key)

            # Freeze the one-shot holdout-open state -- registry first (authoritative),
            # then the local checkpoint -- immediately after integrity verification
            # succeeds and immediately before the first holdout replay. This is a
            # single atomic exclusive-create, not a check-then-write sequence: two
            # concurrent fresh runners racing on the same fingerprint (e.g. a copied
            # manifest/integrity pair) can never both win. The loser gets False back
            # and creates or mutates nothing -- no local checkpoint, no replay.
            won_registry_creation = create_registry_entry_exclusive(
                registry_path,
                venue=args.venue,
                manifest_sha256=manifest_sha,
                source_integrity_composite_sha256=composite_sha,
                terminal_state="RUNNING",
                opened_run_dir=str(canonical_dir),
            )
            if not won_registry_creation:
                raise ValueError(
                    "final holdout is already opened for this frozen manifest/source-integrity "
                    "fingerprint (registry entry exists); runner is one-shot and refuses to reopen "
                    "it, including from a different directory holding a copy of the same manifest "
                    "and integrity artifact, and including a concurrent fresh invocation racing on "
                    "the same fingerprint"
                )

            # From here the run is "opened": any ordinary failure must permanently
            # lock this fingerprint as FAILED. A lost race above never reaches here.
            opened = True

            # Acquire the SAME run lease a --resume would need, immediately after
            # winning registry creation and BEFORE the local RUNNING checkpoint is
            # ever created. This closes the concurrency window a --resume could
            # otherwise exploit: --resume requires both the local checkpoint AND
            # partial file to exist (checked above), so while this fresh runner
            # holds the registry entry but has not yet written the local
            # checkpoint, no --resume can find anything to resume. Once the local
            # checkpoint exists, the lease is already held, so a concurrent
            # --resume's own lease-acquire attempt fails closed before it ever
            # reconciles or replays.
            lease_path = run_lease_path(registry_key)
            if not acquire_run_lease_exclusive(lease_path, registry_key=registry_key):
                raise ValueError(
                    "the run lease for this opened holdout fingerprint is already held by "
                    "another execution; refuses to start a fresh run concurrently"
                )
            run_lease_held_path = lease_path

            partial_path.touch(exist_ok=False)
            write_checkpoint(
                cp_path,
                venue=args.venue,
                manifest_sha256=manifest_sha,
                source_integrity_composite_sha256=composite_sha,
                phase_start=phase_start,
                phase_end=phase_end,
                last_completed_asof=None,
                asofs_completed=0,
                row_count=0,
                partial_bytes=0,
                source_query_count=0,
                source_rows_read=0,
                terminal_state="RUNNING",
            )
            emit(
                f"OPENED registry={registry_path} checkpoint={cp_path} state=RUNNING "
                f"composite_sha256={composite_sha}"
            )

        remaining_grid = [
            asof for asof in full_grid
            if last_completed_asof is None or asof > last_completed_asof
        ]

        emit("PHASE_STARTED name=build_final_holdout_c1_artifact")
        build_started = time.perf_counter()
        with partial_path.open("ab") as handle:
            for chunk in chunk_asof_grid_by_utc_day(remaining_grid):
                chunk_candles, close_maps, fetched = fetch_candles_for_chunk(
                    conn,
                    venue=args.venue,
                    chunk_asofs=chunk,
                    phase_end=phase_end,
                )
                source_query_count += 1
                source_rows_read += fetched
                for asof in chunk:
                    observed_ids = observed_asset_ids_at_asof(coverage, asof_ts=asof)
                    replay_candles = replay_candles_at_asof(
                        chunk_candles=chunk_candles,
                        observed_asset_ids=observed_ids,
                        asof_ts=asof,
                    )
                    results = evaluate_candidate(
                        candles_by_asset=replay_candles,
                        asof_ts=asof,
                        spec=c1_spec,
                        venue=args.venue,
                    )
                    for result in results:
                        if result.candidate_id != CANDIDATE_ID:
                            raise ValueError("non-C1 result escaped C1-only holdout gate")
                        row = build_validation_row(
                            result=result,
                            close_by_ts=close_maps.get(result.asset_id, {}),
                            spec_by_id=spec_by_id,
                            pit_index=pit_index,
                            phase_end=phase_end,
                        )
                        write_row(handle, row)
                        row_count += 1
                    handle.flush()
                    os.fsync(handle.fileno())
                    asofs_completed += 1
                    last_completed_asof = asof
                    partial_bytes = handle.tell()
                    write_checkpoint(
                        cp_path,
                        venue=args.venue,
                        manifest_sha256=manifest_sha,
                        source_integrity_composite_sha256=composite_sha,
                        phase_start=phase_start,
                        phase_end=phase_end,
                        last_completed_asof=last_completed_asof,
                        asofs_completed=asofs_completed,
                        row_count=row_count,
                        partial_bytes=partial_bytes,
                        source_query_count=source_query_count,
                        source_rows_read=source_rows_read,
                        terminal_state="RUNNING",
                    )
                    if asofs_completed % 96 == 0:
                        emit(
                            f"HEARTBEAT phase={PHASE} candidate={CANDIDATE_ID} asofs_completed={asofs_completed} "
                            f"rows_built={row_count} observed_assets={len(observed_ids)} "
                            f"source_queries={source_query_count} source_rows_read={source_rows_read}"
                        )

        if asofs_completed != len(full_grid):
            raise ValueError(f"as-of completion mismatch: {asofs_completed} != {len(full_grid)}")

        summary = {
            "runner": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "phase": PHASE,
            "candidate_id": CANDIDATE_ID,
            "venue": args.venue,
            "manifest_sha256": manifest_sha,
            "source_integrity_composite_sha256": composite_sha,
            "phase_start": phase_start.isoformat().replace("+00:00", "Z"),
            "phase_end_exclusive": phase_end.isoformat().replace("+00:00", "Z"),
            "asof_count": asofs_completed,
            "row_count": row_count,
            "source_query_count": source_query_count,
            "source_rows_read": source_rows_read,
            "final_holdout_access": "OPENED_FOR_PREREGISTERED_C1_ONLY",
            "c2_access": "DENY",
            "c3_access": "DENY",
            "database_writes": 0,
            "live_orders": 0,
            "resume_supported": True,
        }

        def persist_finished_checkpoint(final_bytes: int) -> None:
            write_checkpoint(
                cp_path,
                venue=args.venue,
                manifest_sha256=manifest_sha,
                source_integrity_composite_sha256=composite_sha,
                phase_start=phase_start,
                phase_end=phase_end,
                last_completed_asof=last_completed_asof,
                asofs_completed=asofs_completed,
                row_count=row_count,
                partial_bytes=final_bytes,
                source_query_count=source_query_count,
                source_rows_read=source_rows_read,
                terminal_state="FINISHED",
            )
            assert registry_path is not None and registry_identity is not None
            mark_registry_terminal(registry_path, terminal_state="FINISHED", identity=registry_identity)
            if run_lease_held_path is not None:
                release_run_lease(run_lease_held_path)

        finalize_artifact_bundle(
            partial_path=partial_path,
            artifact_path=artifact_path,
            summary_path=summary_path,
            summary=summary,
            persist_finished_checkpoint=persist_finished_checkpoint,
        )
        partial_path = None
        emit(
            f"PHASE_FINISHED name=build_final_holdout_c1_artifact rows={row_count} asofs={asofs_completed} "
            f"elapsed_s={time.perf_counter() - build_started:.3f}"
        )
        emit(
            f"FINISHED runner={RUNNER_NAME} result=PASS phase={PHASE} candidate={CANDIDATE_ID} "
            f"rows={row_count} c2_access=DENY c3_access=DENY database_writes=0 live_orders=0 "
            f"elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 0
    except RunnerInterrupted as exc:
        if opened:
            if cp_path is not None and partial_path is not None and partial_path.exists() and cp_path.exists():
                try:
                    mark_checkpoint_terminal(cp_path, terminal_state="INTERRUPTED")
                except Exception:
                    pass
            if registry_path is not None and registry_identity is not None:
                try:
                    mark_registry_terminal(registry_path, terminal_state="INTERRUPTED", identity=registry_identity)
                except Exception:
                    pass
            if run_lease_held_path is not None:
                release_run_lease(run_lease_held_path)
        emit(
            f"INTERRUPTED runner={RUNNER_NAME} signal={signal.Signals(exc.signum).name} "
            f"partial_artifact={partial_path} checkpoint={cp_path} registry={registry_path} "
            f"final_holdout_access=GATED database_writes=0 elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 128 + exc.signum
    except Exception as exc:
        # Once the holdout was actually opened (registry + checkpoint created, or a
        # resumed run of a previously-opened fingerprint), any ordinary failure must
        # permanently lock the run as FAILED so it can never be silently resumed or
        # reopened. A failure before opening (e.g. integrity verification itself)
        # must not create any opened state at all.
        if opened:
            if cp_path is not None and cp_path.exists():
                try:
                    mark_checkpoint_terminal(cp_path, terminal_state="FAILED")
                except Exception:
                    pass
            if registry_path is not None and registry_identity is not None:
                try:
                    mark_registry_terminal(registry_path, terminal_state="FAILED", identity=registry_identity)
                except Exception:
                    pass
            if run_lease_held_path is not None:
                release_run_lease(run_lease_held_path)
        emit(
            f"FAILED runner={RUNNER_NAME} error={exc.__class__.__name__}:{exc} "
            f"partial_artifact={partial_path} checkpoint={cp_path} registry={registry_path} "
            f"final_holdout_access=GATED database_writes=0 elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 1
    finally:
        if conn is not None:
            conn.close()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
