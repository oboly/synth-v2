-- Dedicated least-privilege identity for scripts/run_chain_4h.sh.
--
-- DBA execution is a separate, explicitly authorized operation. Before
-- sourcing this file, the DBA must set @synth_chain_4h_writer_password in the
-- same MariaDB session using password material obtained through an approved
-- secret channel. This file contains no password and does not read a file.
--
-- A missing or empty password makes PREPARE fail before CREATE USER executes.

SET @synth_chain_4h_writer_password =
    NULLIF(@synth_chain_4h_writer_password, '');

SET @synth_chain_4h_writer_create_sql = CONCAT(
    'CREATE USER IF NOT EXISTS ',
    '''synth_chain_4h_writer''@''192.168.1.%'' IDENTIFIED BY ',
    QUOTE(@synth_chain_4h_writer_password)
);
PREPARE synth_chain_4h_writer_create_stmt
    FROM @synth_chain_4h_writer_create_sql;
EXECUTE synth_chain_4h_writer_create_stmt;
DEALLOCATE PREPARE synth_chain_4h_writer_create_stmt;

SET @synth_chain_4h_writer_alter_sql = CONCAT(
    'ALTER USER ',
    '''synth_chain_4h_writer''@''192.168.1.%'' IDENTIFIED BY ',
    QUOTE(@synth_chain_4h_writer_password)
);
PREPARE synth_chain_4h_writer_alter_stmt
    FROM @synth_chain_4h_writer_alter_sql;
EXECUTE synth_chain_4h_writer_alter_stmt;
DEALLOCATE PREPARE synth_chain_4h_writer_alter_stmt;

-- Reset only the dedicated identity. The existing broad synth identity is
-- intentionally untouched. Re-granting from an empty authority set makes the
-- artifact deterministic and idempotent if the dedicated identity drifted.
REVOKE ALL PRIVILEGES, GRANT OPTION
    FROM 'synth_chain_4h_writer'@'192.168.1.%';

GRANT SELECT, INSERT, UPDATE
    ON `synth`.`advice_state`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT
    ON `synth`.`aplus_table1_report`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT
    ON `synth`.`aplus_table1_row`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT
    ON `synth`.`asset`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT, UPDATE
    ON `synth`.`asset_interval_quality`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT
    ON `synth`.`canonical_fib_zone_map_publication_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT
    ON `synth`.`canonical_fib_zone_map_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT
    ON `synth`.`canonical_fib_zone_map_latest_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT, UPDATE, DELETE
    ON `synth`.`execution_zone_context`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT, UPDATE
    ON `synth`.`feat_candle`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT, UPDATE
    ON `synth`.`fib_observation_v2`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT
    ON `synth`.`market_price_snapshot`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT
    ON `synth`.`native_short_map_generation_event_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT, DELETE
    ON `synth`.`native_short_map_level_status_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT
    ON `synth`.`native_short_map_lifecycle_event_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT
    ON `synth`.`native_short_map_scope_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT
    ON `synth`.`native_short_map_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT, UPDATE
    ON `synth`.`native_short_materializer_run_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT
    ON `synth`.`native_short_scope_cadence_config_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT
    ON `synth`.`native_short_scope_observation_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT, UPDATE
    ON `synth`.`native_short_scope_status_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT
    ON `synth`.`native_short_scope_support_event_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT
    ON `synth`.`obs_market_candle`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT, UPDATE
    ON `synth`.`paper_advice_observation`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT, UPDATE
    ON `synth`.`ranking_state`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT, UPDATE
    ON `synth`.`selection_state`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT, UPDATE
    ON `synth`.`signal_engine_state`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT INSERT
    ON `synth`.`strategy_runtime_component`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT INSERT
    ON `synth`.`strategy_runtime_snapshot`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT, UPDATE
    ON `synth`.`trade_setup_filter_observation`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT, UPDATE
    ON `synth`.`trade_setup_policy_preview_observation`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT
    ON `synth`.`v_asset_interval_quality_v3`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT
    ON `synth`.`venue_market`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT
    ON `synth`.`vw_paper_advice_execution_zone_context_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT, UPDATE
    ON `synth`.`zone_observation_v2`
    TO 'synth_chain_4h_writer'@'192.168.1.%';

SET @synth_chain_4h_writer_password = NULL;
SET @synth_chain_4h_writer_create_sql = NULL;
SET @synth_chain_4h_writer_alter_sql = NULL;
