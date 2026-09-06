from __future__ import annotations

"""
ENGINE: run_target_capture_calibration_v1
MODE: historical (research-only)

Phase C runner for issue #559. Builds a deterministic, read-only historical
target-capture calibration report for ONE symbol and ONE timeframe (1h or
4h) per invocation, by wiring together three already-merged, independently
owned building blocks -- never reimplementing any of them:

- #555 `src.research.run_historical_fib_map_episode_substrate_v1` /
  `src.research.historical_fib_map_episode_substrate_v1`: DB fetch
  (`fetch_asset_id`, `fetch_ema_state_prehistory_candles`, `fetch_candles`,
  `fetch_forward_tail_candles`) and deterministic Fib/map episode
  construction (`build_episodes`) -- owns EMA-state prehistory, Fib
  geometry, and forward-scan lifecycle labeling.
- #559 Phase A `src.research.target_capture_calibration_adapter_v1`: maps
  each #555 `EpisodeRecord` target role (T1/T2) into a #224
  `ExecutionOffsetEpisodeV1` + `TargetEpisodeAnalysisContextV1`
  (`map_episode_records`) and PIT-filters the already-fetched historical
  candle set into the #224 `ReplayCandle` window each mapped episode is
  actually valid for (`convert_forward_candles`).
- #559 Phase B `src.research.target_capture_calibration_analysis_v1`:
  deterministic candidate-buffer economics/disposition
  (`build_calibration_report`), which itself delegates all fill/near-miss
  replay to the shared #224 `execution_offset_replay_report_v1`.

This runner adds only: CLI/DB orchestration, run identity, exclusion
counting/reporting, and immutable publish -- no Fib geometry, no replay
policy math, no calibration economics of its own.

INPUT:
- obs_market_candle (SELECT only, via #555's fetch functions)
- asset (SELECT only, via #555's fetch_asset_id)

OUTPUT:
- immutable JSON {report_v1.json, manifest_v1.json} pair under
  data/research/target_capture_calibration_v1/<venue>/<symbol>/<timeframe>/<run_id>/
  where <run_id> is a SHA-256 of every dataset-defining parameter (this
  runner's builder/contract version, the #555 substrate / #559 adapter /
  #559 analysis versions actually used, venue, symbol, timeframe, from_ts,
  to_ts, episode_stride_candles, max_episodes, target_roles,
  min_sample_threshold) PLUS source_input_sha256 -- the SAME #555 candle
  content fingerprint (`compute_source_input_sha256`, reused unmodified
  from #555) the underlying episodes were built from. Folding in every
  upstream module version means a change to Fib geometry, adapter mapping,
  or calibration economics always produces a new run_id/path, never a
  silent content change at an existing immutable path.

CLI:
python -m src.research.run_target_capture_calibration_v1 \
  --venue bitvavo \
  --symbol BTC \
  --timeframe 4h \
  --from-ts "2026-01-01 00:00:00" \
  --to-ts "2026-06-01 00:00:00"

HISTORICAL:
- supported (this runner is historical-only)

SAFETY MARKERS:
research_only=1 market_only=1 account_awareness=0 decision_permission=0
execution_intent=0 broker_calls=0 broker_writes=0 orders=0 db_writes=0
production_profile_writes=0 runtime_activation=0
broker_private_calls=0 order_submission=0 live_orders=0
decision_gate=none execution_planner=none executor=none

NOTES:
- read-only DB access; no writes of any kind to the database
- reuses #555's fetch functions verbatim (imported, not reimplemented) --
  same EMA-state prehistory / requested-window / forward-tail fetch
  discipline, same bounded/chunked SELECT retrieval, same signal-safe
  cancellation boundaries
- reuses #555's `build_episodes` verbatim for Fib/map episode construction
  -- this runner never touches Fib geometry, anchor selection, trend
  reconstruction, or forward-scan lifecycle labeling
- reuses #559 Phase A's `map_episode_records`/`convert_forward_candles`
  verbatim for T1/T2 -> #224 episode mapping and PIT candle filtering --
  this runner never reimplements role->level mapping, side resolution, or
  the full-interval PIT candle rule
- reuses #559 Phase B's `build_calibration_report` verbatim for all
  candidate-buffer economics/disposition -- this runner never reimplements
  quantiles, capture-rate economics, or disposition rules
- every mapped episode receives the FULL fetched historical candle set
  (prehistory + requested + forward tail) as `convert_forward_candles`'
  `candles` argument; that function itself narrows to the exact
  `[issued_ts_utc, valid_until_ts_utc]` full-interval PIT window for that
  specific episode -- no separate re-fetch per episode, no candle window
  invented by this runner
- explicit, non-silent (record, target_role) exclusions from
  `map_episode_records` are always counted and reported in the manifest
  (`excluded_target_episode_count`, `exclusion_reason_counts`,
  `exclusions`), never dropped silently
- output files are written exactly once via this runner's own
  `publish_immutable_pair` -- the same atomic staging-directory-then-rename
  discipline #555's `publish_immutable_run` established, parameterized on
  this runner's `report_v1.json`/`manifest_v1.json` filenames (#555's
  version hardcodes its own `episodes_v1.json`/`manifest_v1.json` names, so
  it is not reused directly here): a repeat run with identical inputs is
  idempotent, a conflicting repeat run is refused, nothing is written
  unless the full build+mapping+calibration pipeline completes
  successfully
- fails closed (a single `FAILED reason=<code> ...` terminal line, non-zero
  exit) at every stage boundary: invalid arguments, asset lookup, source
  fetch, source validation, episode build, target-episode mapping,
  calibration, or output write. `NO_CALIBRATION_INPUTS` (every mapped
  target-episode candidate was excluded, or #555 built zero episodes) is a
  `FAILED reason=calibration_failed` outcome, not an empty/degenerate
  report written to disk.
"""

