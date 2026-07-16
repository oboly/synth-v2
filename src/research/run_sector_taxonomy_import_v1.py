from __future__ import annotations

"""Validate and reconcile the versioned Sector Taxonomy v1 seed.

Boundary: research/data metadata only. This module does not import selection,
decision, planning, execution, reporting, or broker code.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from src.common.db import get_connection


SCHEMA_VERSION = "sector_taxonomy_seed_v1"
MIGRATION_PATH = "db/migrations/20260716_sector_taxonomy_database_seed_v1.sql"
DEFAULT_SEED_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "research"
    / "sector_taxonomy_seed_v1.json"
)
SOURCE_TABLES = ("asset", "ffg_research_universe_member_v1")
TARGET_TABLES = (
    "sector_definition",
    "liquidity_market_cap_definition",
    "asset_taxonomy_profile",
    "asset_cluster_membership",
)
UNCLASSIFIED = "UNCLASSIFIED"
FORBIDDEN_SECTOR_CODES = {"SEMI_MAJOR"}
REQUIRED_SECTOR_CODES = {
    "UNCLASSIFIED",
    "DEFI_LENDING",
    "DEFI_YIELD",
    "RWA",
    "RWA_INFRA",
    "AI_COMPUTE",
    "DECENTRALIZED_AI",
    "DEPIN",
    "L1",
    "L2",
    "PERP_DEX",
    "ORACLE",
    "CROSS_CHAIN",
    "PAYMENTS",
    "GAMING",
    "STABLECOIN_INFRA",
    "INSTITUTIONAL_FINANCE_INFRA",
    "SETTLEMENT_INTEROPERABILITY",
    "TOKENIZED_CAPITAL_MARKETS",
    "TOKENIZED_TREASURIES",
    "CLOUD_INFRA",
}
REQUIRED_CC_SECONDARIES = {
    "RWA_INFRA",
    "SETTLEMENT_INTEROPERABILITY",
    "TOKENIZED_CAPITAL_MARKETS",
}
PRECHECK_FAILURE_EXIT_CODE = 2
IMPORT_LOCK_NAME = "sector_taxonomy_import_v1"
ASSET_SECTOR_MAX_LENGTH = 32
ASSET_SECTOR_UNCHANGED = "unchanged"
ASSET_SECTOR_EMPTY_TO_CLASSIFIED = "null_empty_to_classified"
ASSET_SECTOR_EMPTY_TO_UNCLASSIFIED = "null_empty_to_unclassified"
ASSET_SECTOR_CLASSIFIED_TO_CLASSIFIED = "existing_classified_to_different_classified"
ASSET_SECTOR_PRESERVED_FROM_UNCLASSIFIED = "existing_classified_to_unclassified"


class TaxonomyPreflightError(ValueError):
    pass


@dataclass(frozen=True)
class ReconciliationCounts:
    inserts: int = 0
    updates: int = 0
    unchanged: int = 0
    stale: int = 0


@dataclass(frozen=True)
class AssetSectorMutation:
    asset_id: int
    asset_symbol: str
    current_sector: str
    proposed_sector: str
    category: str


@dataclass(frozen=True)
class AssetSectorAudit:
    mutations: tuple[AssetSectorMutation, ...] = ()

    def count(self, category: str) -> int:
        return sum(row.category == category for row in self.mutations)

    @property
    def safe_update_count(self) -> int:
        return sum(
            row.category
            not in {ASSET_SECTOR_UNCHANGED, ASSET_SECTOR_PRESERVED_FROM_UNCLASSIFIED}
            for row in self.mutations
        )


@dataclass(frozen=True)
class ImportPlan:
    sectors: ReconciliationCounts
    liquidity: ReconciliationCounts
    profiles: ReconciliationCounts
    memberships: ReconciliationCounts
    asset_sectors: AssetSectorAudit
    target_tables_missing: tuple[str, ...]

    @property
    def asset_sector_updates(self) -> int:
        return self.asset_sectors.safe_update_count

    @property
    def asset_sector_unchanged(self) -> int:
        return self.asset_sectors.count(ASSET_SECTOR_UNCHANGED)


def _upper(value: Any, field: str) -> str:
    normalized = str(value or "").strip().upper()
    if not normalized:
        raise ValueError(f"{field} must be non-empty")
    return normalized


def _decimal_01(value: Any, field: str) -> Decimal:
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal in [0, 1]") from exc
    if normalized < 0 or normalized > 1:
        raise ValueError(f"{field} must be in [0, 1]: {value}")
    return normalized


def _valid_from(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text.endswith("Z"):
        raise ValueError("valid_from_ts_utc must be an explicit UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("valid_from_ts_utc is invalid") from exc
    return parsed.astimezone(UTC).replace(tzinfo=None)


def load_seed(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("seed root must be an object")
    return payload


def _unique_codes(rows: list[dict[str, Any]], field: str) -> set[str]:
    seen: set[str] = set()
    for row in rows:
        code = _upper(row.get(field), field)
        if code in seen:
            raise ValueError(f"duplicate {field}: {code}")
        seen.add(code)
    return seen


def _asset_alias_map(assets: list[dict[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    canonical_symbols = {_upper(row.get("asset_symbol"), "asset_symbol") for row in assets}
    if len(canonical_symbols) != len(assets):
        raise ValueError("duplicate canonical asset_symbol")

    for row in assets:
        canonical = _upper(row.get("asset_symbol"), "asset_symbol")
        for source_symbol in [canonical, *(row.get("source_symbols") or [])]:
            source = _upper(source_symbol, "source_symbol")
            owner = aliases.get(source)
            if owner is not None and owner != canonical:
                raise ValueError(f"source symbol {source} maps to both {owner} and {canonical}")
            if source in canonical_symbols and source != canonical:
                raise ValueError(f"source symbol {source} collides with canonical asset {source}")
            aliases[source] = canonical
    return aliases


def validate_seed(seed: dict[str, Any]) -> None:
    if seed.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
    _valid_from(seed.get("valid_from_ts_utc"))

    sector_rows = seed.get("sector_definitions")
    liquidity_rows = seed.get("liquidity_market_cap_definitions")
    assets = seed.get("assets")
    if not isinstance(sector_rows, list) or not sector_rows:
        raise ValueError("sector_definitions must be a non-empty list")
    if not isinstance(liquidity_rows, list) or not liquidity_rows:
        raise ValueError("liquidity_market_cap_definitions must be a non-empty list")
    if not isinstance(assets, list) or not assets:
        raise ValueError("assets must be a non-empty list")

    sector_codes = _unique_codes(sector_rows, "sector_code")
    missing_required = sorted(REQUIRED_SECTOR_CODES - sector_codes)
    if missing_required:
        raise ValueError(f"missing required sector codes: {missing_required}")
    forbidden = sorted(FORBIDDEN_SECTOR_CODES & sector_codes)
    if forbidden:
        raise ValueError(f"liquidity/market-cap codes cannot be sectors: {forbidden}")
    for row in sector_rows:
        if not str(row.get("display_name") or "").strip():
            raise ValueError("sector display_name must be non-empty")
        if not str(row.get("description") or "").strip():
            raise ValueError("sector description must be non-empty")
        parent = row.get("parent_sector_code")
        if parent is not None and _upper(parent, "parent_sector_code") not in sector_codes:
            raise ValueError(f"unknown parent sector code: {parent}")
        if not isinstance(row.get("is_active"), bool):
            raise ValueError("sector is_active must be boolean")
        if not isinstance(row.get("sort_order"), int):
            raise ValueError("sector sort_order must be integer")

    liquidity_codes = _unique_codes(liquidity_rows, "liquidity_market_cap_code")
    if not {"UNCLASSIFIED", "SEMI_MAJOR"}.issubset(liquidity_codes):
        raise ValueError("liquidity dimension must define UNCLASSIFIED and SEMI_MAJOR")
    for row in liquidity_rows:
        if not str(row.get("display_name") or "").strip():
            raise ValueError("liquidity display_name must be non-empty")
        if not str(row.get("description") or "").strip():
            raise ValueError("liquidity description must be non-empty")
        if not isinstance(row.get("is_active"), bool):
            raise ValueError("liquidity is_active must be boolean")
        if not isinstance(row.get("sort_order"), int):
            raise ValueError("liquidity sort_order must be integer")

    _asset_alias_map(assets)
    for row in assets:
        symbol = _upper(row.get("asset_symbol"), "asset_symbol")
        primary = _upper(row.get("primary_sector"), f"{symbol}.primary_sector")
        liquidity = _upper(
            row.get("liquidity_market_cap_code"),
            f"{symbol}.liquidity_market_cap_code",
        )
        if primary not in sector_codes:
            raise ValueError(f"{symbol} has unknown primary sector code: {primary}")
        if len(primary) > ASSET_SECTOR_MAX_LENGTH:
            raise ValueError(
                f"{symbol} primary sector exceeds asset.sector length "
                f"{ASSET_SECTOR_MAX_LENGTH}: {primary}"
            )
        if liquidity not in liquidity_codes:
            raise ValueError(f"{symbol} has unknown liquidity code: {liquidity}")
        _decimal_01(row.get("confidence"), f"{symbol}.confidence")
        if not str(row.get("provenance") or "").strip():
            raise ValueError(f"{symbol}.provenance must be non-empty")
        notes = str(row.get("reviewer_notes") or "").strip()
        if primary == UNCLASSIFIED and not notes:
            raise ValueError(f"ambiguous classification {symbol} requires reviewer_notes")

        universe_memberships = row.get("universe_memberships") or []
        if not universe_memberships or any(
            item not in {"ENABLED", "FFG_RESEARCH_UNIVERSE_V1"}
            for item in universe_memberships
        ):
            raise ValueError(f"{symbol} has invalid universe_memberships")
        if len(universe_memberships) != len(set(universe_memberships)):
            raise ValueError(f"{symbol} has duplicate universe_memberships")

        membership_codes = {primary}
        for secondary in row.get("secondary_clusters") or []:
            code = _upper(secondary.get("sector_code"), f"{symbol}.secondary.sector_code")
            if code not in sector_codes:
                raise ValueError(f"{symbol} has unknown secondary sector code: {code}")
            if code in membership_codes:
                raise ValueError(f"duplicate active membership for {symbol}: {code}")
            membership_codes.add(code)
            _decimal_01(secondary.get("weight"), f"{symbol}.{code}.weight")
            _decimal_01(secondary.get("confidence"), f"{symbol}.{code}.confidence")
            if not str(secondary.get("provenance") or row.get("provenance") or "").strip():
                raise ValueError(f"{symbol}.{code}.provenance must be non-empty")

    by_symbol = {_upper(row["asset_symbol"], "asset_symbol"): row for row in assets}
    cc = by_symbol.get("CC")
    if cc is None or _upper(cc.get("primary_sector"), "CC.primary_sector") != "INSTITUTIONAL_FINANCE_INFRA":
        raise ValueError("CC primary sector must be INSTITUTIONAL_FINANCE_INFRA")
    cc_secondaries = {
        _upper(item.get("sector_code"), "CC.secondary.sector_code")
        for item in cc.get("secondary_clusters") or []
    }
    if not REQUIRED_CC_SECONDARIES.issubset(cc_secondaries):
        raise ValueError("CC is missing required secondary clusters")


def normalized_sector_rows(seed: dict[str, Any]) -> list[dict[str, Any]]:
    version = seed["schema_version"]
    return sorted(
        [
            {
                "sector_code": _upper(row["sector_code"], "sector_code"),
                "display_name": str(row["display_name"]).strip(),
                "description": str(row["description"]).strip(),
                "parent_sector_code": (
                    _upper(row["parent_sector_code"], "parent_sector_code")
                    if row.get("parent_sector_code") is not None
                    else None
                ),
                "is_active": int(row["is_active"]),
                "sort_order": int(row["sort_order"]),
                "seed_schema_version": version,
            }
            for row in seed["sector_definitions"]
        ],
        key=lambda row: (row["sort_order"], row["sector_code"]),
    )


def normalized_liquidity_rows(seed: dict[str, Any]) -> list[dict[str, Any]]:
    version = seed["schema_version"]
    return sorted(
        [
            {
                "liquidity_market_cap_code": _upper(
                    row["liquidity_market_cap_code"], "liquidity_market_cap_code"
                ),
                "display_name": str(row["display_name"]).strip(),
                "description": str(row["description"]).strip(),
                "is_active": int(row["is_active"]),
                "sort_order": int(row["sort_order"]),
                "seed_schema_version": version,
            }
            for row in seed["liquidity_market_cap_definitions"]
        ],
        key=lambda row: (row["sort_order"], row["liquidity_market_cap_code"]),
    )


def fetch_present_tables(conn: Any) -> set[str]:
    names = (*SOURCE_TABLES, *TARGET_TABLES)
    placeholders = ", ".join(["%s"] * len(names))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_name IN ({placeholders})
            """,
            names,
        )
        return {str(row["table_name"]) for row in cur.fetchall()}


