"""Explicit schema compatibility contract for the publication cohort rename.

During the #375 migration window, old-only and new-only schemas are supported.
When both columns exist they must agree for every asset; disagreement fails
closed rather than widening the cohort with an OR predicate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal


LEGACY_COLUMN = "is_portfolio"
CANONICAL_COLUMN = "is_publication_cohort"


class PublicationCohortCompatibilityError(RuntimeError):
    """The asset schema cannot safely identify the publication cohort."""


class PublicationCohortDriftError(PublicationCohortCompatibilityError):
    """Legacy and canonical cohort columns disagree during dual-read."""


@dataclass(frozen=True)
class PublicationCohortContract:
    """Resolved, explicit contract for one asset-table schema state."""

    has_legacy_column: bool
    has_canonical_column: bool
    dual_read_mode: Literal["canonical_verified", "legacy_compatible"] = "canonical_verified"

    @property
    def read_column(self) -> str:
        if self.has_canonical_column and not (
            self.has_legacy_column and self.dual_read_mode == "legacy_compatible"
        ):
            return CANONICAL_COLUMN
        return LEGACY_COLUMN

    @property
    def write_columns(self) -> tuple[str, ...]:
        if self.has_legacy_column and self.has_canonical_column:
            return (LEGACY_COLUMN, CANONICAL_COLUMN)
        return (self.read_column,)

    def predicate(self, table_alias: str) -> str:
        return f"COALESCE({table_alias}.{self.read_column}, 0) = 1"


def contract_from_column_names(
    column_names: Iterable[str],
    *,
    dual_read_mode: Literal["canonical_verified", "legacy_compatible"] = "canonical_verified",
) -> PublicationCohortContract:
    names = {str(name) for name in column_names}
    contract = PublicationCohortContract(
        has_legacy_column=LEGACY_COLUMN in names,
        has_canonical_column=CANONICAL_COLUMN in names,
        dual_read_mode=dual_read_mode,
    )
    if not (contract.has_legacy_column or contract.has_canonical_column):
        raise PublicationCohortCompatibilityError(
            "asset schema has neither is_portfolio nor is_publication_cohort"
        )
    return contract


def fetch_publication_cohort_contract(
    conn: Any,
    *,
    dual_read_mode: Literal["canonical_verified", "legacy_compatible"] = "canonical_verified",
) -> PublicationCohortContract:
    sql = """
    SELECT COLUMN_NAME
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'asset'
      AND COLUMN_NAME IN ('is_portfolio', 'is_publication_cohort')
    ORDER BY COLUMN_NAME
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = list(cur.fetchall())
    contract = contract_from_column_names(
        (row["COLUMN_NAME"] for row in rows), dual_read_mode=dual_read_mode
    )
    if (
        contract.has_legacy_column
        and contract.has_canonical_column
        and contract.dual_read_mode == "canonical_verified"
    ):
        _assert_dual_read_no_drift(conn)
    return contract


def _assert_dual_read_no_drift(conn: Any) -> None:
    sql = """
    SELECT asset_id, symbol, is_portfolio, is_publication_cohort
    FROM asset
    WHERE COALESCE(is_portfolio, 0) <> COALESCE(is_publication_cohort, 0)
    ORDER BY asset_id
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
    if row:
        raise PublicationCohortDriftError(
            "publication cohort dual-read drift for "
            f"asset_id={row['asset_id']} symbol={row['symbol']}: "
            f"is_portfolio={row['is_portfolio']} "
            f"is_publication_cohort={row['is_publication_cohort']}"
        )