import argparse
import hashlib
import json
import os
import shutil
import signal as signal_module
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from src.research import target_capture_calibration_adapter_v1 as adapter_v1
from src.research import target_capture_calibration_analysis_v1 as analysis_v1
from src.research.historical_fib_map_episode_substrate_v1 import (
    BUILDER_NAME as SUBSTRATE_BUILDER_NAME,
    BUILDER_VERSION as SUBSTRATE_BUILDER_VERSION,
    CONTRACT_VERSION as SUBSTRATE_CONTRACT_VERSION,
    BuildCancelled,
    EpisodeConfig,
    EpisodeRecord,
    EpisodeSubstrateError,
    HistoricalCandle,
    build_episodes,
    resolve_config,
    validate_candle_sequence,
)
from src.research.run_historical_fib_map_episode_substrate_v1 import (
    ArgParseError,
    DEFAULT_BUILD_PROGRESS_INTERVAL_CANDLES,
    DEFAULT_CHUNK_CANDLES,
    _Parser,
    _SignalState,
    compute_source_input_sha256,
    fetch_asset_id,
    fetch_candles,
    fetch_ema_state_prehistory_candles,
    fetch_forward_tail_candles,
    format_ts_for_query,
    parse_ts_arg,
)
from src.research.target_capture_calibration_adapter_v1 import (
    TARGET_ROLES,
    TargetCaptureAdapterError,
    TargetEpisodeExclusionV1,
)
from src.research.target_capture_calibration_analysis_v1 import (
    CalibrationInputV1,
    TargetCaptureCalibrationError,
    build_calibration_report,
    render_calibration_report_json,
)

BUILDER_NAME = "target_capture_calibration_runner_v1"
BUILDER_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0.0"

