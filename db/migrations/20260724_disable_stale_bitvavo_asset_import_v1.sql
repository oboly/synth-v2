-- Disable eight stale enabled rows from the historical full Bitvavo asset import.
--
-- Scope:
-- - update only asset.is_enabled for the exact canonical symbols below;
-- - preserve asset rows, venue metadata, and all historical observations;
-- - no aliases, symbol rewrites, candle-writer exclusions, or runtime changes.

DELIMITER $$

DROP PROCEDURE IF EXISTS migrate_disable_stale_bitvavo_asset_import_v1$$
CREATE PROCEDURE migrate_disable_stale_bitvavo_asset_import_v1()
BEGIN
    DECLARE target_count INT DEFAULT 0;
    DECLARE remaining_enabled_count INT DEFAULT 0;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT COUNT(*) INTO target_count
    FROM asset
    WHERE BINARY symbol IN (
        'CARDS',
        'COS',
        'D',
        'IP',
        'MBOX',
        'NFP',
        'QTUM',
        'XION'
    );

    IF target_count <> 8 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'STALE_BITVAVO_ASSET_IMPORT_EXACT_TARGETS_REQUIRED';
    END IF;

    UPDATE asset
    SET is_enabled = 0
    WHERE BINARY symbol IN (
        'CARDS',
        'COS',
        'D',
        'IP',
        'MBOX',
        'NFP',
        'QTUM',
        'XION'
    )
      AND is_enabled <> 0;

    SELECT COUNT(*) INTO remaining_enabled_count
    FROM asset
    WHERE BINARY symbol IN (
        'CARDS',
        'COS',
        'D',
        'IP',
        'MBOX',
        'NFP',
        'QTUM',
        'XION'
    )
      AND is_enabled <> 0;

    IF remaining_enabled_count <> 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'STALE_BITVAVO_ASSET_IMPORT_DISABLE_FAILED';
    END IF;

    COMMIT;
END$$

CALL migrate_disable_stale_bitvavo_asset_import_v1()$$
DROP PROCEDURE migrate_disable_stale_bitvavo_asset_import_v1$$

DELIMITER ;
