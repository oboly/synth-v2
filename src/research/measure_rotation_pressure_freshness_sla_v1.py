from __future__ import annotations

"""#547 Phase B — Rotation Pressure freshness SLA measurement harness.

Measurement/observability only. Read-only: no DB writes, no Rotation
formula changes, no #593 changes, no runtime/timer changes. Collects real
production timing evidence for the canonical hourly chain

    source candle close (obs_market_candle, 1h)
    -> market_rotation_history_v1 availability (24h + 168h source snapshots)
    -> Rotation Pressure writer scheduled/start/end (gurkDB, local journal)
    -> market_rotation_pressure_snapshot_v1 commit/queryable (earliest
       post-commit writer FINISHED marker per asof, not raw DB created_at
       -- see earliest_finish_per_asof())
    -> publisher start/end (Odroid; optional, from an externally supplied
       journal export -- this host has no network path to Odroid)
    -> operator-visible publication (optional, same as above)

so a producer-owned ROTATION_STALE_AFTER can eventually be derived from an
OBSERVED distribution rather than a three-cycle anecdote. See
docs/architecture/rotation_pressure_v1_canonical_promotion_v1.md §4 for the
exact BLOCKED_NEEDS_MEASUREMENT contract this harness fulfils, and
docs/research/market_rotation_pressure_freshness_sla_measurement_v1.md for
the resulting report.

This module strictly distinguishes:
  CONFIGURED  -- a systemd OnCalendar/RandomizedDelaySec schedule fact
  OBSERVED    -- an actual measured value from DB/journal evidence
  OWNER-CHOSEN -- a safety margin / threshold decision (explicitly NOT made
                  by this module; it only reports candidate SLA inputs)
"""

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from src.common.db import db_cursor

RUNNER_NAME = "measure_rotation_pressure_freshness_sla_v1"

WRITER_SERVICE = "synth-market-rotation-pressure-writer.service"
PUBLISHER_SERVICE = "synth-market-rotation-pressure-publisher.service"
CANDLE_FRESHNESS_SERVICE = "synth-market-candle-freshness-writer.service"

# CONFIGURED schedule facts, verified against the deployed unit files
# (deploy/systemd/synth-market-rotation-pressure-writer.timer,
# docs/ops/systemd/synth-market-rotation-pressure-publisher.timer). Not
# guessed, not re-derived here -- reproduced only for lag-vs-schedule math.
WRITER_ONCALENDAR_MINUTE = 20
WRITER_RANDOMIZED_DELAY_SEC = 180
PUBLISHER_ONCALENDAR_MINUTE = 35
PUBLISHER_RANDOMIZED_DELAY_SEC = 180

STARTED_RE = re.compile(
    r"STARTED runner=run_market_rotation_pressure_once .*?ts=(?P<ts>\S+)"
)
FINISHED_RE = re.compile(
    r"FINISHED runner=run_market_rotation_pressure_once exit_status=(?P<code>\d+) "
    r"elapsed_sec=(?P<elapsed>\d+) ts=(?P<ts>\S+)"
)
ASOF_RE = re.compile(r"MARKET ROTATION as_of=(?P<asof>\S+)")

PUBLISHER_OUTER_RUNNER = "run_market_rotation_pressure_dashboard_render_once"

PUB_LINE_RE = re.compile(
    r"^(?P<jts>\S+) \S+ \S+\[(?P<pid>\d+)\]: (?P<msg>.*)$"
)
PUB_BOOT_RE = re.compile(r"^-- Boot ")
PUB_OUTER_STARTED_RE = re.compile(
    r"^STARTED runner=" + re.escape(PUBLISHER_OUTER_RUNNER) + r" .*?ts=(?P<ts>\S+)"
)
PUB_OUTER_FINISHED_RE = re.compile(
    r"^FINISHED runner=" + re.escape(PUBLISHER_OUTER_RUNNER)
    + r" exit_status=(?P<code>\d+) elapsed_sec=(?P<elapsed>\d+) ts=(?P<ts>\S+)"
)
PUB_PUBLISHED_RE = re.compile(r"^PUBLISHED html=\S+")
PUB_TRACEBACK_RE = re.compile(r"Traceback \(most recent call last\)")
PUB_NETWORK_UNREACHABLE_RE = re.compile(r"OSError: \[Errno 101\] Network is unreachable")
PUB_DB_OPERR_RE = re.compile(r"pymysql\.err\.OperationalError")


