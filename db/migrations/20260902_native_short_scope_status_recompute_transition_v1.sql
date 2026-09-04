-- Issue #681 Amendment 2: additive recompute-transition evidence column for
-- native_short_scope_status_v1.
--
-- Purpose: a scope whose selected map is currently terminal (MAP_COMPLETED /
-- MAP_INVALIDATED / MAP_EXPIRED) has, until now, had no persisted evidence
-- distinguishing a healthy bounded recompute wait (the materializer already
-- attempted recompute this cadence cycle and found current market structure
-- insufficient for a fresh map) from an overdue/stuck one (no recent
-- materializer attempt exists at all). Both cases previously projected as an
-- identical `actionability_state=TERMINAL_MAP` row with no way to tell them
-- apart, which is the root cause traced for Issue #681.
--
-- This migration only adds one nullable, checked VARCHAR column plus its
-- index to the existing rebuildable native_short_scope_status_v1 projection
-- table. It does not alter any other table, does not change
-- `scope_status_code` or `actionability_state` precedence/values, does not
-- touch `native_short_map_level_status_v1` (which gates on the existing
-- `actionability_state=TERMINAL_MAP` value, unchanged by this migration),
-- and performs no data manipulation: existing rows keep
-- `recompute_transition_state=NULL` until the next projection rebuild
-- repopulates them deterministically from already-persisted facts.
--
-- Safety markers:
-- broker_private_calls=0
-- broker_writes=0
-- order_submission=0
-- live_orders=0
-- decision_gate=none
-- execution_planner=none
-- executor=none

ALTER TABLE native_short_scope_status_v1
    ADD COLUMN recompute_transition_state VARCHAR(32) NULL
        COMMENT 'Issue #681 Amendment 2: NOT_APPLICABLE | WAITING_FOR_NEW_STRUCTURE | RECOMPUTE_OVERDUE'
        AFTER rebuilt_at_utc;

ALTER TABLE native_short_scope_status_v1
    ADD CONSTRAINT chk_native_short_scope_status_v1_recompute_transition
        CHECK (
            recompute_transition_state IS NULL
            OR recompute_transition_state IN (
                'NOT_APPLICABLE',
                'WAITING_FOR_NEW_STRUCTURE',
                'RECOMPUTE_OVERDUE'
            )
        );

CREATE INDEX idx_native_short_scope_status_v1_recompute_transition
    ON native_short_scope_status_v1 (recompute_transition_state);
