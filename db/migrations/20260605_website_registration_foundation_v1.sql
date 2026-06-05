CREATE TABLE IF NOT EXISTS app_user (
    app_user_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    email_normalized VARCHAR(320) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    status VARCHAR(64) NOT NULL,
    created_ts_utc DATETIME NOT NULL,
    verified_ts_utc DATETIME NULL,
    last_login_ts_utc DATETIME NULL,
    PRIMARY KEY (app_user_id),
    UNIQUE KEY uq_app_user_email_normalized (email_normalized)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS app_profile (
    app_profile_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    profile_code VARCHAR(63) NOT NULL,
    display_timezone VARCHAR(64) NOT NULL,
    onboarding_state VARCHAR(64) NOT NULL,
    created_ts_utc DATETIME NOT NULL,
    activated_ts_utc DATETIME NULL,
    PRIMARY KEY (app_profile_id),
    UNIQUE KEY uq_app_profile_profile_code (profile_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS app_user_profile_access (
    app_user_profile_access_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    app_user_id BIGINT UNSIGNED NOT NULL,
    app_profile_id BIGINT UNSIGNED NOT NULL,
    access_role VARCHAR(32) NOT NULL,
    created_ts_utc DATETIME NOT NULL,
    PRIMARY KEY (app_user_profile_access_id),
    UNIQUE KEY uq_app_user_profile_access (app_user_id, app_profile_id),
    CONSTRAINT fk_app_user_profile_access_user
        FOREIGN KEY (app_user_id) REFERENCES app_user (app_user_id),
    CONSTRAINT fk_app_user_profile_access_profile
        FOREIGN KEY (app_profile_id) REFERENCES app_profile (app_profile_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS email_verification_token (
    email_verification_token_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    app_user_id BIGINT UNSIGNED NOT NULL,
    app_profile_id BIGINT UNSIGNED NOT NULL,
    token_hash CHAR(64) NOT NULL,
    created_ts_utc DATETIME NOT NULL,
    expires_ts_utc DATETIME NOT NULL,
    used_ts_utc DATETIME NULL,
    PRIMARY KEY (email_verification_token_id),
    UNIQUE KEY uq_email_verification_token_hash (token_hash),
    KEY ix_email_verification_token_user_profile (app_user_id, app_profile_id),
    CONSTRAINT fk_email_verification_token_user
        FOREIGN KEY (app_user_id) REFERENCES app_user (app_user_id),
    CONSTRAINT fk_email_verification_token_profile
        FOREIGN KEY (app_profile_id) REFERENCES app_profile (app_profile_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS web_session (
    web_session_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    app_user_id BIGINT UNSIGNED NOT NULL,
    app_profile_id BIGINT UNSIGNED NOT NULL,
    session_hash CHAR(64) NOT NULL,
    created_ts_utc DATETIME NOT NULL,
    expires_ts_utc DATETIME NOT NULL,
    rotated_from_session_id BIGINT UNSIGNED NULL,
    invalidated_ts_utc DATETIME NULL,
    last_seen_ts_utc DATETIME NULL,
    PRIMARY KEY (web_session_id),
    UNIQUE KEY uq_web_session_hash (session_hash),
    KEY ix_web_session_user_profile (app_user_id, app_profile_id),
    CONSTRAINT fk_web_session_user
        FOREIGN KEY (app_user_id) REFERENCES app_user (app_user_id),
    CONSTRAINT fk_web_session_profile
        FOREIGN KEY (app_profile_id) REFERENCES app_profile (app_profile_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
