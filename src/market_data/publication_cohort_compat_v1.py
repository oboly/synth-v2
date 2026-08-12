"""Explicit compatibility contract for ``asset`` publication-cohort columns.

During #375's sequenced migration, deployments may expose only the legacy
``is_portfolio`` column or both it and canonical ``is_publication_cohort``.
When both exist they must agree exactly; disagreement is a fail-closed schema
drift error, never an implicit OR of the two cohorts.
"""
from __future__ import annotations

from typing import Any, Iterable

LEGACY_COLUMN = "is_portfolio"
CANONICAL_COLUMN = "is_publication_cohort"


class PublicationCohortCompatibilityError(RuntimeError):
    """The schema cannot safely identify one publication cohort."""


def asset_publication_cohort_columns(conn: Any) -> frozenset[str]:
    sql = """
    SELECT COLUMN_NAME
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'asset'
      AND COLUMN_NAME IN ('is_portfolio', 'is_publication_cohort')
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        return frozenset(str(row["COLUMN_NAME"]) for row in cur.fetchall())


def publication_cohort_column(columns: Iterable[str]) -> str:
    available = frozenset(columns)
    if CANONICAL_COLUMN in available:
        return CANONICAL_COLUMN
    if LEGACY_COLUMN in available:
        return LEGACY_COLUMN
    raise PublicationCohortCompatibilityError(
        "asset has neither is_portfolio nor is_publication_cohort; publication cohort is unavailable"
    )


def assert_no_publication_cohort_drift(conn: Any, columns: Iterable[str] | None = None) -> str:
    available = frozenset(columns) if columns is not None else asset_publication_cohort_columns(conn)
    selected = publication_cohort_column(available)
    if {LEGACY_COLUMN, CANONICAL_COLUMN}.issubset(available):
        sql = """
        SELECT asset_id, symbol, is_portfolio, is_publication_cohort
        FROM asset
        WHERE NOT (is_portfolio <=> is_publication_cohort)
        ORDER BY asset_id
        LIMIT 1
        """
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
        if row is not None:
            raise PublicationCohortCompatibilityError(
                "asset publication-cohort drift: is_portfolio and "
                f"is_publication_cohort disagree for asset_id={row['asset_id']} symbol={row['symbol']}"
            )
    return selected
