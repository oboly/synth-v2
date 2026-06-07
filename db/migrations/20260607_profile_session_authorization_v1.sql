-- Migration: profile_session_authorization_v1
-- Adds idle session expiry and login rate-limiting table.
-- Idempotent: safe to re-run.
--
-- Rollback notes:
--   To undo idle expiry column:
--     ALTER TABLE web_session DROP COLUMN idle_expires_ts_utc;
--   To undo login_attempt table:
--     DROP TABLE IF EXISTS login_attempt;
--   These rollbacks discard session idle tracking and rate-limit history only.
--   Registration, verification, session, and profile data are unaffected.
--
-- Prerequisite: 20260605_website_registration_foundation_v1.sql must have been applied.

-- Optional: invalidate pre-migration sessions that lack idle expiry (fail-closed).
-- Pre-migration sessions have idle_expires_ts_utc = NULL and will only expire at
-- their absolute expires_ts_utc (up to 14 days after session creation).
-- Run this to force re-login for all pre-migration sessions immediately after migration:
--
--   UPDATE web_session
--   SET invalidated_ts_utc = UTC_TIMESTAMP()
--   WHERE idle_expires_ts_utc IS NULL
--     AND invalidated_ts_utc IS NULL;

-- Retention: login_attempt rows accumulate over time.
-- Recommended periodic cleanup (e.g. weekly cron or manual):
--
--   DELETE FROM login_attempt
--   WHERE attempted_ts_utc < DATE_SUB(UTC_TIMESTAMP(), INTERVAL 30 DAY);

-- Add idle expiry column to web_session.
-- Existing rows get NULL (treated as: no idle expiry, absolute expiry still applies).
ALTER TABLE web_session
    ADD COLUMN IF NOT EXISTS idle_expires_ts_utc DATETIME NULL
    AFTER expires_ts_utc;

-- Login attempt tracking for per-IP rate limiting.
-- ip_hash is SHA-256 of the client IP. Raw IPs are never stored.
CREATE TABLE IF NOT EXISTS login_attempt (
    login_attempt_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    ip_hash          CHAR(64)         NOT NULL,
    attempted_ts_utc DATETIME         NOT NULL,
    success          TINYINT(1)       NOT NULL,
    PRIMARY KEY (login_attempt_id),
    KEY ix_login_attempt_ip_ts (ip_hash, attempted_ts_utc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
