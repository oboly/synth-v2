from pathlib import Path


MIGRATION = Path("db/migrations/20260819_automatic_buy_runtime_v1.sql")


def test_automatic_buy_runtime_asset_fk_matches_production_asset_pk_type() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert sql.count("asset_id INT NOT NULL") == 2
    assert "asset_id BIGINT UNSIGNED NOT NULL" not in sql

    assert (
        "FOREIGN KEY (asset_id) REFERENCES asset (asset_id)"
        in sql
    )