def _parse_ts(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    if value.upper().endswith(" UTC"):
        value = value[: -len(" UTC")] + "+00:00"
    if "T" not in value:
        value = value.replace(" ", "T", 1)
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass
class WriterCycle:
    asof: datetime | None = None
    start_ts: datetime | None = None
    finish_ts: datetime | None = None
    elapsed_sec: int | None = None
    exit_status: int | None = None


@dataclass
class PublisherCycle:
    outer_pid: str = ""
    start_ts: datetime | None = None
    finish_ts: datetime | None = None
    published_ts: datetime | None = None
    elapsed_sec: int | None = None
    exit_status: int | None = None
    failed: bool = False
    error_reason: str | None = None


def collect_writer_cycles_from_journal(since: str) -> list[WriterCycle]:
    """Parse local gurkdb journalctl output for the writer service.

    Runs journalctl directly (this harness executes ON gurkdb) -- read-only,
    no DB writes, no host mutation.
    """
    proc = subprocess.run(
        [
            "journalctl",
            "-u",
            WRITER_SERVICE,
            "--no-pager",
            "-o",
            "short-iso",
            "--since",
            since,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    cycles: list[WriterCycle] = []
    current: WriterCycle | None = None
    for line in proc.stdout.splitlines():
        m = STARTED_RE.search(line)
        if m:
            current = WriterCycle(start_ts=_parse_ts(m.group("ts")))
            continue
        if current is None:
            continue
        m = ASOF_RE.search(line)
        if m:
            current.asof = _parse_ts(m.group("asof"))
            continue
        m = FINISHED_RE.search(line)
        if m:
            current.finish_ts = _parse_ts(m.group("ts"))
            current.elapsed_sec = int(m.group("elapsed"))
            current.exit_status = int(m.group("code"))
            cycles.append(current)
            current = None
    return cycles


def parse_publisher_journal_export(
    text: str,
) -> tuple[list[PublisherCycle], list[PublisherCycle], list[str]]:
    """Parse an externally supplied publisher journal export (Odroid).

    This harness has no network path to Odroid; the caller pastes the
    output of the documented read-only journalctl command and this function
    parses it deterministically, keyed by the OUTER
    `run_market_rotation_pressure_dashboard_render_once` wrapper's own PID
    (distinct from the inner `run_market_rotation_pressure_dashboard_v1`
    subprocess PID that a DB-connection traceback is logged under).

    Returns (successful_cycles, failed_cycles, boot_marker_journal_ts_list).
    A cycle is "failed" if its outer STARTED is followed by a Traceback/
    OSError/pymysql error and/or is never followed by a matching outer
    FINISHED before the next outer STARTED, a `-- Boot ... --` journal
    boundary, or end of input. `PUBLISHED status=`/`freshness=` values are
    parsed only as informational context (reporting-owned legacy
    classification) and are never used to compute SLA lag.
    """
    successes: list[PublisherCycle] = []
    failures: list[PublisherCycle] = []
    boot_markers: list[str] = []
    pending: PublisherCycle | None = None

    def flush(reason: str | None) -> None:
        nonlocal pending
        if pending is None:
            return
        if pending.finish_ts is not None and not pending.failed and pending.exit_status == 0:
            successes.append(pending)
        else:
            if pending.error_reason is None:
                pending.error_reason = reason
            failures.append(pending)
        pending = None

    for line in text.splitlines():
        if PUB_BOOT_RE.match(line):
            flush("INTERRUPTED_BY_REBOOT")
            boot_markers.append(line)
            continue

        m = PUB_LINE_RE.match(line)
        if not m:
            continue
        jts = _parse_ts(m.group("jts"))
        pid = m.group("pid")
        msg = m.group("msg")

        sm = PUB_OUTER_STARTED_RE.match(msg)
        if sm:
            flush("NO_FINISHED_BEFORE_NEXT_START")
            pending = PublisherCycle(outer_pid=pid, start_ts=_parse_ts(sm.group("ts")))
            continue

        if pending is None:
            continue

        fm = PUB_OUTER_FINISHED_RE.match(msg)
        if fm and pid == pending.outer_pid:
            pending.finish_ts = _parse_ts(fm.group("ts"))
            pending.elapsed_sec = int(fm.group("elapsed"))
            pending.exit_status = int(fm.group("code"))
            flush(None)
            continue

        if PUB_PUBLISHED_RE.match(msg):
            pending.published_ts = jts
            continue
        if PUB_TRACEBACK_RE.search(msg):
            pending.failed = True
            pending.error_reason = pending.error_reason or "TRACEBACK"
            continue
        if PUB_NETWORK_UNREACHABLE_RE.search(msg):
            pending.failed = True
            pending.error_reason = "NETWORK_UNREACHABLE"
            continue
        if PUB_DB_OPERR_RE.search(msg):
            pending.failed = True
            pending.error_reason = pending.error_reason or "DB_OPERATIONAL_ERROR"
            continue

    flush("TRUNCATED_AT_END_OF_LOG")
    return successes, failures, boot_markers


CANDLE_PHASE_FINISHED_RE = re.compile(
    r"PHASE_FINISHED runner=run_market_candle_freshness_once interval=1h ts=(?P<ts>\S+)"
)


def collect_candle_freshness_1h_completions(since: str) -> list[datetime]:
    """Timestamps at which each rolling candle-freshness cycle's 1h-interval
    phase finished (i.e. the closed-1h-candle universe was last refreshed).

    NOTE: this deliberately does NOT use MAX(obs_market_candle.ingest_ts_utc)
    grouped by close_ts_utc -- that DB aggregate is contaminated by later
    asset-onboarding backfills that insert historical rows for newly tracked
    symbols long after the original hour (observed: 293/418 hours in the
    initial sample showed a multi-hour-to-multi-day MAX(ingest_ts_utc) tail
    from this cause, not a real completion delay). The candle-freshness
    writer's own per-cycle PHASE_FINISHED marker is the actual, unambiguous
    "this rolling refresh of the closed-1h universe is done" event and is
    read-only, in-app, deterministic evidence.
    """
    proc = subprocess.run(
        [
            "journalctl",
            "-u",
            CANDLE_FRESHNESS_SERVICE,
            "--no-pager",
            "-o",
            "short-iso",
            "--since",
            since,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    completions: list[datetime] = []
    for line in proc.stdout.splitlines():
        m = CANDLE_PHASE_FINISHED_RE.search(line)
        if m:
            completions.append(_parse_ts(m.group("ts")))
    completions.sort()
    return completions


def source_completion_for_asof(asof: datetime, completions: list[datetime]) -> datetime | None:
    """First candle-freshness 1h-phase completion at or after ``asof`` --
    the first rolling refresh cycle that could possibly have observed the
    just-closed candle.
    """
    for ts in completions:
        if ts >= asof:
            return ts
    return None


def collect_persist_events(since_utc: datetime) -> dict[datetime, datetime]:
    """as_of_ts_utc -> DB `created_at` for market_rotation_pressure_snapshot_v1.

    NOT the commit/queryable timestamp: `created_at` is a DATETIME(6)
    DEFAULT CURRENT_TIMESTAMP(6) column stamped by the header row's own
    `INSERT IGNORE` in `write_pressure_snapshot()`
    (src/research/run_market_rotation_pressure_v1.py), which runs BEFORE
    the ~150-190 per-asset observation-row inserts, the header `UPDATE`,
    and the caller's `conn.commit()`
    (src/research/run_market_rotation_pressure_v1.py `main()`). It is kept
    here only as an insert-order diagnostic (`header_insert_at_utc` in the
    report); `asof_to_persist_lag` is computed from `earliest_finish_per_asof`
    below instead, which is provably post-commit.
    """
    with db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT as_of_ts_utc, created_at
            FROM market_rotation_pressure_snapshot_v1
            WHERE as_of_ts_utc >= %s
            ORDER BY as_of_ts_utc
            """,
            (since_utc.replace(tzinfo=None),),
        )
        rows = cur.fetchall()
    out: dict[datetime, datetime] = {}
    for row in rows:
        asof = row["as_of_ts_utc"].replace(tzinfo=UTC)
        created = row["created_at"].replace(tzinfo=UTC)
        out[asof] = created
    return out


def earliest_finish_per_asof(
    by_asof: dict[datetime, list["WriterCycle"]],
) -> dict[datetime, datetime]:
    """The authoritative, provably post-commit "queryable" timestamp per asof.

    `write_pressure_snapshot()` always executes its full INSERT/UPDATE path
    (idempotently, via `INSERT IGNORE`) even on a NOOP_ALREADY_COMPLETE
    rerun, and the caller commits before the runner's own FINISHED marker is
    emitted (`conn.commit()` precedes `print_report()` precedes process
    exit precedes the shell wrapper's `FINISHED ... ts=` log line). So for
    any writer invocation that reached this asof, that invocation's
    `finish_ts` is a valid upper bound on when the row became committed and
    queryable. Taking the MINIMUM `finish_ts` across all invocations for an
    asof (not just the "regular" OnCalendar-window one) correctly picks up
    an earlier off-schedule/manual/catch-up invocation when one actually
    persisted the data first.
    """
    return {
        asof: min(c.finish_ts for c in cycles if c.finish_ts is not None)
        for asof, cycles in by_asof.items()
        if any(c.finish_ts is not None for c in cycles)
    }


def _pctile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    values = sorted(values)
    k = (len(values) - 1) * p
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def summarize(label: str, values: list[float]) -> dict[str, object]:
    if not values:
        return {"label": label, "count": 0}
    return {
        "label": label,
        "count": len(values),
        "min_sec": round(min(values), 1),
        "p50_sec": round(_pctile(values, 0.50), 1),
        "p90_sec": round(_pctile(values, 0.90), 1),
        "p95_sec": round(_pctile(values, 0.95), 1),
        "p99_sec": round(_pctile(values, 0.99), 1),
        "max_sec": round(max(values), 1),
        "mean_sec": round(statistics.fmean(values), 1),
    }


PUBLISHER_GAP_THRESHOLD_HOURS = 2.0


def max_publisher_attempt_gap_hours(
    successes: list[PublisherCycle], failures: list[PublisherCycle]
) -> float:
    """Largest gap between consecutive publisher attempts (success or
    failure), in hours. An unobserved gap this large inside the journal's
    nominal [coverage_start, coverage_end] span means the journal itself is
    missing entries there (e.g. journal rotation truncation), not that the
    publisher was merely retrying during a real outage -- during the
    observed 2026-09-01 outage, failed attempts were still logged roughly
    every 15-30 minutes. Returns 0.0 for fewer than two attempts.
    """
    ts = sorted(
        [c.start_ts for c in successes if c.start_ts is not None]
        + [c.start_ts for c in failures if c.start_ts is not None]
    )
    if len(ts) < 2:
        return 0.0
    return max((b - a).total_seconds() for a, b in zip(ts, ts[1:])) / 3600


def evaluate_publisher_sufficiency(
    *,
    publisher_journal_supplied: bool,
    coverage_start: datetime | None,
    coverage_end: datetime | None,
    earliest_writer_asof: datetime | None,
    latest_writer_asof: datetime | None,
    max_gap_hours: float,
    gap_threshold_hours: float = PUBLISHER_GAP_THRESHOLD_HOURS,
) -> tuple[str, float | None]:
    """Publisher-leg sufficiency verdict against the #547 task contract:
    the journal must cover the FULL writer sample span (start through end,
    not just start) with no unobserved gap, or extrapolation is forbidden
    and MEASUREMENT_INSUFFICIENT must be returned with the exact shortfall.

    Returns (status, shortfall_hours_or_none).
    """
    if not publisher_journal_supplied:
        return "NOT_ATTEMPTED_NO_PUBLISHER_JOURNAL", None
    if coverage_start is None:
        return "MEASUREMENT_INSUFFICIENT_EMPTY_JOURNAL", None
    if earliest_writer_asof is not None and coverage_start > earliest_writer_asof:
        missing = round((coverage_start - earliest_writer_asof).total_seconds() / 3600, 1)
        return "MEASUREMENT_INSUFFICIENT_PARTIAL_COVERAGE", missing
    if (
        latest_writer_asof is not None
        and coverage_end is not None
        and coverage_end < latest_writer_asof
    ):
        missing = round((latest_writer_asof - coverage_end).total_seconds() / 3600, 1)
        return "MEASUREMENT_INSUFFICIENT_PARTIAL_COVERAGE", missing
    if max_gap_hours > gap_threshold_hours:
        return "MEASUREMENT_INSUFFICIENT_UNOBSERVED_GAP", round(max_gap_hours, 1)
    return "MEASUREMENT_SUFFICIENT_FOR_OWNER_DECISION", None


def build_report(
    since: str,
    publisher_journal_path: str | None,
) -> dict[str, object]:
    since_utc = _parse_ts(since)

    print(
        f"STARTED runner={RUNNER_NAME} mode=measurement_only scope=rotation_pressure_freshness "
        f"since={since}",
        flush=True,
    )
    t0 = time.monotonic()

    writer_cycles = collect_writer_cycles_from_journal(since)
    print(
        f"PHASE_FINISHED phase=writer_journal_collect rows={len(writer_cycles)} "
        f"elapsed_sec={time.monotonic() - t0:.1f}",
        flush=True,
    )

    t1 = time.monotonic()
    candle_completions = collect_candle_freshness_1h_completions(since)
    print(
        f"PHASE_FINISHED phase=source_completion_journal_collect rows={len(candle_completions)} "
        f"elapsed_sec={time.monotonic() - t1:.1f}",
        flush=True,
    )

    t2 = time.monotonic()
    persist_events = collect_persist_events(since_utc)
    print(
        f"PHASE_FINISHED phase=persist_query rows={len(persist_events)} "
        f"elapsed_sec={time.monotonic() - t2:.1f}",
        flush=True,
    )

    publisher_successes: list[PublisherCycle] = []
    publisher_failures: list[PublisherCycle] = []
    publisher_boot_markers: list[str] = []
    if publisher_journal_path:
        text = Path(publisher_journal_path).read_text()
        publisher_successes, publisher_failures, publisher_boot_markers = (
            parse_publisher_journal_export(text)
        )
        print(
            f"PHASE_FINISHED phase=publisher_journal_parse "
            f"success_rows={len(publisher_successes)} failed_rows={len(publisher_failures)} "
            f"reboot_boundaries={len(publisher_boot_markers)}",
            flush=True,
        )
    else:
        print(
            "PHASE_SKIPPED phase=publisher_journal_parse reason=no_odroid_network_path "
            "(--publisher-journal not supplied)",
            flush=True,
        )

    source_completion_lag: list[float] = []
    writer_scheduling_lag: list[float] = []
    writer_runtime: list[float] = []
    asof_to_persist_lag: list[float] = []
    asof_to_persist_lag_steady_state: list[float] = []

    # Publisher-leg metrics, split into cohorts per the #547 Phase B task
    # contract: steady-state (normal `:35:00`-window cycles) must not be
    # blended with outage/recovery cycles (post-reboot, off-cadence starts).
    persist_to_pub_start_steady: list[float] = []
    persist_to_published_steady: list[float] = []
    publisher_runtime_steady: list[float] = []
    total_lag_steady: list[float] = []

    persist_to_pub_start_recovery: list[float] = []
    persist_to_published_recovery: list[float] = []
    publisher_runtime_recovery: list[float] = []
    total_lag_recovery: list[float] = []

    matched_success_count = 0
    unmatched_asof_count = 0

    publisher_coverage_start: datetime | None = None
    publisher_coverage_end: datetime | None = None
    all_pub_ts = [c.start_ts for c in publisher_successes if c.start_ts is not None]
    all_pub_ts += [c.start_ts for c in publisher_failures if c.start_ts is not None]
    if all_pub_ts:
        publisher_coverage_start = min(all_pub_ts)
        publisher_coverage_end = max(all_pub_ts)

    samples: list[dict[str, object]] = []

    # Multiple writer invocations can share one asof hour (manual/catch-up
    # re-runs alongside the regular OnCalendar-triggered cycle; NOOP reruns
    # do not change committed_at). For writer_scheduling_lag/writer_runtime
    # -- properties of ONE specific invocation -- keep only the invocation
    # whose start falls inside the configured worst-case window
    # [OnCalendar, OnCalendar + RandomizedDelaySec] + a small dispatch-jitter
    # margin; that is the regular, timer-triggered cycle this SLA concerns.
    # asof_to_persist_lag is invocation-independent (it is the DB commit
    # time for that asof, whichever invocation actually wrote it), so it is
    # deduplicated by asof instead, once, below.
    regular_window_margin_sec = 60
    off_schedule_cycle_count = 0
    by_asof: dict[datetime, list[WriterCycle]] = {}
    for cycle in writer_cycles:
        if cycle.asof is None or cycle.start_ts is None or cycle.finish_ts is None:
            continue
        by_asof.setdefault(cycle.asof, []).append(cycle)

    # Authoritative, provably post-commit persist timestamp per asof -- see
    # earliest_finish_per_asof() docstring. Supersedes raw DB `created_at`
    # (kept only as a diagnostic field, `header_insert_at_utc`, since it is
    # stamped at header-row INSERT time, before the observation-row inserts
    # and conn.commit()).
    committed_events = earliest_finish_per_asof(by_asof)

    # Pre-match each persisted asof to at most one successful publisher
    # cycle, and each publisher cycle to at most one asof. A publish call
    # always serves whatever row is currently latest in the DB, so if two
    # hours were persisted before the next publish fired (e.g. during the
    # 2026-09-01 outage), that one publish reflects only the LATER hour --
    # the earlier hour was genuinely never independently published. Process
    # asofs in descending committed_at order so the later hour claims the
    # earliest eligible publish first; this prevents an earlier hour from
    # wrongly "claiming" a publish that actually served a later hour's data
    # (which briefly produced a negative persist->publish lag before this
    # fix).
    matched_pub_for_asof: dict[datetime, PublisherCycle] = {}
    if publisher_successes:
        claimed_pub_ids: set[int] = set()
        asofs_by_committed_at_desc = sorted(
            (a for a in by_asof if a in committed_events),
            key=lambda a: committed_events[a],
            reverse=True,
        )
        for asof in asofs_by_committed_at_desc:
            committed_at = committed_events[asof]
            candidates = [
                p
                for p in publisher_successes
                if id(p) not in claimed_pub_ids
                and p.start_ts is not None
                and p.finish_ts is not None
                and p.published_ts is not None
                and 0 <= (p.start_ts - committed_at).total_seconds() <= 90 * 60
            ]
            if candidates:
                pub = min(candidates, key=lambda p: p.start_ts)
                claimed_pub_ids.add(id(pub))
                matched_pub_for_asof[asof] = pub

    for asof in sorted(by_asof):
        cycles_for_asof = by_asof[asof]
        scheduled_start = asof.replace(minute=WRITER_ONCALENDAR_MINUTE, second=0, microsecond=0)
        window_end = scheduled_start.timestamp() + WRITER_RANDOMIZED_DELAY_SEC + regular_window_margin_sec
        regular = [
            c
            for c in cycles_for_asof
            if scheduled_start.timestamp() <= c.start_ts.timestamp() <= window_end
        ]
        off_schedule_cycle_count += len(cycles_for_asof) - len(regular)
        cycle = min(regular, key=lambda c: c.start_ts) if regular else None

        record: dict[str, object] = {"asof_ts_utc": asof.isoformat()}

        sc = source_completion_for_asof(asof, candle_completions)
        if sc is not None:
            lag = (sc - asof).total_seconds()
            source_completion_lag.append(lag)
            record["source_completion_lag_sec"] = round(lag, 1)

        if cycle is None:
            record["writer_cycle_status"] = "NO_REGULAR_TIMER_CYCLE_OBSERVED"
            samples.append(record)
            continue
        sched_lag = (cycle.start_ts - scheduled_start).total_seconds()
        writer_scheduling_lag.append(sched_lag)
        record["writer_scheduling_lag_sec"] = round(sched_lag, 1)

        runtime = (cycle.finish_ts - cycle.start_ts).total_seconds()
        writer_runtime.append(runtime)
        record["writer_runtime_sec"] = round(runtime, 1)

        header_insert_at = persist_events.get(asof)
        if header_insert_at is not None:
            record["header_insert_at_utc"] = header_insert_at.isoformat()

        committed_at = committed_events.get(asof)
        if committed_at is not None:
            persist_lag = (committed_at - asof).total_seconds()
            asof_to_persist_lag.append(persist_lag)
            record["asof_to_persist_lag_sec"] = round(persist_lag, 1)
            record["committed_at_utc"] = committed_at.isoformat()
            if committed_at < cycle.start_ts:
                # This asof was already committed before the regular
                # OnCalendar-window cycle even started -- an earlier
                # off-schedule/manual/catch-up invocation must have written
                # it (the regular cycle then observed NOOP_ALREADY_COMPLETE).
                # Excluded from the steady-state summary below.
                record["persisted_by_off_schedule_invocation"] = True
            else:
                asof_to_persist_lag_steady_state.append(persist_lag)

            # Use the pre-matched (claimed, one-to-one) publisher cycle for
            # this asof, if any -- see the descending-committed_at matching
            # pass above. Failed publisher cycles are never matched here --
            # they cannot contribute a latency observation (no PUBLISHED
            # event exists).
            if publisher_successes:
                pub = matched_pub_for_asof.get(asof)
                if pub is not None:
                    matched_success_count += 1

                    pub_start_lag = (pub.start_ts - committed_at).total_seconds()
                    pub_published_lag = (pub.published_ts - committed_at).total_seconds()
                    pub_runtime = (pub.finish_ts - pub.start_ts).total_seconds()
                    total = (pub.published_ts - asof).total_seconds()

                    pub_scheduled_start = asof.replace(
                        minute=PUBLISHER_ONCALENDAR_MINUTE, second=0, microsecond=0
                    )
                    pub_sched_lag = (pub.start_ts - pub_scheduled_start).total_seconds()
                    is_steady_state = (
                        0 <= pub_sched_lag <= PUBLISHER_RANDOMIZED_DELAY_SEC + regular_window_margin_sec
                    )

                    record["publisher_start_utc"] = pub.start_ts.isoformat()
                    record["published_at_utc"] = pub.published_ts.isoformat()
                    record["persist_to_publisher_start_lag_sec"] = round(pub_start_lag, 1)
                    record["persist_to_published_lag_sec"] = round(pub_published_lag, 1)
                    record["publisher_runtime_sec"] = round(pub_runtime, 1)
                    record["total_asof_to_published_lag_sec"] = round(total, 1)
                    record["publisher_cohort"] = "steady_state" if is_steady_state else "recovery"

                    if is_steady_state:
                        persist_to_pub_start_steady.append(pub_start_lag)
                        persist_to_published_steady.append(pub_published_lag)
                        publisher_runtime_steady.append(pub_runtime)
                        total_lag_steady.append(total)
                    else:
                        persist_to_pub_start_recovery.append(pub_start_lag)
                        persist_to_published_recovery.append(pub_published_lag)
                        publisher_runtime_recovery.append(pub_runtime)
                        total_lag_recovery.append(total)
                elif (
                    publisher_coverage_start is not None
                    and publisher_coverage_start <= asof <= publisher_coverage_end
                ):
                    unmatched_asof_count += 1
                    record["publisher_match_status"] = "NO_SUCCESSFUL_PUBLISHER_CYCLE_IN_WINDOW"
                elif publisher_journal_path:
                    record["publisher_match_status"] = "ASOF_OUTSIDE_PUBLISHER_JOURNAL_COVERAGE"

        samples.append(record)

    total_writer_asofs_with_persist = len(asof_to_persist_lag)
    earliest_writer_asof = min(by_asof) if by_asof else None
    latest_writer_asof = max(by_asof) if by_asof else None

    max_gap_hours = max_publisher_attempt_gap_hours(publisher_successes, publisher_failures)
    publisher_leg_sufficiency, missing_publisher_history_hours = evaluate_publisher_sufficiency(
        publisher_journal_supplied=bool(publisher_journal_path),
        coverage_start=publisher_coverage_start,
        coverage_end=publisher_coverage_end,
        earliest_writer_asof=earliest_writer_asof,
        latest_writer_asof=latest_writer_asof,
        max_gap_hours=max_gap_hours,
    )

    report = {
        "runner": RUNNER_NAME,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "observation_window_since_utc": since_utc.isoformat(),
        "sample_count": len(samples),
        "off_schedule_writer_invocation_count": off_schedule_cycle_count,
        "configured_schedule_facts": {
            "writer_oncalendar_utc": f"*:{WRITER_ONCALENDAR_MINUTE:02d}:00",
            "writer_randomized_delay_sec": WRITER_RANDOMIZED_DELAY_SEC,
            "publisher_oncalendar_utc": f"*:{PUBLISHER_ONCALENDAR_MINUTE:02d}:00",
            "publisher_randomized_delay_sec": PUBLISHER_RANDOMIZED_DELAY_SEC,
        },
        "observed_metrics": {
            "source_completion_lag": summarize("source_completion_lag", source_completion_lag),
            "writer_scheduling_lag": summarize("writer_scheduling_lag", writer_scheduling_lag),
            "writer_runtime": summarize("writer_runtime", writer_runtime),
            "asof_to_persist_lag": summarize("asof_to_persist_lag", asof_to_persist_lag),
            "asof_to_persist_lag_steady_state": summarize(
                "asof_to_persist_lag_steady_state", asof_to_persist_lag_steady_state
            ),
            "persist_to_publisher_start_lag_steady_state": summarize(
                "persist_to_publisher_start_lag_steady_state", persist_to_pub_start_steady
            ),
            "persist_to_published_lag_steady_state": summarize(
                "persist_to_published_lag_steady_state", persist_to_published_steady
            ),
            "publisher_runtime_steady_state": summarize(
                "publisher_runtime_steady_state", publisher_runtime_steady
            ),
            "total_asof_to_published_lag_steady_state": summarize(
                "total_asof_to_published_lag_steady_state", total_lag_steady
            ),
            "persist_to_publisher_start_lag_recovery": summarize(
                "persist_to_publisher_start_lag_recovery", persist_to_pub_start_recovery
            ),
            "persist_to_published_lag_recovery": summarize(
                "persist_to_published_lag_recovery", persist_to_published_recovery
            ),
            "publisher_runtime_recovery": summarize(
                "publisher_runtime_recovery", publisher_runtime_recovery
            ),
            "total_asof_to_published_lag_recovery": summarize(
                "total_asof_to_published_lag_recovery", total_lag_recovery
            ),
        },
        "publisher_leg_status": (
            "OBSERVED" if publisher_successes or publisher_failures
            else "NOT_OBSERVED_NO_ODROID_ACCESS"
        ),
        "publisher_leg_sufficiency": publisher_leg_sufficiency,
        "publisher_join_summary": {
            "total_writer_asofs_with_persist": total_writer_asofs_with_persist,
            "matched_successful_publisher_cycles": matched_success_count,
            "unmatched_asofs_within_publisher_coverage": unmatched_asof_count,
            "publisher_failed_cycle_count": len(publisher_failures),
            "publisher_failed_cycle_reasons": sorted(
                {c.error_reason for c in publisher_failures if c.error_reason}
            ),
            "publisher_reboot_boundary_count": len(publisher_boot_markers),
            "publisher_journal_coverage_start_utc": (
                publisher_coverage_start.isoformat() if publisher_coverage_start else None
            ),
            "publisher_journal_coverage_end_utc": (
                publisher_coverage_end.isoformat() if publisher_coverage_end else None
            ),
            "writer_sample_earliest_asof_utc": (
                earliest_writer_asof.isoformat() if earliest_writer_asof else None
            ),
            "writer_sample_latest_asof_utc": (
                latest_writer_asof.isoformat() if latest_writer_asof else None
            ),
            "missing_publisher_history_hours_needed": missing_publisher_history_hours,
            "max_publisher_attempt_gap_hours": round(max_gap_hours, 1),
        },
        "publisher_failed_cycles": [
            {
                "outer_pid": c.outer_pid,
                "start_ts_utc": c.start_ts.isoformat() if c.start_ts else None,
                "error_reason": c.error_reason,
            }
            for c in publisher_failures
        ],
        "samples": samples,
    }

    print(
        f"FINISHED runner={RUNNER_NAME} exit_status=0 "
        f"sample_count={len(samples)} "
        f"publisher_leg_sufficiency={publisher_leg_sufficiency} "
        f"elapsed_sec={time.monotonic() - t0:.1f}",
        flush=True,
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        default="2026-08-08 12:00:00 UTC",
        help="journalctl/DB lower bound (UTC), default: gurkDB production activation",
    )
    parser.add_argument(
        "--publisher-journal",
        default=None,
        help="path to a pasted read-only odroid journalctl export for the publisher service",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="write the JSON report to this path in addition to stdout",
    )
    args = parser.parse_args()

    report = build_report(args.since, args.publisher_journal)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2, default=str))
        print(f"WROTE {args.out}", flush=True)
    else:
        print(json.dumps(report, indent=2, default=str))

    return 0


if __name__ == "__main__":
    sys.exit(main())