DEFAULT_OUTPUT_DIR = "data/research/target_capture_calibration_v1"
DEFAULT_TARGET_ROLES = ",".join(TARGET_ROLES)


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        description=(
            "Build the deterministic historical target-capture calibration "
            "report for one symbol/timeframe (#559 Phase C)."
        )
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", required=True, choices=["1h", "4h"])
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--episode-stride-candles", type=int, default=1)
    parser.add_argument("--max-episodes", type=int, default=None)
    parser.add_argument("--target-roles", default=DEFAULT_TARGET_ROLES)
    parser.add_argument(
        "--min-sample-threshold",
        type=int,
        default=analysis_v1.MIN_SAMPLE_THRESHOLD,
    )
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--chunk-size-candles", type=int, default=DEFAULT_CHUNK_CANDLES)
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Raises `ArgParseError` (never `SystemExit`) for a genuine parse failure,
    reusing #555's `_Parser`/`ArgParseError` override so `main()` owns a
    single `FAILED reason=invalid_arguments` terminal-line/exit-code
    contract, exactly like the #555 runner. `--help` is unaffected.
    """
    return _build_parser().parse_args(argv)


def parse_target_roles(text: str) -> list[str]:
    roles = [part.strip() for part in text.split(",") if part.strip()]
    if not roles:
        raise ValueError("--target-roles must name at least one target role")
    if len(set(roles)) != len(roles):
        raise ValueError(f"--target-roles must not repeat a role, got {text!r}")
    unsupported = [role for role in roles if role not in TARGET_ROLES]
    if unsupported:
        raise ValueError(
            f"--target-roles contains unsupported role(s) {unsupported}; "
            f"supported={list(TARGET_ROLES)}"
        )
    return roles


def validate_args(args: argparse.Namespace) -> None:
    """Reject invalid CLI arguments before any DB connection/query is made."""
    if args.episode_stride_candles <= 0:
        raise ValueError(
            f"--episode-stride-candles must be > 0, got {args.episode_stride_candles}"
        )
    if args.max_episodes is not None and args.max_episodes < 0:
        raise ValueError(f"--max-episodes must be omitted or >= 0, got {args.max_episodes}")
    if args.chunk_size_candles <= 0:
        raise ValueError(f"--chunk-size-candles must be > 0, got {args.chunk_size_candles}")
    if args.min_sample_threshold <= 0:
        raise ValueError(
            f"--min-sample-threshold must be > 0, got {args.min_sample_threshold}"
        )
    parse_target_roles(args.target_roles)

    from_ts_dt = parse_ts_arg(args.from_ts, name="--from-ts")
    to_ts_dt = parse_ts_arg(args.to_ts, name="--to-ts")
    if not from_ts_dt < to_ts_dt:
        raise ValueError(
            f"--from-ts ({args.from_ts}) must be strictly earlier than --to-ts ({args.to_ts})"
        )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_text_or_none(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def publish_immutable_pair(
    *,
    output_dir: Path,
    report_text: str,
    manifest_text: str,
) -> tuple[str, str]:
    """Atomically publish {report_v1.json, manifest_v1.json} into `output_dir`.

    Same structural guarantee as #555's `publish_immutable_run`: `output_dir`
    ends up either ABSENT or a COMPLETE, internally consistent immutable run
    directory containing BOTH files -- never a partial directory with only
    one of them. #555's `publish_immutable_run` is not reused directly here
    because it hardcodes the filenames `episodes_v1.json`/`manifest_v1.json`
    (correct for its own Fib/map episode contract, not a calibration
    report); this is the same atomic staging-directory-then-rename
    discipline, parameterized on this runner's own report/manifest names.

    Both texts are staged into a private sibling directory, individually
    `fsync`'d, the staging directory itself `fsync`'d, then published with a
    single atomic `os.rename` -- a rename either fully succeeds or does not
    happen at all, so there is no filesystem-visible intermediate state with
    only one file present. A repeat run with content-identical existing
    output is idempotent; an existing directory that is incomplete or
    content-different fails closed (`ValueError`), never silently repaired
    or overwritten.
    """
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    def _existing_or_none() -> tuple[str, str] | None:
        if not output_dir.exists():
            return None
        existing_report = _read_text_or_none(output_dir / "report_v1.json")
        existing_manifest = _read_text_or_none(output_dir / "manifest_v1.json")
        if existing_report is None or existing_manifest is None:
            raise ValueError(
                f"refusing to publish immutable run {output_dir}: existing run "
                f"directory is incomplete (report_present="
                f"{existing_report is not None} manifest_present="
                f"{existing_manifest is not None})"
            )
        existing_report_sha256 = _sha256_text(existing_report)
        existing_manifest_sha256 = _sha256_text(existing_manifest)
        candidate_report_sha256 = _sha256_text(report_text)
        candidate_manifest_sha256 = _sha256_text(manifest_text)
        if (
            existing_report_sha256 != candidate_report_sha256
            or existing_manifest_sha256 != candidate_manifest_sha256
        ):
            raise ValueError(
                f"refusing to overwrite immutable run {output_dir}: "
                f"existing report_sha256={existing_report_sha256} "
                f"candidate report_sha256={candidate_report_sha256} "
                f"existing manifest_sha256={existing_manifest_sha256} "
                f"candidate manifest_sha256={candidate_manifest_sha256}"
            )
        return existing_report_sha256, existing_manifest_sha256

    existing = _existing_or_none()
    if existing is not None:
        return existing

    staging_dir: Path | None = Path(
        tempfile.mkdtemp(dir=output_dir.parent, prefix=f".{output_dir.name}.stage-")
    )
    try:
        for name, text in (
            ("report_v1.json", report_text),
            ("manifest_v1.json", manifest_text),
        ):
            staged_path = staging_dir / name
            with open(staged_path, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())

        dir_fd = os.open(staging_dir, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

        try:
            os.rename(staging_dir, output_dir)
        except OSError:
            existing = _existing_or_none()
            if existing is not None:
                return existing
            raise
        else:
            staging_dir = None
            return _sha256_text(report_text), _sha256_text(manifest_text)
    finally:
        if staging_dir is not None and staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def compute_run_id(
    *,
    venue: str,
    symbol: str,
    timeframe: str,
    from_ts: str,
    to_ts: str,
    episode_stride_candles: int,
    max_episodes: int | None,
    target_roles: list[str],
    min_sample_threshold: int,
    source_input_sha256: str,
) -> str:
    """Deterministic run identity over every dataset-defining parameter
    AND every upstream module version actually used to build this report.

    Folding in `SUBSTRATE_BUILDER_VERSION`/`SUBSTRATE_CONTRACT_VERSION`,
    `adapter_v1.BUILDER_VERSION`, and `analysis_v1.VERSION` alongside this
    runner's own `BUILDER_VERSION`/`CONTRACT_VERSION` means a change to Fib
    geometry (#555), target-role mapping (#559 Phase A), or calibration
    economics (#559 Phase B) always produces a different run_id -- and
    therefore a different immutable path -- never a silent content change
    at an existing one. `source_input_sha256` (reused unmodified from
    #555's `compute_source_input_sha256`) closes the same gap #555 already
    documents for its own run identity: two runs with byte-identical CLI
    arguments can still see different underlying `obs_market_candle`
    content.
    """
    run_key = {
        "builder_version": BUILDER_VERSION,
        "contract_version": CONTRACT_VERSION,
        "substrate_builder_version": SUBSTRATE_BUILDER_VERSION,
        "substrate_contract_version": SUBSTRATE_CONTRACT_VERSION,
        "adapter_builder_version": adapter_v1.BUILDER_VERSION,
        "analysis_version": analysis_v1.VERSION,
        "venue": venue,
        "symbol": symbol,
        "timeframe": timeframe,
        "from_ts": from_ts,
        "to_ts": to_ts,
        "episode_stride_candles": episode_stride_candles,
        "max_episodes": max_episodes,
        "target_roles": sorted(target_roles),
        "min_sample_threshold": min_sample_threshold,
        "source_input_sha256": source_input_sha256,
    }
    canonical_text = json.dumps(run_key, sort_keys=True, separators=(",", ":"))
    return _sha256_text(canonical_text)


def build_calibration_inputs(
    mapped: list[tuple[Any, Any]],
    *,
    candles: list[HistoricalCandle],
) -> list[CalibrationInputV1]:
    """Attach PIT-filtered #224 replay candles to every mapped target episode.

    `candles` is the FULL fetched historical set (EMA-state prehistory +
    requested window + forward tail) already in memory -- the identical
    sequence `build_episodes` consumed. No separate fetch happens here:
    `adapter_v1.convert_forward_candles` narrows this shared set down to
    the exact `[episode.issued_ts_utc, episode.valid_until_ts_utc]`
    full-interval PIT window for each individual episode, per the #224
    contract #559 Phase A already implements and documents.
    """
    inputs: list[CalibrationInputV1] = []
    for episode, context in mapped:
        replay_candles = adapter_v1.convert_forward_candles(
            candles,
            issued_ts_utc=episode.issued_ts_utc,
            valid_until_ts_utc=episode.valid_until_ts_utc,
        )
        inputs.append(
            CalibrationInputV1(
                episode=episode,
                context=context,
                candles=tuple(replay_candles),
            )
        )
    return inputs


def build_manifest(
    *,
    run_id: str,
    venue: str,
    symbol: str,
    timeframe: str,
    from_ts: str,
    to_ts: str,
    episode_stride_candles: int,
    max_episodes: int | None,
    target_roles: list[str],
    min_sample_threshold: int,
    source_input_sha256: str,
    ema_state_prehistory_candle_count: int,
    requested_candle_count: int,
    forward_tail_candle_count: int,
    forward_tail_max_candles: int,
    total_candle_count: int,
    source_episode_count: int,
    mapped_target_episode_count: int,
    excluded_target_episode_count: int,
    exclusion_reason_counts: dict[str, int],
    exclusions: list[dict[str, str]],
    report_fingerprint: str,
    disposition: str,
    disposition_reason: str,
    selected_buffer_pct_fraction: str | None,
    chunk_size_candles: int,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "builder_name": BUILDER_NAME,
        "builder_version": BUILDER_VERSION,
        "contract_version": CONTRACT_VERSION,
        "upstream_substrate_builder_name": SUBSTRATE_BUILDER_NAME,
        "upstream_substrate_builder_version": SUBSTRATE_BUILDER_VERSION,
        "upstream_substrate_contract_version": SUBSTRATE_CONTRACT_VERSION,
        "upstream_adapter_builder_name": adapter_v1.BUILDER_NAME,
        "upstream_adapter_builder_version": adapter_v1.BUILDER_VERSION,
        "upstream_analysis_version": analysis_v1.VERSION,
        "venue": venue,
        "symbol": symbol,
        "timeframe": timeframe,
        "source_table": "obs_market_candle",
        "source_from_ts": from_ts,
        "source_to_ts": to_ts,
        "episode_stride_candles": episode_stride_candles,
        "max_episodes": max_episodes,
        "target_roles": sorted(target_roles),
        "min_sample_threshold": min_sample_threshold,
        # Part of run_id/dataset identity -- see compute_run_id(). Reused
        # unmodified from #555's compute_source_input_sha256 over the exact
        # ordered prehistory+requested+forward_tail candle content this
        # run's episodes were built from.
        "source_input_sha256": source_input_sha256,
        # Provenance only -- not part of run_id (see #555's manifest for the
        # same discipline).
        "ema_state_prehistory_candle_count": ema_state_prehistory_candle_count,
        "requested_window_candle_count": requested_candle_count,
        "forward_tail_candle_count": forward_tail_candle_count,
        "forward_tail_max_candles": forward_tail_max_candles,
        "total_candle_count": total_candle_count,
        "chunk_size_candles": chunk_size_candles,
        "source_episode_count": source_episode_count,
        "mapped_target_episode_count": mapped_target_episode_count,
        # Explicit, non-silent (record, target_role) exclusions from #559
        # Phase A's map_episode_records -- never dropped silently.
        "excluded_target_episode_count": excluded_target_episode_count,
        "exclusion_reason_counts": exclusion_reason_counts,
        "exclusions": exclusions,
        "report_fingerprint": report_fingerprint,
        "disposition": disposition,
        "disposition_reason": disposition_reason,
        "selected_buffer_pct_fraction": selected_buffer_pct_fraction,
        "safety_markers": {
            "research_only": 1,
            "market_only": 1,
            "account_awareness": 0,
            "decision_permission": 0,
            "execution_intent": 0,
            "broker_calls": 0,
            "broker_writes": 0,
            "orders": 0,
            "db_writes": 0,
            "production_profile_writes": 0,
            "runtime_activation": 0,
            "broker_private_calls": 0,
            "order_submission": 0,
            "live_orders": 0,
            "decision_gate": "none",
            "execution_planner": "none",
            "executor": "none",
        },
    }


FAILED_REASON_ASSET_LOOKUP = "asset_lookup_failed"
FAILED_REASON_SOURCE_FETCH = "source_fetch_failed"
FAILED_REASON_SOURCE_VALIDATION = "source_validation_failed"
FAILED_REASON_BUILD = "build_failed"
FAILED_REASON_MAPPING = "mapping_failed"
FAILED_REASON_CALIBRATION = "calibration_failed"
FAILED_REASON_OUTPUT_WRITE = "output_write_failed"


def _print_failed(reason: str, exc: BaseException, *, exit_code: int = 1) -> int:
    print(f"FAILED reason={reason} detail={exc}", flush=True)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except ArgParseError as exc:
        return _print_failed("invalid_arguments", exc, exit_code=2)
    try:
        validate_args(args)
    except ValueError as exc:
        return _print_failed("invalid_arguments", exc, exit_code=2)
    target_roles = parse_target_roles(args.target_roles)
    cfg: EpisodeConfig = resolve_config(args.timeframe)

    signal_state = _SignalState()
    signal_state.install()

    print(
        f"STARTED runner={BUILDER_NAME} mode=historical venue={args.venue} "
        f"symbol={args.symbol} timeframe={args.timeframe} "
        f"target_roles={','.join(target_roles)} workers=1 "
        f"chunk_size_candles={args.chunk_size_candles}",
        flush=True,
    )

    def _interrupted_exit() -> int:
        print(
            f"INTERRUPTED signal={signal_state.signum} "
            f"reason=stopped_at_safe_boundary_before_write",
            flush=True,
        )
        return 130 if signal_state.signum == signal_module.SIGINT else 143

    try:
        asset_id = fetch_asset_id(venue=args.venue, symbol=args.symbol)
    except Exception as exc:
        return _print_failed(FAILED_REASON_ASSET_LOOKUP, exc)
    if signal_state.triggered:
        return _interrupted_exit()

    from_ts_dt = parse_ts_arg(args.from_ts, name="--from-ts")
    to_ts_dt = parse_ts_arg(args.to_ts, name="--to-ts")

    def _prehistory_progress(count: int) -> None:
        print(f"FETCHING phase=ema_prehistory fetched={count}", flush=True)

    print("FETCHING phase=ema_prehistory target=full_available_history", flush=True)
    try:
        prehistory_candles = fetch_ema_state_prehistory_candles(
            asset_id=asset_id,
            symbol=args.symbol,
            venue=args.venue,
            interval_code=cfg.interval_code,
            from_ts=format_ts_for_query(from_ts_dt),
            chunk_size=args.chunk_size_candles,
            on_progress=_prehistory_progress,
            should_stop=lambda: signal_state.triggered,
        )
    except Exception as exc:
        return _print_failed(FAILED_REASON_SOURCE_FETCH, exc)
    print(f"FETCHING phase=ema_prehistory fetched={len(prehistory_candles)}", flush=True)
    if signal_state.triggered:
        return _interrupted_exit()

    def _fetch_progress(count: int) -> None:
        print(f"FETCHING phase=requested_window fetched={count}", flush=True)

    try:
        requested_candles = fetch_candles(
            asset_id=asset_id,
            symbol=args.symbol,
            venue=args.venue,
            interval_code=cfg.interval_code,
            from_ts=format_ts_for_query(from_ts_dt),
            to_ts=format_ts_for_query(to_ts_dt),
            chunk_size=args.chunk_size_candles,
            on_progress=_fetch_progress,
            should_stop=lambda: signal_state.triggered,
        )
    except Exception as exc:
        return _print_failed(FAILED_REASON_SOURCE_FETCH, exc)
    if signal_state.triggered:
        return _interrupted_exit()

    print(f"FETCHING phase=forward_tail target={cfg.forward_max_candles}", flush=True)
    try:
        forward_tail_candles = fetch_forward_tail_candles(
            asset_id=asset_id,
            symbol=args.symbol,
            venue=args.venue,
            interval_code=cfg.interval_code,
            to_ts=format_ts_for_query(to_ts_dt),
            limit=cfg.forward_max_candles,
        )
    except Exception as exc:
        return _print_failed(FAILED_REASON_SOURCE_FETCH, exc)
    print(f"FETCHING phase=forward_tail fetched={len(forward_tail_candles)}", flush=True)
    if signal_state.triggered:
        return _interrupted_exit()

    candles: list[HistoricalCandle] = prehistory_candles + requested_candles + forward_tail_candles
    print(
        f"FETCHED ema_prehistory_candles={len(prehistory_candles)} "
        f"requested_candles={len(requested_candles)} "
        f"forward_tail_candles={len(forward_tail_candles)} total_candles={len(candles)}",
        flush=True,
    )

    try:
        validate_candle_sequence(candles)
    except EpisodeSubstrateError as exc:
        return _print_failed(FAILED_REASON_SOURCE_VALIDATION, exc)

    source_input_sha256 = compute_source_input_sha256(candles)
    print(f"FETCHED source_input_sha256={source_input_sha256}", flush=True)

    print(f"BUILDING candles={len(candles)}", flush=True)

    def _build_progress(processed: int, total: int) -> None:
        print(f"BUILDING progress processed={processed} total={total}", flush=True)

    try:
        records: list[EpisodeRecord] = build_episodes(
            symbol=args.symbol,
            venue=args.venue,
            candles=candles,
            cfg=cfg,
            episode_stride_candles=args.episode_stride_candles,
            max_episodes=args.max_episodes,
            emit_from_ts_utc=from_ts_dt,
            emit_to_ts_utc=to_ts_dt,
            on_progress=_build_progress,
            should_stop=lambda: signal_state.triggered,
            progress_interval_candles=DEFAULT_BUILD_PROGRESS_INTERVAL_CANDLES,
        )
    except BuildCancelled:
        return _interrupted_exit()
    except Exception as exc:
        return _print_failed(FAILED_REASON_BUILD, exc)
    print(f"BUILT episodes={len(records)}", flush=True)
    if signal_state.triggered:
        return _interrupted_exit()

    print(f"MAPPING source_episodes={len(records)} target_roles={','.join(target_roles)}", flush=True)
    try:
        mapped, exclusions = adapter_v1.map_episode_records(
            records, target_roles=target_roles
        )
        calibration_inputs = build_calibration_inputs(mapped, candles=candles)
    except TargetCaptureAdapterError as exc:
        return _print_failed(FAILED_REASON_MAPPING, exc)
    exclusion_reason_counts = Counter(exclusion.reason for exclusion in exclusions)
    print(
        f"MAPPED mapped={len(calibration_inputs)} excluded={len(exclusions)}",
        flush=True,
    )
    if signal_state.triggered:
        return _interrupted_exit()

    print(
        f"CALIBRATING inputs={len(calibration_inputs)} "
        f"min_sample_threshold={args.min_sample_threshold}",
        flush=True,
    )
    try:
        report = build_calibration_report(
            calibration_inputs, min_sample_threshold=args.min_sample_threshold
        )
    except TargetCaptureCalibrationError as exc:
        return _print_failed(FAILED_REASON_CALIBRATION, exc)
    print(
        f"CALIBRATED disposition={report['disposition']} "
        f"resolved_sample_count={report['overall']['resolved_sample_count']}",
        flush=True,
    )
    if signal_state.triggered:
        return _interrupted_exit()

    report_text = render_calibration_report_json(report)

    run_id = compute_run_id(
        venue=args.venue,
        symbol=args.symbol,
        timeframe=args.timeframe,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
        episode_stride_candles=args.episode_stride_candles,
        max_episodes=args.max_episodes,
        target_roles=target_roles,
        min_sample_threshold=args.min_sample_threshold,
        source_input_sha256=source_input_sha256,
    )

    output_dir = Path(args.output_dir) / args.venue / args.symbol / cfg.interval_code / run_id
    report_path = output_dir / "report_v1.json"
    manifest_path = output_dir / "manifest_v1.json"

    try:
        selected_buffer = report["selected_buffer_pct_fraction"]
        manifest = build_manifest(
            run_id=run_id,
            venue=args.venue,
            symbol=args.symbol,
            timeframe=args.timeframe,
            from_ts=args.from_ts,
            to_ts=args.to_ts,
            episode_stride_candles=args.episode_stride_candles,
            max_episodes=args.max_episodes,
            target_roles=target_roles,
            min_sample_threshold=args.min_sample_threshold,
            source_input_sha256=source_input_sha256,
            ema_state_prehistory_candle_count=len(prehistory_candles),
            requested_candle_count=len(requested_candles),
            forward_tail_candle_count=len(forward_tail_candles),
            forward_tail_max_candles=cfg.forward_max_candles,
            total_candle_count=len(candles),
            source_episode_count=len(records),
            mapped_target_episode_count=len(calibration_inputs),
            excluded_target_episode_count=len(exclusions),
            exclusion_reason_counts=dict(sorted(exclusion_reason_counts.items())),
            exclusions=[
                {
                    "source_map_id": exclusion.source_map_id,
                    "target_role": exclusion.target_role,
                    "reason": exclusion.reason,
                }
                for exclusion in exclusions
            ],
            report_fingerprint=report["report_fingerprint"],
            disposition=report["disposition"],
            disposition_reason=report["disposition_reason"],
            selected_buffer_pct_fraction=(
                None if selected_buffer is None else format(selected_buffer, "f")
            ),
            chunk_size_candles=args.chunk_size_candles,
        )
        manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"

        print(f"WRITING phase=staging output_dir={output_dir}", flush=True)
        report_sha256, manifest_sha256 = publish_immutable_pair(
            output_dir=output_dir,
            report_text=report_text,
            manifest_text=manifest_text,
        )
        print(f"WRITING phase=published output_dir={output_dir}", flush=True)
    except Exception as exc:
        return _print_failed(FAILED_REASON_OUTPUT_WRITE, exc)

    print(
        f"FINISHED mapped_target_episodes={len(calibration_inputs)} "
        f"excluded_target_episodes={len(exclusions)} "
        f"disposition={report['disposition']} run_id={run_id} "
        f"report_path={report_path} manifest_path={manifest_path} "
        f"report_sha256={report_sha256} manifest_sha256={manifest_sha256}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