def fetch_universe(conn: Any) -> tuple[dict[str, dict[str, Any]], set[str], set[str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT asset_id, symbol, sector, asset_class
            FROM asset
            ORDER BY symbol
            """
        )
        asset_rows = {
            _upper(row["symbol"], "asset.symbol"): dict(row)
            for row in cur.fetchall()
        }
        cur.execute("SELECT symbol FROM asset WHERE is_enabled = 1 ORDER BY symbol")
        enabled = {_upper(row["symbol"], "asset.symbol") for row in cur.fetchall()}
        cur.execute(
            """
            SELECT source_symbol
            FROM ffg_research_universe_member_v1
            WHERE research_status = 'RESEARCH_UNIVERSE'
            ORDER BY source_symbol
            """
        )
        research = {
            _upper(row["source_symbol"], "research.source_symbol")
            for row in cur.fetchall()
        }
    return asset_rows, enabled, research


def validate_database_coverage(
    seed: dict[str, Any],
    enabled_symbols: set[str],
    research_symbols: set[str],
) -> tuple[int, int, int]:
    assets = seed["assets"]
    aliases = _asset_alias_map(assets)
    rows = {_upper(row["asset_symbol"], "asset_symbol"): row for row in assets}

    missing_enabled = sorted(symbol for symbol in enabled_symbols if symbol not in aliases)
    missing_research = sorted(symbol for symbol in research_symbols if symbol not in aliases)
    if missing_enabled or missing_research:
        raise TaxonomyPreflightError(
            f"universe coverage incomplete: enabled_missing={missing_enabled} "
            f"research_missing={missing_research}"
        )

    declared_enabled = {
        canonical
        for canonical, row in rows.items()
        if "ENABLED" in row["universe_memberships"]
    }
    declared_research_sources = {
        source
        for source, canonical in aliases.items()
        if "FFG_RESEARCH_UNIVERSE_V1" in rows[canonical]["universe_memberships"]
        and source in research_symbols
    }
    actual_enabled_canonical = {aliases[symbol] for symbol in enabled_symbols}
    if declared_enabled != actual_enabled_canonical:
        raise TaxonomyPreflightError(
            "enabled universe declarations differ from database: "
            f"seed_only={sorted(declared_enabled - actual_enabled_canonical)} "
            f"db_only={sorted(actual_enabled_canonical - declared_enabled)}"
        )
    if declared_research_sources != research_symbols:
        raise TaxonomyPreflightError(
            "research universe declarations differ from database: "
            f"seed_only={sorted(declared_research_sources - research_symbols)} "
            f"db_only={sorted(research_symbols - declared_research_sources)}"
        )
    return len(enabled_symbols), len(research_symbols), len(actual_enabled_canonical | {aliases[s] for s in research_symbols})


def desired_profiles(
    seed: dict[str, Any],
    asset_rows: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    version = seed["schema_version"]
    profiles: dict[str, dict[str, Any]] = {}
    for row in seed["assets"]:
        symbol = _upper(row["asset_symbol"], "asset_symbol")
        local = asset_rows.get(symbol)
        sources = sorted({_upper(item, "source_symbol") for item in [symbol, *(row.get("source_symbols") or [])]})
        profiles[symbol] = {
            "asset_symbol": symbol,
            "asset_id": int(local["asset_id"]) if local is not None else None,
            "liquidity_market_cap_code": _upper(
                row["liquidity_market_cap_code"], "liquidity_market_cap_code"
            ),
            "is_enabled_universe": int("ENABLED" in row["universe_memberships"]),
            "is_research_universe": int("FFG_RESEARCH_UNIVERSE_V1" in row["universe_memberships"]),
            "source_symbols_json": json.dumps(sources, separators=(",", ":")),
            "provenance": str(row["provenance"]).strip(),
            "reviewer_notes": str(row.get("reviewer_notes") or "").strip() or None,
            "seed_schema_version": version,
        }
    return profiles


def desired_memberships(
    seed: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    version = seed["schema_version"]
    valid_from = _valid_from(seed["valid_from_ts_utc"])
    desired: dict[tuple[str, str], dict[str, Any]] = {}
    for asset in seed["assets"]:
        symbol = _upper(asset["asset_symbol"], "asset_symbol")
        primary_code = _upper(asset["primary_sector"], "primary_sector")
        desired[(symbol, primary_code)] = {
            "asset_symbol": symbol,
            "asset_id": profiles[symbol]["asset_id"],
            "sector_code": primary_code,
            "membership_weight": Decimal("1"),
            "membership_type": "PRIMARY",
            "confidence": _decimal_01(asset["confidence"], f"{symbol}.confidence"),
            "provenance": str(asset["provenance"]).strip(),
            "valid_from_ts_utc": valid_from,
            "reviewer_notes": str(asset.get("reviewer_notes") or "").strip() or None,
            "seed_schema_version": version,
        }
        for cluster in asset.get("secondary_clusters") or []:
            code = _upper(cluster["sector_code"], "secondary.sector_code")
            desired[(symbol, code)] = {
                "asset_symbol": symbol,
                "asset_id": profiles[symbol]["asset_id"],
                "sector_code": code,
                "membership_weight": _decimal_01(cluster["weight"], f"{symbol}.{code}.weight"),
                "membership_type": "SECONDARY",
                "confidence": _decimal_01(cluster["confidence"], f"{symbol}.{code}.confidence"),
                "provenance": str(cluster.get("provenance") or asset["provenance"]).strip(),
                "valid_from_ts_utc": valid_from,
                "reviewer_notes": str(cluster.get("reviewer_notes") or "").strip() or None,
                "seed_schema_version": version,
            }
    return desired


def _fetch_rows(conn: Any, table: str, order_by: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {table} ORDER BY {order_by}")
        return [dict(row) for row in cur.fetchall()]


def _normalized_compare(value: Any) -> Any:
    if isinstance(value, Decimal):
        return value.normalize()
    if isinstance(value, bool):
        return int(value)
    return value


def _same(row: dict[str, Any], desired: dict[str, Any], fields: Iterable[str]) -> bool:
    return all(
        _normalized_compare(row.get(field)) == _normalized_compare(desired.get(field))
        for field in fields
    )


def _definition_counts(
    existing: dict[str, dict[str, Any]],
    desired: dict[str, dict[str, Any]],
    fields: tuple[str, ...],
) -> ReconciliationCounts:
    inserts = sum(key not in existing for key in desired)
    updates = sum(
        key in existing and not _same(existing[key], row, fields)
        for key, row in desired.items()
    )
    unchanged = len(desired) - inserts - updates
    stale = sum(key not in desired and int(row.get("is_active") or 0) == 1 for key, row in existing.items())
    return ReconciliationCounts(inserts, updates, unchanged, stale)


def build_asset_sector_audit(
    seed: dict[str, Any],
    asset_rows: dict[str, dict[str, Any]],
) -> AssetSectorAudit:
    mutations: list[AssetSectorMutation] = []
    for asset in sorted(seed["assets"], key=lambda row: _upper(row["asset_symbol"], "asset_symbol")):
        symbol = _upper(asset["asset_symbol"], "asset_symbol")
        local = asset_rows.get(symbol)
        if local is None:
            continue
        current = str(local.get("sector") or "").strip()
        proposed = _upper(asset["primary_sector"], "primary_sector")
        if current == proposed:
            category = ASSET_SECTOR_UNCHANGED
        elif not current:
            category = (
                ASSET_SECTOR_EMPTY_TO_UNCLASSIFIED
                if proposed == UNCLASSIFIED
                else ASSET_SECTOR_EMPTY_TO_CLASSIFIED
            )
        elif proposed == UNCLASSIFIED:
            category = ASSET_SECTOR_PRESERVED_FROM_UNCLASSIFIED
        else:
            category = ASSET_SECTOR_CLASSIFIED_TO_CLASSIFIED
        mutations.append(
            AssetSectorMutation(
                asset_id=int(local["asset_id"]),
                asset_symbol=symbol,
                current_sector=current,
                proposed_sector=proposed,
                category=category,
            )
        )
    return AssetSectorAudit(tuple(mutations))


def build_plan(
    seed: dict[str, Any],
    asset_rows: dict[str, dict[str, Any]],
    existing_sectors: list[dict[str, Any]],
    existing_liquidity: list[dict[str, Any]],
    existing_profiles: list[dict[str, Any]],
    existing_memberships: list[dict[str, Any]],
    target_tables_missing: tuple[str, ...] = (),
) -> ImportPlan:
    sectors = {row["sector_code"]: row for row in normalized_sector_rows(seed)}
    liquidity = {
        row["liquidity_market_cap_code"]: row
        for row in normalized_liquidity_rows(seed)
    }
    profiles = desired_profiles(seed, asset_rows)
    memberships = desired_memberships(seed, profiles)

    existing_sector_map = {str(row["sector_code"]): row for row in existing_sectors}
    existing_liquidity_map = {
        str(row["liquidity_market_cap_code"]): row for row in existing_liquidity
    }
    existing_profile_map = {str(row["asset_symbol"]): row for row in existing_profiles}
    active_membership_map = {
        (str(row["asset_symbol"]), str(row["sector_code"])): row
        for row in existing_memberships
        if row.get("valid_to_ts_utc") is None
    }

    sector_fields = (
        "display_name", "description", "parent_sector_code", "is_active",
        "sort_order", "seed_schema_version",
    )
    liquidity_fields = (
        "display_name", "description", "is_active", "sort_order", "seed_schema_version",
    )
    profile_fields = (
        "asset_id", "liquidity_market_cap_code", "is_enabled_universe",
        "is_research_universe", "source_symbols_json", "provenance",
        "reviewer_notes", "seed_schema_version",
    )
    membership_fields = (
        "asset_id", "membership_weight", "membership_type", "confidence",
        "provenance", "reviewer_notes", "seed_schema_version",
    )

    profile_inserts = sum(key not in existing_profile_map for key in profiles)
    profile_updates = sum(
        key in existing_profile_map and not _same(existing_profile_map[key], row, profile_fields)
        for key, row in profiles.items()
    )
    profile_unchanged = len(profiles) - profile_inserts - profile_updates
    profile_stale = sum(key not in profiles for key in existing_profile_map)

    membership_inserts = sum(key not in active_membership_map for key in memberships)
    membership_updates = sum(
        key in active_membership_map and not _same(active_membership_map[key], row, membership_fields)
        for key, row in memberships.items()
    )
    membership_unchanged = len(memberships) - membership_inserts - membership_updates
    membership_stale = sum(key not in memberships for key in active_membership_map)

    return ImportPlan(
        sectors=_definition_counts(existing_sector_map, sectors, sector_fields),
        liquidity=_definition_counts(existing_liquidity_map, liquidity, liquidity_fields),
        profiles=ReconciliationCounts(
            profile_inserts, profile_updates, profile_unchanged, profile_stale
        ),
        memberships=ReconciliationCounts(
            membership_inserts, membership_updates, membership_unchanged, membership_stale
        ),
        asset_sectors=build_asset_sector_audit(seed, asset_rows),
        target_tables_missing=target_tables_missing,
    )


def _upsert_definitions(conn: Any, seed: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        for row in normalized_sector_rows(seed):
            cur.execute(
                """
                INSERT INTO sector_definition (
                    sector_code, display_name, description, parent_sector_code,
                    is_active, sort_order, seed_schema_version
                ) VALUES (
                    %(sector_code)s, %(display_name)s, %(description)s, %(parent_sector_code)s,
                    %(is_active)s, %(sort_order)s, %(seed_schema_version)s
                )
                ON DUPLICATE KEY UPDATE
                    display_name = VALUES(display_name),
                    description = VALUES(description),
                    parent_sector_code = VALUES(parent_sector_code),
                    is_active = VALUES(is_active),
                    sort_order = VALUES(sort_order),
                    seed_schema_version = VALUES(seed_schema_version)
                """,
                row,
            )
        codes = [row["sector_code"] for row in normalized_sector_rows(seed)]
        placeholders = ", ".join(["%s"] * len(codes))
        cur.execute(
            f"UPDATE sector_definition SET is_active = 0 WHERE is_active = 1 AND sector_code NOT IN ({placeholders})",
            codes,
        )

        for row in normalized_liquidity_rows(seed):
            cur.execute(
                """
                INSERT INTO liquidity_market_cap_definition (
                    liquidity_market_cap_code, display_name, description,
                    is_active, sort_order, seed_schema_version
                ) VALUES (
                    %(liquidity_market_cap_code)s, %(display_name)s, %(description)s,
                    %(is_active)s, %(sort_order)s, %(seed_schema_version)s
                )
                ON DUPLICATE KEY UPDATE
                    display_name = VALUES(display_name),
                    description = VALUES(description),
                    is_active = VALUES(is_active),
                    sort_order = VALUES(sort_order),
                    seed_schema_version = VALUES(seed_schema_version)
                """,
                row,
            )
        codes = [row["liquidity_market_cap_code"] for row in normalized_liquidity_rows(seed)]
        placeholders = ", ".join(["%s"] * len(codes))
        cur.execute(
            f"UPDATE liquidity_market_cap_definition SET is_active = 0 WHERE is_active = 1 AND liquidity_market_cap_code NOT IN ({placeholders})",
            codes,
        )


def apply_asset_sector_updates(
    conn: Any,
    seed: dict[str, Any],
    asset_rows: dict[str, dict[str, Any]],
) -> AssetSectorAudit:
    audit = build_asset_sector_audit(seed, asset_rows)
    with conn.cursor() as cur:
        for row in audit.mutations:
            if row.category in {
                ASSET_SECTOR_UNCHANGED,
                ASSET_SECTOR_PRESERVED_FROM_UNCLASSIFIED,
            }:
                continue
            if row.proposed_sector == UNCLASSIFIED:
                cur.execute(
                    """
                    UPDATE asset
                    SET sector = %s
                    WHERE asset_id = %s
                      AND (sector IS NULL OR TRIM(sector) = '')
                    """,
                    (row.proposed_sector, row.asset_id),
                )
                if getattr(cur, "rowcount", 1) == 0:
                    raise TaxonomyPreflightError(
                        "asset.sector changed after audit; refusing UNCLASSIFIED write "
                        f"for {row.asset_symbol}"
                    )
                continue
            cur.execute(
                "UPDATE asset SET sector = %s WHERE asset_id = %s",
                (row.proposed_sector, row.asset_id),
            )
    return audit


def apply_plan(conn: Any, seed: dict[str, Any], asset_rows: dict[str, dict[str, Any]]) -> None:
    profiles = desired_profiles(seed, asset_rows)
    memberships = desired_memberships(seed, profiles)
    valid_from = _valid_from(seed["valid_from_ts_utc"])
    _upsert_definitions(conn, seed)

    with conn.cursor() as cur:
        for row in profiles.values():
            cur.execute(
                """
                INSERT INTO asset_taxonomy_profile (
                    asset_symbol, asset_id, liquidity_market_cap_code,
                    is_enabled_universe, is_research_universe, source_symbols_json,
                    provenance, reviewer_notes, seed_schema_version
                ) VALUES (
                    %(asset_symbol)s, %(asset_id)s, %(liquidity_market_cap_code)s,
                    %(is_enabled_universe)s, %(is_research_universe)s, %(source_symbols_json)s,
                    %(provenance)s, %(reviewer_notes)s, %(seed_schema_version)s
                )
                ON DUPLICATE KEY UPDATE
                    asset_id = VALUES(asset_id),
                    liquidity_market_cap_code = VALUES(liquidity_market_cap_code),
                    is_enabled_universe = VALUES(is_enabled_universe),
                    is_research_universe = VALUES(is_research_universe),
                    source_symbols_json = VALUES(source_symbols_json),
                    provenance = VALUES(provenance),
                    reviewer_notes = VALUES(reviewer_notes),
                    seed_schema_version = VALUES(seed_schema_version)
                """,
                row,
            )

        symbols = sorted(profiles)
        placeholders = ", ".join(["%s"] * len(symbols))
        cur.execute(
            f"""
            UPDATE asset_taxonomy_profile
            SET is_enabled_universe = 0,
                is_research_universe = 0
            WHERE asset_symbol NOT IN ({placeholders})
              AND (is_enabled_universe = 1 OR is_research_universe = 1)
            """,
            symbols,
        )

        cur.execute(
            """
            SELECT * FROM asset_cluster_membership
            WHERE valid_to_ts_utc IS NULL
            ORDER BY asset_symbol, sector_code
            """
        )
        active = {
            (str(row["asset_symbol"]), str(row["sector_code"])): dict(row)
            for row in cur.fetchall()
        }
        compare_fields = (
            "asset_id", "membership_weight", "membership_type", "confidence",
            "provenance", "reviewer_notes", "seed_schema_version",
        )
        expire_keys = {
            key
            for key, row in active.items()
            if key not in memberships or not _same(row, memberships[key], compare_fields)
        }
        for key in sorted(expire_keys):
            row = active[key]
            if row["valid_from_ts_utc"] >= valid_from:
                raise TaxonomyPreflightError(
                    f"seed valid_from must be later than active membership for {key}"
                )
            cur.execute(
                """
                UPDATE asset_cluster_membership
                SET valid_to_ts_utc = %s
                WHERE asset_cluster_membership_id = %s
                  AND valid_to_ts_utc IS NULL
                """,
                (valid_from, row["asset_cluster_membership_id"]),
            )

        for key, row in sorted(memberships.items()):
            existing = active.get(key)
            if existing is not None and key not in expire_keys:
                continue
            cur.execute(
                """
                INSERT INTO asset_cluster_membership (
                    asset_symbol, asset_id, sector_code, membership_weight,
                    membership_type, confidence, provenance, valid_from_ts_utc,
                    reviewer_notes, seed_schema_version
                ) VALUES (
                    %(asset_symbol)s, %(asset_id)s, %(sector_code)s, %(membership_weight)s,
                    %(membership_type)s, %(confidence)s, %(provenance)s, %(valid_from_ts_utc)s,
                    %(reviewer_notes)s, %(seed_schema_version)s
                )
                """,
                row,
            )

    apply_asset_sector_updates(conn, seed, asset_rows)


def acquire_import_lock(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT GET_LOCK(%s, 0) AS acquired", (IMPORT_LOCK_NAME,))
        row = cur.fetchone()
    if row is None or int(row.get("acquired") or 0) != 1:
        raise TaxonomyPreflightError("another sector taxonomy import holds the DB lock")


def release_import_lock(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT RELEASE_LOCK(%s) AS released", (IMPORT_LOCK_NAME,))


def _print_counts(label: str, counts: ReconciliationCounts) -> None:
    print(
        f"  {label}: inserts={counts.inserts} updates={counts.updates} "
        f"unchanged={counts.unchanged} stale={counts.stale}"
    )


def _print_plan(plan: ImportPlan) -> None:
    _print_counts("sector_definitions", plan.sectors)
    _print_counts("liquidity_definitions", plan.liquidity)
    _print_counts("asset_profiles", plan.profiles)
    _print_counts("memberships", plan.memberships)
    audit = plan.asset_sectors
    print(f"  asset_primary_sectors: unchanged={audit.count(ASSET_SECTOR_UNCHANGED)}")
    print(
        "  asset_primary_sectors: null_empty_to_classified="
        f"{audit.count(ASSET_SECTOR_EMPTY_TO_CLASSIFIED)}"
    )
    print(
        "  asset_primary_sectors: null_empty_to_unclassified="
        f"{audit.count(ASSET_SECTOR_EMPTY_TO_UNCLASSIFIED)}"
    )
    print(
        "  asset_primary_sectors: existing_classified_to_different_classified="
        f"{audit.count(ASSET_SECTOR_CLASSIFIED_TO_CLASSIFIED)}"
    )
    print(
        "  asset_primary_sectors: existing_classified_to_unclassified_preserved="
        f"{audit.count(ASSET_SECTOR_PRESERVED_FROM_UNCLASSIFIED)}"
    )
    for row in audit.mutations:
        if row.category == ASSET_SECTOR_PRESERVED_FROM_UNCLASSIFIED:
            print(
                "  asset_primary_sector_preserved: "
                f"symbol={row.asset_symbol} current={row.current_sector} "
                f"taxonomy_status={row.proposed_sector}"
            )
    print(f"  asset_primary_sectors: safe_updates={audit.safe_update_count}")
    if plan.target_tables_missing:
        print(
            "  migration_required_for_write_db: "
            + ",".join(plan.target_tables_missing)
            + f" migration={MIGRATION_PATH}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate or reconcile Sector Taxonomy & Database Seed v1."
    )
    parser.add_argument("--seed-file", type=Path, default=DEFAULT_SEED_PATH)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--write-db", action="store_true")
    args = parser.parse_args(argv)
    mode_name = "validate-only" if args.validate_only else "dry-run" if args.dry_run else "write-db"

    print(
        "STARTED runner=sector_taxonomy_import_v1 "
        f"mode={mode_name} scope=enabled+research-universe workers=1"
    )
    print(
        "  broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
        "decision_gate=none execution_planner=none executor=none"
    )
    conn = None
    import_lock_acquired = False
    try:
        seed = load_seed(args.seed_file)
        validate_seed(seed)
        assets = seed["assets"]
        primary_counts: dict[str, int] = {}
        for row in assets:
            code = _upper(row["primary_sector"], "primary_sector")
            primary_counts[code] = primary_counts.get(code, 0) + 1
        print(
            f"  seed_valid schema_version={seed['schema_version']} "
            f"assets={len(assets)} sector_definitions={len(seed['sector_definitions'])} "
            f"liquidity_definitions={len(seed['liquidity_market_cap_definitions'])}"
        )
        print(
            f"  classified={len(assets) - primary_counts.get(UNCLASSIFIED, 0)} "
            f"unclassified={primary_counts.get(UNCLASSIFIED, 0)}"
        )
        if args.validate_only:
            print("FINISHED runner=sector_taxonomy_import_v1 mode=validate-only db_connections=0 db_writes=0")
            return 0

        conn = get_connection()
        if args.write_db:
            acquire_import_lock(conn)
            import_lock_acquired = True
        present = fetch_present_tables(conn)
        missing_source = sorted(set(SOURCE_TABLES) - present)
        if missing_source:
            raise TaxonomyPreflightError(f"required source tables missing: {missing_source}")
        missing_target = tuple(sorted(set(TARGET_TABLES) - present))
        if args.write_db and missing_target:
            raise TaxonomyPreflightError(
                f"MIGRATION_REQUIRED missing={list(missing_target)} migration={MIGRATION_PATH}"
            )

        asset_rows, enabled, research = fetch_universe(conn)
        enabled_count, research_count, canonical_count = validate_database_coverage(
            seed, enabled, research
        )
        print(
            f"  coverage enabled={enabled_count}/{enabled_count} "
            f"research={research_count}/{research_count} canonical_assets={canonical_count}"
        )

        existing_sectors = [] if "sector_definition" in missing_target else _fetch_rows(conn, "sector_definition", "sector_code")
        existing_liquidity = [] if "liquidity_market_cap_definition" in missing_target else _fetch_rows(conn, "liquidity_market_cap_definition", "liquidity_market_cap_code")
        existing_profiles = [] if "asset_taxonomy_profile" in missing_target else _fetch_rows(conn, "asset_taxonomy_profile", "asset_symbol")
        existing_memberships = [] if "asset_cluster_membership" in missing_target else _fetch_rows(conn, "asset_cluster_membership", "asset_symbol, sector_code, valid_from_ts_utc")
        plan = build_plan(
            seed,
            asset_rows,
            existing_sectors,
            existing_liquidity,
            existing_profiles,
            existing_memberships,
            missing_target,
        )
        _print_plan(plan)

        if args.write_db:
            apply_plan(conn, seed, asset_rows)
            conn.commit()
            print("  transaction=committed")
        else:
            conn.rollback()
            print("  transaction=rolled_back dry_run_db_writes=0")
        print(
            f"FINISHED runner=sector_taxonomy_import_v1 mode={mode_name} "
            f"db_writes={1 if args.write_db else 0}"
        )
        return 0
    except (OSError, json.JSONDecodeError, ValueError, TaxonomyPreflightError) as exc:
        if conn is not None:
            conn.rollback()
        print(f"FAILED runner=sector_taxonomy_import_v1 reason={exc}")
        return PRECHECK_FAILURE_EXIT_CODE
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        print(f"FAILED runner=sector_taxonomy_import_v1 reason={type(exc).__name__}: {exc}")
        return 1
    finally:
        if conn is not None:
            if import_lock_acquired:
                try:
                    release_import_lock(conn)
                except Exception as exc:
                    print(f"  lock_release_warning={type(exc).__name__}: {exc}")
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
