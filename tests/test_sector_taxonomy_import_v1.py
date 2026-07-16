from __future__ import annotations

import copy
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from src.research import run_sector_taxonomy_import_v1 as importer


SEED_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "research"
    / "sector_taxonomy_seed_v1.json"
)


@pytest.fixture(scope="module")
def seed() -> dict:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def asset(seed: dict, symbol: str) -> dict:
    return next(row for row in seed["assets"] if row["asset_symbol"] == symbol)


def test_actual_seed_validates(seed: dict) -> None:
    importer.validate_seed(seed)


def test_actual_seed_has_complete_review_shape(seed: dict) -> None:
    assert len(seed["assets"]) == 448
    assert len({row["asset_symbol"] for row in seed["assets"]}) == 448
    assert sum(row["primary_sector"] != "UNCLASSIFIED" for row in seed["assets"]) == 103
    assert sum(row["primary_sector"] == "UNCLASSIFIED" for row in seed["assets"]) == 345
    assert all(row["reviewer_notes"].strip() for row in seed["assets"])


def test_required_sector_codes_exist(seed: dict) -> None:
    codes = {row["sector_code"] for row in seed["sector_definitions"]}
    assert importer.REQUIRED_SECTOR_CODES <= codes


def test_semi_major_is_only_liquidity_dimension(seed: dict) -> None:
    sector_codes = {row["sector_code"] for row in seed["sector_definitions"]}
    liquidity_codes = {
        row["liquidity_market_cap_code"]
        for row in seed["liquidity_market_cap_definitions"]
    }
    assert "SEMI_MAJOR" not in sector_codes
    assert "SEMI_MAJOR" in liquidity_codes


def test_cc_required_primary_and_cross_clusters(seed: dict) -> None:
    cc = asset(seed, "CC")
    assert cc["primary_sector"] == "INSTITUTIONAL_FINANCE_INFRA"
    assert {row["sector_code"] for row in cc["secondary_clusters"]} >= {
        "RWA_INFRA",
        "SETTLEMENT_INTEROPERABILITY",
        "TOKENIZED_CAPITAL_MARKETS",
    }
    assert "prior FFG identity status was unresolved" in cc["reviewer_notes"]


@pytest.mark.parametrize("symbol", ["LINK", "XLM"])
def test_cross_cluster_assets_are_not_duplicated(seed: dict, symbol: str) -> None:
    rows = [row for row in seed["assets"] if row["asset_symbol"] == symbol]
    assert len(rows) == 1
    codes = [rows[0]["primary_sector"]] + [
        row["sector_code"] for row in rows[0]["secondary_clusters"]
    ]
    assert len(codes) == len(set(codes))
    assert len(codes) >= 4


def test_research_aliases_do_not_duplicate_local_assets(seed: dict) -> None:
    assert asset(seed, "RENDER")["source_symbols"] == ["RNDR"]
    assert asset(seed, "LIGHTER")["source_symbols"] == ["LIT"]
    assert not any(row["asset_symbol"] in {"RNDR", "LIT"} for row in seed["assets"])


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("AAVE", "DEFI_LENDING"),
        ("PENDLE", "DEFI_YIELD"),
        ("AKT", "AI_COMPUTE"),
        ("TAO", "DECENTRALIZED_AI"),
        ("RENDER", "AI_COMPUTE"),
        ("ENA", "STABLECOIN_INFRA"),
        ("ONDO", "RWA"),
        ("PLUME", "RWA_INFRA"),
        ("POL", "L2"),
        ("HYPE", "PERP_DEX"),
        ("LIGHTER", "PERP_DEX"),
        ("NEAR", "L1"),
        ("VET", "L1"),
        ("CHIP", "AI_COMPUTE"),
    ],
)
def test_required_reviewed_classifications(seed: dict, symbol: str, expected: str) -> None:
    assert asset(seed, symbol)["primary_sector"] == expected


def test_deep_is_explicitly_reviewed_unclassified(seed: dict) -> None:
    deep = asset(seed, "DEEP")
    assert deep["primary_sector"] == "UNCLASSIFIED"
    assert "intentionally UNCLASSIFIED" in deep["reviewer_notes"]


