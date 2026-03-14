CREATE TABLE IF NOT EXISTS compute_jobs (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 job_type VARCHAR(64),
 params_json JSON,
 status VARCHAR(16) DEFAULT 'pending',
 created_ts DATETIME(6),
 started_ts DATETIME(6),
 finished_ts DATETIME(6),
 locked_by VARCHAR(64),
 last_error TEXT
);

CREATE TABLE IF NOT EXISTS compute_results (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 job_id BIGINT,
 result_json JSON,
 created_ts DATETIME(6)
);


