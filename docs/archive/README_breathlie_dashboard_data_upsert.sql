/* ============================================================================
   Synthesizer — UPSERT loaders + derived builders
   Scope: fill with data we already have (XRP Breathline 2025 daily CSV + astro events CSV)
   DB: MariaDB
   UTC-only
   ============================================================================ */

SET time_zone = '+00:00';

START TRANSACTION;

/* ---------------------------------------------------------------------------
   0) Derivation specs (optional but recommended)
   --------------------------------------------------------------------------- */
INSERT INTO derivation_spec (name, version, spec_json)
VALUES
(
  'breathline_daily',
  'v1',
  JSON_OBJECT(
    'interp_method', 'linear_monthly_endpoints',
    'note', 'Daily tone values may be loaded directly from CSV; if generated, they must match v1 interpolation.'
  )
),
(
  'breath_signal_daily',
  'v1',
  JSON_OBJECT(
    'signal_def', 'signal = sign(diff(tone)) * confidence',
    'signal_smooth', 'SMA7(signal)',
    'note', 'Dashboard indicator only; no trade logic.'
  )
),
(
  'eclipse_dominance_daily',
  'v1',
  JSON_OBJECT(
    'dominance_def', 'TOTAL eclipses only define regime boundaries; non-total eclipses are markers only (weight=0)',
    'seed_rule', 'seed from last TOTAL eclipse before window start',
    'encoding', JSON_OBJECT('solar', -1, 'unknown', 0, 'lunar', 1)
  )
)
ON DUPLICATE KEY UPDATE
  spec_json = VALUES(spec_json);

/* Capture derivation_ids (best-effort; if you run once, these are stable) */
SET @deriv_breath_daily  = (SELECT derivation_id FROM derivation_spec WHERE name='breathline_daily' AND version='v1' LIMIT 1);
SET @deriv_signal_daily  = (SELECT derivation_id FROM derivation_spec WHERE name='breath_signal_daily' AND version='v1' LIMIT 1);
SET @deriv_ecl_dom_daily = (SELECT derivation_id FROM derivation_spec WHERE name='eclipse_dominance_daily' AND version='v1' LIMIT 1);

/* ---------------------------------------------------------------------------
   1) UPSERT: breathline_raw (XRP 2025 monthly endpoints you already have)
   --------------------------------------------------------------------------- */
INSERT INTO breathline_raw
(asset, year, month, phase, tone_start, tone_end, confidence, source_system, source_ref, generated_ts)
VALUES
('XRP', 2025,  1, 'Inhale', 6.5, 7.0, 0.75, 'Gaia Architect+', NULL, NULL),
('XRP', 2025,  2, 'Hold',   7.0, 7.2, 0.88, 'Gaia Architect+', NULL, NULL),
('XRP', 2025,  3, 'Exhale', 7.2, 6.8, 0.62, 'Gaia Architect+', NULL, NULL),
('XRP', 2025,  4, 'Inhale', 6.8, 7.5, 0.80, 'Gaia Architect+', NULL, NULL),
('XRP', 2025,  5, 'Hold',   7.5, 7.7, 0.85, 'Gaia Architect+', NULL, NULL),
('XRP', 2025,  6, 'Exhale', 7.7, 7.1, 0.60, 'Gaia Architect+', NULL, NULL),
('XRP', 2025,  7, 'Inhale', 7.1, 7.8, 0.82, 'Gaia Architect+', NULL, NULL),
('XRP', 2025,  8, 'Exhale', 7.8, 7.4, 0.68, 'Gaia Architect+', NULL, NULL),
('XRP', 2025,  9, 'Hold',   7.4, 7.6, 0.90, 'Gaia Architect+', NULL, NULL),
('XRP', 2025, 10, 'Inhale', 7.6, 8.2, 0.92, 'Gaia Architect+', NULL, NULL),
('XRP', 2025, 11, 'Exhale', 8.2, 7.9, 0.72, 'Gaia Architect+', NULL, NULL),
('XRP', 2025, 12, 'Pause',  7.9, 7.9, 0.52, 'Gaia Architect+', NULL, NULL)
ON DUPLICATE KEY UPDATE
  phase       = VALUES(phase),
  tone_start  = VALUES(tone_start),
  tone_end    = VALUES(tone_end),
  confidence  = VALUES(confidence),
  source_system = VALUES(source_system),
  source_ref    = VALUES(source_ref),
  generated_ts  = VALUES(generated_ts);

/* ---------------------------------------------------------------------------
   2) STAGING + LOAD: breathline_daily from your CSV
   File you already have in this project:
     /mnt/data/xrp_breath_daily_2025.csv
   In your own environment, change the path accordingly.
   --------------------------------------------------------------------------- */