def test_unknown_sector_code_fails(seed: dict) -> None:
    invalid = copy.deepcopy(seed)
    invalid["assets"][0]["primary_sector"] = "NOT_A_SECTOR"
    with pytest.raises(ValueError, match="unknown primary sector code"):
        importer.validate_seed(invalid)


def test_semi_major_sector_definition_fails(seed: dict) -> None:
    invalid = copy.deepcopy(seed)
    invalid["sector_definitions"].append(
        {
            "sector_code": "SEMI_MAJOR",
            "display_name": "Wrong",
            "description": "Wrong dimension.",
            "parent_sector_code": None,
            "is_active": True,
            "sort_order": 999,
        }
    )
    with pytest.raises(ValueError, match="cannot be sectors"):
        importer.validate_seed(invalid)


def test_duplicate_active_membership_fails(seed: dict) -> None:
    invalid = copy.deepcopy(seed)
    aave = asset(invalid, "AAVE")
    aave["secondary_clusters"].append(
        {
            "sector_code": "DEFI_LENDING",
            "weight": "0.5",
            "confidence": "0.5",
            "provenance": "test",
            "reviewer_notes": "duplicate",
        }
    )
    with pytest.raises(ValueError, match="duplicate active membership"):
        importer.validate_seed(invalid)


@pytest.mark.parametrize(("field", "value"), [("weight", "1.01"), ("confidence", "-0.01")])
def test_invalid_secondary_range_fails(seed: dict, field: str, value: str) -> None:
    invalid = copy.deepcopy(seed)
    asset(invalid, "AKT")["secondary_clusters"][0][field] = value
    with pytest.raises(ValueError, match=r"must be in \[0, 1\]"):
        importer.validate_seed(invalid)


def test_invalid_primary_confidence_fails(seed: dict) -> None:
    invalid = copy.deepcopy(seed)
    invalid["assets"][0]["confidence"] = "2"
    with pytest.raises(ValueError, match=r"must be in \[0, 1\]"):
        importer.validate_seed(invalid)


def test_primary_sector_must_fit_canonical_asset_column(seed: dict) -> None:
    invalid = copy.deepcopy(seed)
    long_code = "X" * 33
    invalid["sector_definitions"].append(
        {
            "sector_code": long_code,
            "display_name": "Too long for asset.sector",
            "description": "Valid definition width but invalid primary width.",
            "parent_sector_code": None,
            "is_active": True,
            "sort_order": 999,
        }
    )
    invalid["assets"][0]["primary_sector"] = long_code
    with pytest.raises(ValueError, match="exceeds asset.sector length"):
        importer.validate_seed(invalid)


def test_ambiguous_classification_requires_notes(seed: dict) -> None:
    invalid = copy.deepcopy(seed)
    unclassified = next(row for row in invalid["assets"] if row["primary_sector"] == "UNCLASSIFIED")
    unclassified["reviewer_notes"] = ""
    with pytest.raises(ValueError, match="ambiguous classification"):
        importer.validate_seed(invalid)


def test_alias_collision_fails(seed: dict) -> None:
    invalid = copy.deepcopy(seed)
    asset(invalid, "RENDER")["source_symbols"].append("LINK")
    with pytest.raises(ValueError, match="maps to both"):
        importer.validate_seed(invalid)


def _database_sets(seed: dict) -> tuple[set[str], set[str]]:
    enabled = {
        row["asset_symbol"]
        for row in seed["assets"]
        if "ENABLED" in row["universe_memberships"]
    }
    research: set[str] = set()
    for row in seed["assets"]:
        if "FFG_RESEARCH_UNIVERSE_V1" not in row["universe_memberships"]:
            continue
        aliases = row["source_symbols"] or [row["asset_symbol"]]
        research.update(aliases)
        if not row["source_symbols"]:
            research.add(row["asset_symbol"])
    return enabled, research


def test_database_coverage_accepts_aliases(seed: dict) -> None:
    enabled, research = _database_sets(seed)
    assert "RNDR" in research and "RENDER" not in research
    assert "LIT" in research and "LIGHTER" not in research
    assert importer.validate_database_coverage(seed, enabled, research) == (429, 100, 448)


