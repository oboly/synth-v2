from pathlib import Path
import re


MIGRATION_PATH = Path("db/migrations/20260814_automatic_exit_runtime_contract_v1.sql")
PRODUCTION_ASSET_ID_SQL_TYPE = "INT(11)"
ASSET_FK_TABLES = (
    "automatic_exit_profile_v1",
    "automatic_exit_evaluation_audit_v1",
)


def _create_table_body(sql: str, table_name: str) -> str:
    pattern = re.compile(
        rf"CREATE TABLE IF NOT EXISTS {re.escape(table_name)} \\((.*?)\\) ENGINE=InnoDB",
        re.DOTALL,
    )
    match = pattern.search(sql)
    assert match is not None, f"missing CREATE TABLE for {table_name}"
    return match.group(1)


def _column_type(table_body: str, column_name: str) -> str:
    pattern = re.compile(
        rf"^\\s*{re.escape(column_name)}\\s+([^,\\n]+)",
        re.MULTILINE,
    )
    match = pattern.search(table_body)
    assert match is not None, f"missing column {column_name}"
    definition = match.group(1).strip()
    return definition.split(" NOT NULL", 1)[0].strip()


def test_automatic_exit_asset_foreign_keys_match_production_asset_id_type() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    for table_name in ASSET_FK_TABLES:
        body = _create_table_body(sql, table_name)

        assert _column_type(body, "asset_id") == PRODUCTION_ASSET_ID_SQL_TYPE
        assert (
            "FOREIGN KEY (asset_id) REFERENCES asset (asset_id)" in body
        ), f"missing asset FK in {table_name}"


def test_automatic_exit_asset_foreign_keys_are_not_unsigned_bigint() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    for table_name in ASSET_FK_TABLES:
        body = _create_table_body(sql, table_name)
        assert "asset_id BIGINT UNSIGNED" not in body
