from __future__ import annotations

from pathlib import Path


PRIVATE_READ_CALLERS = (
    Path("src/account/run_account_wallet_refresh_v1.py"),
    Path("src/operations/run_broker_balance_snapshot_writer_v1.py"),
    Path("src/operations/run_broker_order_snapshot_writer_v1.py"),
    Path("src/operations/run_broker_balance_readonly_probe_v1.py"),
    Path("src/operations/run_broker_open_orders_readonly_probe_v1.py"),
)


def test_private_read_callers_use_canonical_resolver_not_default_client() -> None:
    for path in PRIVATE_READ_CALLERS:
        source = path.read_text()
        assert "resolve_private_read_bitvavo_client_from_env" in source, path
        assert "BitvavoClient(" not in source, path


def test_private_read_callers_do_not_read_global_bitvavo_credentials() -> None:
    for path in PRIVATE_READ_CALLERS:
        source = path.read_text()
        assert "os.getenv(\"BITVAVO_API_KEY" not in source, path
        assert "os.getenv(\"BITVAVO_API_SECRET" not in source, path
        assert "BITVAVO_API_KEY=" not in source, path
        assert "BITVAVO_API_SECRET=" not in source, path


def test_readonly_probe_readiness_reports_master_key_not_api_key() -> None:
    for path in (
        Path("src/operations/run_broker_balance_readonly_probe_v1.py"),
        Path("src/operations/run_broker_open_orders_readonly_probe_v1.py"),
    ):
        source = path.read_text()
        assert "MASTER_KEY_ENV_VAR" in source
        assert "BITVAVO_API_KEY" not in source
        assert "BITVAVO_API_SECRET" not in source


def test_mvp_scripts_require_explicit_account_and_master_key() -> None:
    for path in (
        Path("scripts/odroid/run_mvp_account_refresh_once.sh"),
        Path("scripts/odroid/run_mvp_readonly_pipeline_once.sh"),
    ):
        source = path.read_text()
        assert "SYNTH_MVP_ACCOUNT_CODE must be set" in source
        assert "SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY must be loaded" in source
        assert "--account-code \"${SYNTH_MVP_ACCOUNT_CODE}\"" in source
        assert "--account-code bitvavo_synth_read" not in source


def test_wallet_refresh_script_no_legacy_profile_env_source() -> None:
    source = Path("scripts/odroid/run_account_wallet_refresh_once.sh").read_text()
    assert "SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY" in source
    assert "SYNTH_WALLET_CREDENTIAL_SOURCE" not in source
    assert "profile-env" not in source


def test_provisioning_private_reads_use_explicit_client_without_global_fallback() -> None:
    validator = Path(
        "src/account_provisioning/bitvavo_credential_validator_v1.py"
    ).read_text()
    web_runner = Path("src/web/run_web_auth_service_v1.py").read_text()

    assert "BitvavoClient.for_private_read(" in validator
    assert "BitvavoClient.for_private_read(" in web_runner
    assert "os.getenv(\"BITVAVO_API_KEY" not in validator
    assert "os.getenv(\"BITVAVO_API_SECRET" not in validator
    assert "BitvavoClient(" not in web_runner

    activation = Path("src/account_provisioning/connect_bitvavo_v1.py").read_text()
    assert "resolve_private_read_bitvavo_client(" in activation
    assert "load_account_credential(" not in activation


def test_pr129_paper_worker_boundary_remains_public_and_credential_free() -> None:
    source = Path("src/execution/worker.py").read_text()
    assert "BitvavoPublicMarketDataClient" in source
    assert "src.execution.bitvavo_client" not in source
    assert "BitvavoClient" not in source
    assert "BITVAVO_API_KEY" not in source
    assert "BITVAVO_API_SECRET" not in source
    assert ".place_order(" not in source
    assert ".cancel_order(" not in source


def test_private_client_has_no_global_trade_credential_factory() -> None:
    source = Path("src/execution/bitvavo_client.py").read_text()
    assert "for_legacy_trade_execution_from_env" not in source
    assert "os.getenv(\"BITVAVO_API_KEY" not in source
    assert "os.getenv(\"BITVAVO_API_SECRET" not in source