def test_database_coverage_fails_missing_enabled(seed: dict) -> None:
    enabled, research = _database_sets(seed)
    with pytest.raises(importer.TaxonomyPreflightError, match="enabled_missing"):
        importer.validate_database_coverage(seed, enabled | {"MISSING"}, research)


def test_database_coverage_fails_stale_scope_declaration(seed: dict) -> None:
    enabled, research = _database_sets(seed)
    invalid = copy.deepcopy(seed)
    asset(invalid, "AAVE")["universe_memberships"].remove("ENABLED")
    with pytest.raises(importer.TaxonomyPreflightError, match="enabled universe declarations"):
        importer.validate_database_coverage(invalid, enabled, research)


def _asset_rows(seed: dict) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    next_id = 1
    for row in seed["assets"]:
        if "ENABLED" not in row["universe_memberships"]:
            continue
        rows[row["asset_symbol"]] = {
            "asset_id": next_id,
            "symbol": row["asset_symbol"],
            "sector": row["primary_sector"],
            "asset_class": row["liquidity_market_cap_code"],
        }
        next_id += 1
    return rows


def test_empty_database_plan_is_all_inserts(seed: dict) -> None:
    plan = importer.build_plan(seed, _asset_rows(seed), [], [], [], [])
    assert plan.sectors.inserts == 29
    assert plan.liquidity.inserts == 7
    assert plan.profiles.inserts == 448
    assert plan.memberships.inserts == 473
    assert plan.asset_sector_updates == 0
    assert plan.asset_sector_unchanged == 429


def test_second_plan_is_deterministically_unchanged(seed: dict) -> None:
    asset_rows = _asset_rows(seed)
    sectors = importer.normalized_sector_rows(seed)
    liquidity = importer.normalized_liquidity_rows(seed)
    profiles = list(importer.desired_profiles(seed, asset_rows).values())
    memberships = list(importer.desired_memberships(seed, importer.desired_profiles(seed, asset_rows)).values())
    for row in memberships:
        row["valid_to_ts_utc"] = None
    plan = importer.build_plan(seed, asset_rows, sectors, liquidity, profiles, memberships)
    assert plan.sectors == importer.ReconciliationCounts(unchanged=29)
    assert plan.liquidity == importer.ReconciliationCounts(unchanged=7)
    assert plan.profiles == importer.ReconciliationCounts(unchanged=448)
    assert plan.memberships == importer.ReconciliationCounts(unchanged=473)


def test_changed_and_stale_memberships_are_separate(seed: dict) -> None:
    asset_rows = _asset_rows(seed)
    profiles = importer.desired_profiles(seed, asset_rows)
    memberships = list(importer.desired_memberships(seed, profiles).values())
    for row in memberships:
        row["valid_to_ts_utc"] = None
    memberships[0]["confidence"] = importer.Decimal("0.01")
    memberships.append(
        {
            **memberships[0],
            "asset_symbol": "STALE",
            "sector_code": "UNCLASSIFIED",
        }
    )
    plan = importer.build_plan(seed, asset_rows, [], [], [], memberships)
    assert plan.memberships.updates == 1
    assert plan.memberships.stale == 1


class RecordingCursor:
    def __init__(self, conn: "RecordingApplyConnection") -> None:
        self.conn = conn
        self.results: list[dict] = []

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, sql: str, params=None) -> None:
        normalized = " ".join(sql.split())
        self.conn.statements.append((normalized, params))
        if normalized.startswith("SELECT * FROM asset_cluster_membership"):
            self.results = copy.deepcopy(self.conn.active_memberships)
        elif normalized.startswith("SELECT GET_LOCK"):
            self.results = [{"acquired": self.conn.lock_result}]
        elif normalized.startswith("SELECT RELEASE_LOCK"):
            self.results = [{"released": 1}]
        else:
            self.results = []

    def fetchall(self) -> list[dict]:
        return list(self.results)

    def fetchone(self) -> dict | None:
        return self.results[0] if self.results else None


class RecordingApplyConnection:
    def __init__(self, active_memberships: list[dict] | None = None, lock_result: int = 1) -> None:
        self.active_memberships = active_memberships or []
        self.lock_result = lock_result
        self.statements: list[tuple[str, object]] = []

    def cursor(self) -> RecordingCursor:
        return RecordingCursor(self)


