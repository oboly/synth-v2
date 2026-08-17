import re
from pathlib import Path


MIGRATION = Path("db/migrations/20260817_executor_live_authority_v1.sql")


def migration_text() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_is_additive_created_not_applied_and_seeds_nothing() -> None:
    text = migration_text()
    assert "MIGRATION_STATE=CREATED_NOT_APPLIED" in text
    assert text.count("CREATE TABLE") == 3
    assert "CREATE TABLE executor_live_authority_grant" in text
    assert "CREATE TABLE executor_live_authority_revocation" in text
    assert "CREATE TABLE executor_kill_switch_event" in text
    assert "INSERT INTO" not in text
    assert "ALTER TABLE" not in text
    assert "manual_execution_" not in text


def test_grant_window_scope_revocation_and_kill_state_are_constrained() -> None:
    text = migration_text()
    assert "INTERVAL 7 DAY" in text
    assert "side IN ('BUY','SELL')" in text
    assert "market VARCHAR(64) NULL" in text
    assert "FOREIGN KEY (trading_account_id)" in text
    assert "UNIQUE KEY uq_elar_one_per_grant" in text
    assert "state IN ('ENGAGED','DISENGAGED')" in text
    assert "ORDER" not in text.upper()


def test_all_three_histories_reject_update_and_delete() -> None:
    text = migration_text()
    for prefix in ("elag", "elar", "ekse"):
        assert f"CREATE TRIGGER trg_{prefix}_no_update" in text
        assert f"CREATE TRIGGER trg_{prefix}_no_delete" in text


def test_mariadb_identifiers_fit_64_character_limit() -> None:
    identifiers = re.findall(
        r"(?:CONSTRAINT|TRIGGER|KEY)\s+([A-Za-z0-9_]+)", migration_text()
    )
    assert identifiers
    assert all(len(identifier) <= 64 for identifier in identifiers)


def test_authority_modules_do_not_import_forbidden_layers() -> None:
    text = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "src/executor/execution_live_authority_v1.py",
            "src/executor/execution_kill_switch_v1.py",
        )
    )
    forbidden = (
        "src.selection_engine",
        "src.selection",
        "src.entry_policy",
        "src.exit_policy",
        "src.decision_gate",
        "src.execution_planner",
        "src.manual_execution",
        "src.executor.manual_execution_",
    )
    assert not any(item in text for item in forbidden)
