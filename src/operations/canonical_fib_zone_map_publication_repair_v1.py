from __future__ import annotations

"""Operator-invoked, exact-identity repair for one confirmed-invalid
``canonical_fib_zone_map_publication_v1`` cohort.

Boundary: this module does not weaken ``publish``'s fail-closed collision
guard. It is a narrow, separate, operator-invoked recovery path for the one
scenario that guard is not meant to solve: a deterministic recomputation after
a confirmed upstream data defect (e.g. a feat_candle alignment bug fixed after
the original publication was produced), not ordinary nondeterminism. Ordinary
nondeterminism must keep failing closed via ``publish``.

Design:

- exact-scope only: (venue, quote_currency, interval_code, asof_ts_utc,
  map_version) identifies exactly one row; no wildcard, no range, no "latest".
- the caller-supplied ``expected_old_digest`` must exactly match the digest
  currently stored for that identity; any mismatch (including "already
  repaired" or "no such row") fails closed with no mutation.
- the new content must target the same identity as the row being replaced;
  a scope mismatch fails closed with no mutation.
- one transaction: delete the old publication and its child rows, insert the
  new cohort via the same ``insert_publication_cohort`` helper ``publish``
  uses, record one audit row. The caller commits or rolls back.
- this module never opens or authorizes a database connection itself and
  never runs as part of the recurring ``native_short_4h_chain``; the
  read/write identity used to run it is a separate, DBA-authorized credential
  outside the least-privilege INSERT-only grant given to
  ``synth_chain_4h_writer`` (see db/dba/synth_chain_4h_writer_v1.sql).

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.market_data.canonical_fib_zone_map_v1 import (
    MAP_VERSION,
    CanonicalFibMapError,
    PublicationBuild,
    _db_ts,
    _utc,
    insert_publication_cohort,
)


_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class RepairResult:
    status: str
    old_publication_id: str
    old_content_digest: str
    new_publication_id: str
    new_content_digest: str
    row_count: int
    available_count: int


def repair_publication_identity(
    conn: Any,
    *,
    venue: str,
    quote_currency: str,
    interval_code: str,
    asof_ts_utc: datetime,
    expected_old_digest: str,
    new_build: PublicationBuild,
    operator: str,
    reason: str,
) -> RepairResult:
    if not _DIGEST_RE.match(expected_old_digest or ""):
        raise CanonicalFibMapError("expected_old_digest must be a 64-char lowercase hex sha256")
    if not operator or not operator.strip():
        raise CanonicalFibMapError("operator is required for a publication repair")
    if not reason or not reason.strip():
        raise CanonicalFibMapError("reason is required for a publication repair")

    scope_asof = _utc(asof_ts_utc)
    if (
        new_build.venue != venue
        or new_build.quote_currency != quote_currency
        or new_build.interval_code != interval_code
        or _utc(new_build.asof_ts_utc) != scope_asof
    ):
        raise CanonicalFibMapError(
            "new_build identity does not match the exact repair scope; refusing to mutate"
        )
    if new_build.content_digest == expected_old_digest:
        raise CanonicalFibMapError(
            "new_build content_digest equals expected_old_digest; nothing to repair"
        )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT publication_id, content_digest
            FROM canonical_fib_zone_map_publication_v1
            WHERE venue=%s AND quote_currency=%s AND interval_code=%s
              AND asof_ts_utc=%s AND map_version=%s
            FOR UPDATE
            """,
            (venue, quote_currency, interval_code, _db_ts(scope_asof), MAP_VERSION),
        )
        existing = cur.fetchone()
        if existing is None:
            raise CanonicalFibMapError(
                "no existing publication at this exact identity; repair is only for an "
                "existing collision, not first publish"
            )
        old_publication_id = str(existing["publication_id"])
        old_content_digest = str(existing["content_digest"])
        if old_content_digest != expected_old_digest:
            raise CanonicalFibMapError(
                "expected_old_digest does not match the currently stored digest; refusing "
                "to mutate"
            )

        cur.execute(
            "DELETE FROM canonical_fib_zone_map_v1 WHERE publication_id=%s",
            (old_publication_id,),
        )
        cur.execute(
            "DELETE FROM canonical_fib_zone_map_publication_v1 WHERE publication_id=%s",
            (old_publication_id,),
        )

        new_publication_id = f"fibnav-{new_build.content_digest[:32]}"
        insert_publication_cohort(cur, new_build, new_publication_id)

        cur.execute(
            """
            INSERT INTO canonical_fib_zone_map_publication_repair_v1
              (venue, quote_currency, interval_code, asof_ts_utc, map_version,
               old_publication_id, old_content_digest, new_publication_id, new_content_digest,
               operator, reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                venue,
                quote_currency,
                interval_code,
                _db_ts(scope_asof),
                MAP_VERSION,
                old_publication_id,
                old_content_digest,
                new_publication_id,
                new_build.content_digest,
                operator.strip(),
                reason.strip(),
            ),
        )

    return RepairResult(
        status="REPAIRED",
        old_publication_id=old_publication_id,
        old_content_digest=old_content_digest,
        new_publication_id=new_publication_id,
        new_content_digest=new_build.content_digest,
        row_count=len(new_build.rows),
        available_count=new_build.available_count,
    )