def test_apply_plan_expires_changed_and_stale_then_inserts(seed: dict) -> None:
    asset_rows = _asset_rows(seed)
    profiles = importer.desired_profiles(seed, asset_rows)
    desired = importer.desired_memberships(seed, profiles)
    keys = sorted(desired)
    unchanged = {**desired[keys[0]], "asset_cluster_membership_id": 1, "valid_to_ts_utc": None}
    changed = {
        **desired[keys[1]],
        "asset_cluster_membership_id": 2,
        "valid_to_ts_utc": None,
        "valid_from_ts_utc": datetime(2026, 1, 1),
        "confidence": Decimal("0.01"),
    }
    stale = {
        **desired[keys[2]],
        "asset_cluster_membership_id": 3,
        "asset_symbol": "STALE",
        "sector_code": "UNCLASSIFIED",
        "valid_to_ts_utc": None,
        "valid_from_ts_utc": datetime(2026, 1, 1),
    }
    conn = RecordingApplyConnection([unchanged, changed, stale])

    importer.apply_plan(conn, seed, asset_rows)

    membership_inserts = [
        sql for sql, _ in conn.statements if sql.startswith("INSERT INTO asset_cluster_membership")
    ]
    membership_expiries = [
        sql for sql, _ in conn.statements if sql.startswith("UPDATE asset_cluster_membership")
    ]
    profile_scope_reconciliations = [
        sql for sql, _ in conn.statements if sql.startswith("UPDATE asset_taxonomy_profile")
    ]
    asset_sector_updates = [
        sql for sql, _ in conn.statements if sql.startswith("UPDATE asset SET sector")
    ]
    assert len(membership_inserts) == 472
    assert len(membership_expiries) == 2
    assert len(profile_scope_reconciliations) == 1
    assert len(asset_sector_updates) == 429


def test_apply_plan_rejects_non_monotonic_validity(seed: dict) -> None:
    asset_rows = _asset_rows(seed)
    profiles = importer.desired_profiles(seed, asset_rows)
    desired = importer.desired_memberships(seed, profiles)
    key = sorted(desired)[0]
    changed = {
        **desired[key],
        "asset_cluster_membership_id": 1,
        "valid_to_ts_utc": None,
        "confidence": Decimal("0.01"),
    }
    conn = RecordingApplyConnection([changed])
    with pytest.raises(importer.TaxonomyPreflightError, match="valid_from must be later"):
        importer.apply_plan(conn, seed, asset_rows)


def test_named_lock_fails_closed() -> None:
    with pytest.raises(importer.TaxonomyPreflightError, match="holds the DB lock"):
        importer.acquire_import_lock(RecordingApplyConnection(lock_result=0))


def test_migration_contains_separate_dimensions_and_active_uniqueness() -> None:
    sql = (
        Path(__file__).resolve().parents[1]
        / "db"
        / "migrations"
        / "20260716_sector_taxonomy_database_seed_v1.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS sector_definition" in sql
    assert "CREATE TABLE IF NOT EXISTS liquidity_market_cap_definition" in sql
    assert "CREATE TABLE IF NOT EXISTS asset_taxonomy_profile" in sql
    assert "CREATE TABLE IF NOT EXISTS asset_cluster_membership" in sql
    assert "uq_asset_cluster_membership_active" in sql
    assert "uq_asset_cluster_primary_active" in sql
    assert "uq_asset_taxonomy_profile_asset" in sql
    assert "fk_asset_cluster_membership_profile_asset" in sql
    assert "membership_weight >= 0 AND membership_weight <= 1" in sql
    assert "confidence >= 0 AND confidence <= 1" in sql


def test_sector_rotation_public_contract_uses_participation_terms() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "docs/todo/sector_rotation_engine_v1.md",
        "docs/todo/sector_rotation_dashboard_v1.md",
        "src/research/run_sector_taxonomy_import_v1.py",
        "db/migrations/20260716_sector_taxonomy_database_seed_v1.sql",
    ):
        assert "breadth" not in (root / relative).read_text(encoding="utf-8").lower()
    engine = (root / "docs/todo/sector_rotation_engine_v1.md").read_text(encoding="utf-8")
    assert "positive_participation_pct" in engine
    assert "negative_participation_pct" in engine
    assert "participation_ratio" in engine
    assert "INSUFFICIENT_PARTICIPATION" in engine


class MainConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closes += 1


def _empty_plan() -> importer.ImportPlan:
    empty = importer.ReconciliationCounts()
    return importer.ImportPlan(empty, empty, empty, empty, 0, 0, ())


def test_validate_only_never_opens_database(seed: dict) -> None:
    with patch.object(importer, "load_seed", return_value=seed), patch.object(
        importer, "get_connection", side_effect=AssertionError("DB must not open")
    ):
        assert importer.main(["--validate-only"]) == 0


def test_dry_run_rolls_back_without_apply(seed: dict) -> None:
    conn = MainConnection()
    enabled, research = _database_sets(seed)
    with patch.object(importer, "load_seed", return_value=seed), patch.object(
        importer, "get_connection", return_value=conn
    ), patch.object(importer, "fetch_present_tables", return_value=set(importer.SOURCE_TABLES)), patch.object(
        importer, "fetch_universe", return_value=(_asset_rows(seed), enabled, research)
    ), patch.object(importer, "build_plan", return_value=_empty_plan()), patch.object(
        importer, "apply_plan", side_effect=AssertionError("dry run must not apply")
    ):
        assert importer.main(["--dry-run"]) == 0
    assert conn.commits == 0
    assert conn.rollbacks == 1
    assert conn.closes == 1


def test_write_requires_migration(seed: dict) -> None:
    conn = MainConnection()
    with patch.object(importer, "load_seed", return_value=seed), patch.object(
        importer, "get_connection", return_value=conn
    ), patch.object(importer, "acquire_import_lock"), patch.object(
        importer, "release_import_lock"
    ) as release, patch.object(
        importer, "fetch_present_tables", return_value=set(importer.SOURCE_TABLES)
    ):
        assert importer.main(["--write-db"]) == importer.PRECHECK_FAILURE_EXIT_CODE
    assert conn.commits == 0
    assert conn.rollbacks == 1
    release.assert_called_once_with(conn)


def test_write_commits_once_and_uses_lock(seed: dict) -> None:
    conn = MainConnection()
    enabled, research = _database_sets(seed)
    present = set(importer.SOURCE_TABLES) | set(importer.TARGET_TABLES)
    with patch.object(importer, "load_seed", return_value=seed), patch.object(
        importer, "get_connection", return_value=conn
    ), patch.object(importer, "fetch_present_tables", return_value=present), patch.object(
        importer, "fetch_universe", return_value=(_asset_rows(seed), enabled, research)
    ), patch.object(importer, "_fetch_rows", return_value=[]), patch.object(
        importer, "build_plan", return_value=_empty_plan()
    ), patch.object(importer, "acquire_import_lock") as acquire, patch.object(
        importer, "release_import_lock"
    ) as release, patch.object(importer, "apply_plan") as apply:
        assert importer.main(["--write-db"]) == 0
    acquire.assert_called_once_with(conn)
    apply.assert_called_once()
    release.assert_called_once_with(conn)
    assert conn.commits == 1
    assert conn.rollbacks == 0


def test_write_failure_rolls_back_and_releases_lock(seed: dict) -> None:
    conn = MainConnection()
    enabled, research = _database_sets(seed)
    present = set(importer.SOURCE_TABLES) | set(importer.TARGET_TABLES)
    with patch.object(importer, "load_seed", return_value=seed), patch.object(
        importer, "get_connection", return_value=conn
    ), patch.object(importer, "fetch_present_tables", return_value=present), patch.object(
        importer, "fetch_universe", return_value=(_asset_rows(seed), enabled, research)
    ), patch.object(importer, "_fetch_rows", return_value=[]), patch.object(
        importer, "build_plan", return_value=_empty_plan()
    ), patch.object(importer, "acquire_import_lock"), patch.object(
        importer, "release_import_lock"
    ) as release, patch.object(importer, "apply_plan", side_effect=RuntimeError("boom")):
        assert importer.main(["--write-db"]) == 1
    assert conn.commits == 0
    assert conn.rollbacks == 1
    release.assert_called_once_with(conn)