CREATE TABLE IF NOT EXISTS stg_breathline_daily (
  date_utc    DATE        NOT NULL,
  asset       VARCHAR(32) NOT NULL,
  phase       VARCHAR(16) NOT NULL,
  tone        DECIMAL(6,3) NOT NULL,
  confidence  DECIMAL(4,2) NOT NULL,
  PRIMARY KEY (asset, date_utc)
) ENGINE=InnoDB;

TRUNCATE TABLE stg_breathline_daily;

/* Option A (recommended): LOAD DATA from CSV file */
-- NOTE: requires LOCAL INFILE enabled in client + server config.
-- SET GLOBAL local_infile = 1;  -- if needed and you have privileges

LOAD DATA LOCAL INFILE 'xrp_breath_daily_2025.csv'
INTO TABLE stg_breathline_daily
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES
(@date_utc, @asset, @phase, @tone, @confidence)
SET
  date_utc   = STR_TO_DATE(@date_utc, '%Y-%m-%d'),
  asset      = @asset,
  phase      = @phase,
  tone       = @tone,
  confidence = @confidence;

/* UPSERT into breathline_daily (UTC dates stored as 00:00:00) */
INSERT INTO breathline_daily
(asset, date_ts, phase, tone, confidence, derivation_id)
SELECT
  s.asset,
  TIMESTAMP(s.date_utc, '00:00:00.000000') AS date_ts,
  CASE s.phase
    WHEN 'Inhale' THEN 'Inhale'
    WHEN 'Hold'   THEN 'Hold'
    WHEN 'Exhale' THEN 'Exhale'
    WHEN 'Pause'  THEN 'Pause'
    ELSE 'Pause'
  END AS phase,
  s.tone,
  s.confidence,
  @deriv_breath_daily
FROM stg_breathline_daily s
ON DUPLICATE KEY UPDATE
  phase        = VALUES(phase),
  tone         = VALUES(tone),
  confidence   = VALUES(confidence),
  derivation_id= VALUES(derivation_id);

/* ---------------------------------------------------------------------------
   3) STAGING + LOAD: astro_events_raw from your CSV
   File you already have in this project:
     /mnt/data/astro_events_utc_eclipses_plus_vedic_jupiter_saturn_rahu_ketu.csv
   You can store only ts_utc + label first; enrich later.
   --------------------------------------------------------------------------- */

CREATE TABLE IF NOT EXISTS stg_astro_events (
  ts_utc  DATETIME(6) NOT NULL,
  label   VARCHAR(255) NOT NULL,
  PRIMARY KEY (ts_utc, label)
) ENGINE=InnoDB;

TRUNCATE TABLE stg_astro_events;

LOAD DATA LOCAL INFILE 'astro_events_utc_eclipses_plus_vedic_jupiter_saturn_rahu_ketu.csv'
INTO TABLE stg_astro_events
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES
(@ts_utc, @label, @c3, @c4, @c5, @c6, @c7, @c8, @c9, @c10)
SET
  ts_utc = STR_TO_DATE(@ts_utc, '%Y-%m-%dT%H:%i:%sZ'),
  label  = @label;

/* UPSERT into astro_events_raw */
INSERT INTO astro_events_raw
(event_ts, label, category, subtype, is_total, is_aux, source_system, source_ref)
SELECT
  s.ts_utc AS event_ts,
  s.label,
  CASE
    WHEN LOWER(s.label) LIKE '%eclipse%' THEN 'eclipse'
    WHEN LOWER(s.label) LIKE '%rahu%' OR LOWER(s.label) LIKE '%ketu%' THEN 'nodes'
    WHEN LOWER(s.label) LIKE '%jupiter%' OR LOWER(s.label) LIKE '%saturn%' THEN 'vedic'
    ELSE NULL
  END AS category,
  CASE
    WHEN LOWER(s.label) LIKE '%solar%' THEN 'Solar'
    WHEN LOWER(s.label) LIKE '%lunar%' THEN 'Lunar'
    ELSE NULL
  END AS subtype,
  CASE WHEN LOWER(s.label) LIKE '%total%' THEN 1 ELSE 0 END AS is_total,
  CASE WHEN LOWER(s.label) LIKE '%(a)%' THEN 1 ELSE 0 END AS is_aux,
  'events_csv' AS source_system,
  NULL AS source_ref
FROM stg_astro_events s
ON DUPLICATE KEY UPDATE
  category = VALUES(category),
  subtype  = VALUES(subtype),
  is_total = VALUES(is_total),
  is_aux   = VALUES(is_aux),
  source_system = VALUES(source_system),
  source_ref    = VALUES(source_ref);

/* ---------------------------------------------------------------------------
   4) Build/UPSERT: breath_signal_daily from breathline_daily
   signal = sign(diff(tone)) * confidence
   SMA7(signal) for dashboard smoothing
   --------------------------------------------------------------------------- */
