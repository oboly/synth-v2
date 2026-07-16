-- Migration: native_short_writer_provenance_v1
-- Boundary: market-data writer provenance only; no scope, geometry, lifecycle, or status semantic changes
-- Purpose:
--   1. Preserve independent repository, runner, invocation, execution-mode, build, and host provenance.
--   2. Link all future native SHORT writer evidence to one explicit invocation UUID.
--   3. Leave every historical row unchanged and nullable as LEGACY_UNATTRIBUTED.
-- Non-goals:
--   - no historical backfill or inferred ownership
--   - no scope promotion, removal, or seeding
--   - no scheduler, service, timer, deployment, account, broker, order, or execution changes

ALTER TABLE native_short_materializer_run_v1
    ADD COLUMN provenance_contract_version VARCHAR(40) NULL AFTER process_id,
    ADD COLUMN writer_entrypoint VARCHAR(160) NULL AFTER provenance_contract_version,
    ADD COLUMN repository_writer_owner VARCHAR(96) NULL AFTER writer_entrypoint,
    ADD COLUMN execution_mode VARCHAR(16) NULL AFTER repository_writer_owner,
    ADD COLUMN repository_commit_sha CHAR(40) NULL AFTER execution_mode,
    ADD KEY idx_native_short_materializer_run_v1_provenance (
        provenance_contract_version, execution_mode, started_at_utc
    ),
    ADD CONSTRAINT chk_native_short_materializer_run_v1_execution_mode
        CHECK (execution_mode IS NULL OR execution_mode IN ('CHAIN', 'MANUAL', 'TEST')),
    ADD CONSTRAINT chk_native_short_materializer_run_v1_provenance_shape
        CHECK (
            provenance_contract_version IS NULL
            OR (
                provenance_contract_version = 'native_short_writer_provenance_v1'
                AND writer_entrypoint IS NOT NULL
                AND repository_writer_owner = 'synth-chain-4h'
                AND execution_mode IS NOT NULL
                AND repository_commit_sha IS NOT NULL
                AND repository_commit_sha REGEXP '^[0-9a-f]{40}$'
                AND host_name IS NOT NULL
                AND process_id IS NOT NULL
                AND trigger_ref IS NOT NULL
            )
        );

ALTER TABLE native_short_map_v1
    ADD COLUMN writer_invocation_uuid CHAR(36) NULL AFTER published_generation_attempt_id,
    ADD KEY idx_native_short_map_v1_writer_invocation (writer_invocation_uuid),
    ADD CONSTRAINT fk_native_short_map_v1_writer_invocation
        FOREIGN KEY (writer_invocation_uuid)
        REFERENCES native_short_materializer_run_v1 (run_uuid);

ALTER TABLE native_short_map_generation_event_v1
    ADD COLUMN writer_invocation_uuid CHAR(36) NULL AFTER generation_attempt_id,
    ADD KEY idx_native_short_map_generation_event_v1_writer_invocation (writer_invocation_uuid),
    ADD CONSTRAINT fk_native_short_map_generation_event_v1_writer_invocation
        FOREIGN KEY (writer_invocation_uuid)
        REFERENCES native_short_materializer_run_v1 (run_uuid);

ALTER TABLE native_short_map_lifecycle_event_v1
    ADD COLUMN writer_invocation_uuid CHAR(36) NULL AFTER event_ts_utc,
    ADD KEY idx_native_short_map_lifecycle_event_v1_writer_invocation (writer_invocation_uuid),
    ADD CONSTRAINT fk_native_short_map_lifecycle_event_v1_writer_invocation
        FOREIGN KEY (writer_invocation_uuid)
        REFERENCES native_short_materializer_run_v1 (run_uuid);

ALTER TABLE native_short_map_scope_v1
    ADD COLUMN writer_invocation_uuid CHAR(36) NULL AFTER scope_reason_detail,
    ADD KEY idx_native_short_map_scope_v1_writer_invocation (writer_invocation_uuid),
    ADD CONSTRAINT fk_native_short_map_scope_v1_writer_invocation
        FOREIGN KEY (writer_invocation_uuid)
        REFERENCES native_short_materializer_run_v1 (run_uuid);

ALTER TABLE native_short_scope_support_event_v1
    ADD COLUMN writer_invocation_uuid CHAR(36) NULL AFTER event_ts_utc,
    ADD KEY idx_native_short_scope_support_event_v1_writer_invocation (writer_invocation_uuid),
    ADD CONSTRAINT fk_native_short_scope_support_event_v1_writer_invocation
        FOREIGN KEY (writer_invocation_uuid)
        REFERENCES native_short_materializer_run_v1 (run_uuid);

ALTER TABLE native_short_scope_status_v1
    ADD COLUMN writer_invocation_uuid CHAR(36) NULL AFTER latest_run_id,
    ADD KEY idx_native_short_scope_status_v1_writer_invocation (writer_invocation_uuid),
    ADD CONSTRAINT fk_native_short_scope_status_v1_writer_invocation
        FOREIGN KEY (writer_invocation_uuid)
        REFERENCES native_short_materializer_run_v1 (run_uuid);

ALTER TABLE native_short_map_level_status_v1
    ADD COLUMN writer_invocation_uuid CHAR(36) NULL AFTER map_cycle_id,
    ADD KEY idx_native_short_map_level_status_v1_writer_invocation (writer_invocation_uuid),
    ADD CONSTRAINT fk_native_short_map_level_status_v1_writer_invocation
        FOREIGN KEY (writer_invocation_uuid)
        REFERENCES native_short_materializer_run_v1 (run_uuid);