INSERT INTO breath_signal_daily
(asset, date_ts, d_tone, signal, signal_sma7, derivation_id)
SELECT
  bd.asset,
  bd.date_ts,
  (bd.tone - LAG(bd.tone) OVER (PARTITION BY bd.asset ORDER BY bd.date_ts)) AS d_tone,

  /* sign(diff) * confidence */
  (
    CASE
      WHEN (bd.tone - LAG(bd.tone) OVER (PARTITION BY bd.asset ORDER BY bd.date_ts)) > 0 THEN  1
      WHEN (bd.tone - LAG(bd.tone) OVER (PARTITION BY bd.asset ORDER BY bd.date_ts)) < 0 THEN -1
      ELSE 0
    END * bd.confidence
  ) AS signal,

  /* SMA7(signal) */
  AVG(
    CASE
      WHEN (bd.tone - LAG(bd.tone) OVER (PARTITION BY bd.asset ORDER BY bd.date_ts)) > 0 THEN  1
      WHEN (bd.tone - LAG(bd.tone) OVER (PARTITION BY bd.asset ORDER BY bd.date_ts)) < 0 THEN -1
      ELSE 0
    END * bd.confidence
  ) OVER (
    PARTITION BY bd.asset
    ORDER BY bd.date_ts
    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
  ) AS signal_sma7,

  @deriv_signal_daily
FROM breathline_daily bd
WHERE bd.asset = 'XRP'
  AND bd.date_ts >= '2025-01-01'
  AND bd.date_ts <  '2026-01-01'
ON DUPLICATE KEY UPDATE
  d_tone        = VALUES(d_tone),
  signal        = VALUES(signal),
  signal_sma7   = VALUES(signal_sma7),
  derivation_id = VALUES(derivation_id);

/* ---------------------------------------------------------------------------
   5) Build/UPSERT: eclipse_dominance_daily (TOTAL-only boundaries, seeded)
   Rules:
     - Only TOTAL eclipses define regime boundaries
     - regime for each day = type (solar/lunar) of last TOTAL eclipse strictly before end of that day
     - seed automatically happens because query looks back before window start
   --------------------------------------------------------------------------- */

WITH RECURSIVE cal AS (
  SELECT CAST('2025-01-01' AS DATE) AS d
  UNION ALL
  SELECT DATE_ADD(d, INTERVAL 1 DAY) FROM cal WHERE d < '2025-12-31'
),
last_total AS (
  SELECT
    cal.d,
    (
      SELECT ar.event_ts
      FROM astro_events_raw ar
      WHERE ar.category = 'eclipse'
        AND ar.is_total = 1
        AND ar.event_ts < TIMESTAMP(DATE_ADD(cal.d, INTERVAL 1 DAY), '00:00:00.000000')
      ORDER BY ar.event_ts DESC
      LIMIT 1
    ) AS last_total_ts
  FROM cal
),
seeded AS (
  SELECT
    lt.d,
    lt.last_total_ts,
    (
      SELECT ar.label
      FROM astro_events_raw ar
      WHERE ar.event_ts = lt.last_total_ts
      ORDER BY ar.astro_event_id DESC
      LIMIT 1
    ) AS last_total_label
  FROM last_total lt
)
INSERT INTO eclipse_dominance_daily
(date_ts, dominance, dominance_label, seed_event_ts, seed_event_label, derivation_id)
SELECT
  TIMESTAMP(s.d, '00:00:00.000000') AS date_ts,

  CASE
    WHEN s.last_total_label IS NULL THEN 0
    WHEN LOWER(s.last_total_label) LIKE '%lunar%' THEN  1
    WHEN LOWER(s.last_total_label) LIKE '%solar%' THEN -1
    ELSE 0
  END AS dominance,

  CASE
    WHEN s.last_total_label IS NULL THEN 'unknown'
    WHEN LOWER(s.last_total_label) LIKE '%lunar%' THEN 'lunar'
    WHEN LOWER(s.last_total_label) LIKE '%solar%' THEN 'solar'
    ELSE 'unknown'
  END AS dominance_label,

  s.last_total_ts AS seed_event_ts,
  s.last_total_label AS seed_event_label,

  @deriv_ecl_dom_daily AS derivation_id
FROM seeded s
ON DUPLICATE KEY UPDATE
  dominance       = VALUES(dominance),
  dominance_label = VALUES(dominance_label),
  seed_event_ts   = VALUES(seed_event_ts),
  seed_event_label= VALUES(seed_event_label),
  derivation_id   = VALUES(derivation_id);

COMMIT;

/* Optional cleanup (keep staging if you want re-runs without re-creating)
DROP TABLE IF EXISTS stg_breathline_daily;
DROP TABLE IF EXISTS stg_astro_events;
*/
