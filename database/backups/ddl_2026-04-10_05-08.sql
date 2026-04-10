/*M!999999\- enable the sandbox mode */ 
-- MariaDB dump 10.19  Distrib 10.11.14-MariaDB, for debian-linux-gnu (x86_64)
--
-- Host: 192.168.1.196    Database: synth
-- ------------------------------------------------------
-- Server version	10.11.14-MariaDB-0ubuntu0.24.04.1

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `advice_state`
--

DROP TABLE IF EXISTS `advice_state`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `advice_state` (
  `advice_state_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `venue` varchar(32) NOT NULL DEFAULT 'bitvavo',
  `interval_code` varchar(16) NOT NULL,
  `asof_ts_utc` datetime(6) NOT NULL,
  `regime_label` varchar(64) DEFAULT NULL,
  `time_horizon_hint` varchar(32) DEFAULT NULL,
  `advice_state` varchar(32) DEFAULT NULL,
  `regime_fit_score` decimal(10,6) DEFAULT NULL,
  `opportunity_score` decimal(10,6) DEFAULT NULL,
  `risk_score` decimal(10,6) DEFAULT NULL,
  `priority_rank` int(11) DEFAULT NULL,
  `summary_text` varchar(512) DEFAULT NULL,
  `engine_name` varchar(64) DEFAULT 'advice_engine',
  `engine_version` varchar(16) DEFAULT '1.0',
  `created_ts_utc` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  PRIMARY KEY (`advice_state_id`),
  UNIQUE KEY `uq_advice_state` (`asset_id`,`venue`,`interval_code`,`asof_ts_utc`),
  KEY `ix_advice_lookup` (`asset_id`,`interval_code`,`asof_ts_utc`),
  KEY `ix_advice_priority` (`regime_label`,`advice_state`,`opportunity_score`),
  CONSTRAINT `fk_advice_state_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB AUTO_INCREMENT=2653 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `aplus_asset_signal`
--

DROP TABLE IF EXISTS `aplus_asset_signal`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `aplus_asset_signal` (
  `aplus_signal_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `aplus_run_id` bigint(20) unsigned NOT NULL,
  `asset_code` varchar(32) NOT NULL,
  `created_ts` datetime(6) NOT NULL,
  `horizon_label` varchar(64) DEFAULT NULL,
  `horizon_end_ts` datetime(6) DEFAULT NULL,
  `phase_label` varchar(32) DEFAULT NULL,
  `direction_label` varchar(16) DEFAULT NULL,
  `magnitude_label` varchar(32) DEFAULT NULL,
  `confidence_label` varchar(32) DEFAULT NULL,
  `confidence_score` decimal(5,2) DEFAULT NULL,
  `target_price` decimal(20,8) DEFAULT NULL,
  `target_currency` varchar(8) DEFAULT 'EUR',
  `raw_excerpt` text DEFAULT NULL,
  `notes` text DEFAULT NULL,
  PRIMARY KEY (`aplus_signal_id`),
  KEY `fk_aplus_asset_signal_run` (`aplus_run_id`),
  KEY `ix_aplus_asset_signal_asset_created` (`asset_code`,`created_ts`),
  KEY `ix_aplus_asset_signal_phase` (`phase_label`),
  KEY `ix_aplus_asset_signal_horizon_end_ts` (`horizon_end_ts`),
  CONSTRAINT `fk_aplus_asset_signal_run` FOREIGN KEY (`aplus_run_id`) REFERENCES `aplus_run` (`aplus_run_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `aplus_factor`
--

DROP TABLE IF EXISTS `aplus_factor`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `aplus_factor` (
  `aplus_factor_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `aplus_signal_id` bigint(20) unsigned NOT NULL,
  `factor_name` varchar(64) NOT NULL,
  `factor_value_text` varchar(255) DEFAULT NULL,
  `factor_value_num` decimal(20,8) DEFAULT NULL,
  `factor_unit` varchar(32) DEFAULT NULL,
  `notes` text DEFAULT NULL,
  PRIMARY KEY (`aplus_factor_id`),
  KEY `ix_aplus_factor_signal` (`aplus_signal_id`),
  KEY `ix_aplus_factor_name` (`factor_name`),
  CONSTRAINT `fk_aplus_factor_signal` FOREIGN KEY (`aplus_signal_id`) REFERENCES `aplus_asset_signal` (`aplus_signal_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `aplus_raw_text`
--

DROP TABLE IF EXISTS `aplus_raw_text`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `aplus_raw_text` (
  `aplus_raw_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `aplus_run_id` bigint(20) unsigned NOT NULL,
  `body_text` longtext NOT NULL,
  `body_hash_sha256` char(64) NOT NULL,
  PRIMARY KEY (`aplus_raw_id`),
  UNIQUE KEY `uq_aplus_raw_text_hash` (`body_hash_sha256`),
  KEY `fk_aplus_raw_text_run` (`aplus_run_id`),
  CONSTRAINT `fk_aplus_raw_text_run` FOREIGN KEY (`aplus_run_id`) REFERENCES `aplus_run` (`aplus_run_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `aplus_run`
--

DROP TABLE IF EXISTS `aplus_run`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `aplus_run` (
  `aplus_run_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `created_ts` datetime(6) NOT NULL,
  `source_name` varchar(64) NOT NULL,
  `source_session_ref` varchar(128) DEFAULT NULL,
  `model_variant` varchar(64) DEFAULT NULL,
  `prompt_label` varchar(128) DEFAULT NULL,
  `notes` text DEFAULT NULL,
  PRIMARY KEY (`aplus_run_id`),
  KEY `ix_aplus_run_created_ts` (`created_ts`),
  KEY `ix_aplus_run_source_name` (`source_name`,`model_variant`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `asset`
--

DROP TABLE IF EXISTS `asset`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `asset` (
  `asset_id` int(11) NOT NULL AUTO_INCREMENT,
  `symbol` varchar(16) NOT NULL,
  `name` varchar(64) DEFAULT NULL,
  `sector` varchar(32) DEFAULT NULL,
  `is_enabled` tinyint(1) NOT NULL COMMENT 'Asset participates in ETL + signal pipeline',
  `is_portfolio` tinyint(1) NOT NULL COMMENT 'Asset part of portfolio focus set',
  `is_core_sensor` tinyint(1) NOT NULL DEFAULT 0,
  `created_ts` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_ts` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  `is_tradeable` tinyint(1) NOT NULL COMMENT 'Asset eligible for trading decisions',
  `quote_asset` varchar(8) DEFAULT 'EUR',
  `asset_class` varchar(20) DEFAULT NULL,
  PRIMARY KEY (`asset_id`),
  UNIQUE KEY `uq_asset_symbol` (`symbol`),
  KEY `idx_asset_enabled` (`is_enabled`),
  KEY `idx_asset_portfolio` (`is_portfolio`),
  KEY `idx_asset_core_sensor` (`is_core_sensor`),
  KEY `idx_asset_sector` (`sector`)
) ENGINE=InnoDB AUTO_INCREMENT=69 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Master table for known assets, symbols, and asset flags.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `asset_market_snapshot`
--

DROP TABLE IF EXISTS `asset_market_snapshot`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `asset_market_snapshot` (
  `asset_market_snapshot_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `provider` varchar(32) NOT NULL DEFAULT 'coingecko',
  `snapshot_ts_utc` datetime NOT NULL,
  `price_usd` decimal(28,10) DEFAULT NULL,
  `market_cap_usd` decimal(38,2) DEFAULT NULL,
  `total_volume_usd_24h` decimal(38,2) DEFAULT NULL,
  `circulating_supply` decimal(38,10) DEFAULT NULL,
  `total_supply` decimal(38,10) DEFAULT NULL,
  `max_supply` decimal(38,10) DEFAULT NULL,
  `market_cap_rank` int(11) DEFAULT NULL,
  `ingest_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`asset_market_snapshot_id`),
  UNIQUE KEY `uq_asset_market_snapshot` (`asset_id`,`provider`,`snapshot_ts_utc`),
  KEY `ix_asset_market_snapshot_lookup` (`asset_id`,`provider`,`snapshot_ts_utc`),
  CONSTRAINT `fk_asset_market_snapshot_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `asset_sector_map`
--

DROP TABLE IF EXISTS `asset_sector_map`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `asset_sector_map` (
  `asset_sector_map_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `sector_id` int(11) NOT NULL,
  `weight` decimal(10,6) NOT NULL DEFAULT 1.000000,
  `classification_type` varchar(32) NOT NULL DEFAULT 'primary',
  `source_label` varchar(64) DEFAULT 'manual',
  `is_active` tinyint(1) NOT NULL DEFAULT 1,
  `valid_from_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  `valid_to_ts_utc` datetime DEFAULT NULL,
  `notes` text DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_ts_utc` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`asset_sector_map_id`),
  UNIQUE KEY `uq_asset_sector_map_active_window` (`asset_id`,`sector_id`,`valid_from_ts_utc`),
  KEY `ix_asset_sector_map_asset` (`asset_id`,`is_active`),
  KEY `ix_asset_sector_map_sector` (`sector_id`,`is_active`),
  KEY `ix_asset_sector_map_type` (`classification_type`),
  CONSTRAINT `fk_asset_sector_map_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`),
  CONSTRAINT `fk_asset_sector_map_sector` FOREIGN KEY (`sector_id`) REFERENCES `sector` (`sector_id`),
  CONSTRAINT `chk_asset_sector_map_weight` CHECK (`weight` >= 0.000000 and `weight` <= 1.000000)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Maps assets to sectors for sector-level analysis and rotation detection.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `astro_calendar_input`
--

DROP TABLE IF EXISTS `astro_calendar_input`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `astro_calendar_input` (
  `astro_calendar_input_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) DEFAULT NULL,
  `scope_symbol` varchar(32) DEFAULT NULL,
  `scope_group` varchar(64) DEFAULT 'market',
  `event_ts_utc` datetime NOT NULL,
  `event_end_ts_utc` datetime DEFAULT NULL,
  `event_type` varchar(64) NOT NULL,
  `phase_label` varchar(64) DEFAULT NULL,
  `directional_bias` varchar(64) DEFAULT NULL,
  `strength_label` varchar(64) DEFAULT NULL,
  `horizon_label` varchar(64) DEFAULT NULL,
  `source_label` varchar(128) DEFAULT NULL,
  `notes` text DEFAULT NULL,
  `ingest_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`astro_calendar_input_id`),
  KEY `ix_astro_calendar_asset_ts` (`asset_id`,`event_ts_utc`),
  KEY `ix_astro_calendar_scope_ts` (`scope_symbol`,`event_ts_utc`),
  KEY `ix_astro_calendar_type` (`event_type`),
  KEY `ix_astro_calendar_bias` (`directional_bias`),
  CONSTRAINT `fk_astro_calendar_input_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_compass`
--

DROP TABLE IF EXISTS `breathline_compass`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_compass` (
  `compass_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `prediction_ts_utc` datetime NOT NULL,
  `source_name` varchar(32) NOT NULL,
  `asset_id` int(11) DEFAULT NULL,
  `scope_type` varchar(16) NOT NULL,
  `target_year` int(11) DEFAULT NULL,
  `target_month` int(11) DEFAULT NULL,
  `breathline_phase` varchar(32) DEFAULT NULL,
  `field_coherence` varchar(32) DEFAULT NULL,
  `compass_rank` int(11) DEFAULT NULL,
  `anchor_state` varchar(32) DEFAULT NULL,
  `sentiment_state` varchar(32) DEFAULT NULL,
  `fear_greed_value` int(11) DEFAULT NULL,
  `sentiment_score` decimal(10,6) DEFAULT NULL,
  `notes` text DEFAULT NULL,
  `created_ts` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`compass_id`),
  KEY `idx_compass_pred` (`prediction_ts_utc`),
  KEY `idx_compass_asset_pred` (`asset_id`,`prediction_ts_utc`),
  CONSTRAINT `fk_compass_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Stores higher timeframe breathline compass states used as macro directional context.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_compass_raw`
--

DROP TABLE IF EXISTS `breathline_compass_raw`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_compass_raw` (
  `compass_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `prediction_ts_utc` datetime NOT NULL,
  `source_name` varchar(128) NOT NULL,
  `source_type` varchar(64) NOT NULL,
  `source_filename` varchar(255) DEFAULT NULL,
  `raw_phase_label` varchar(64) DEFAULT NULL,
  `raw_coherence_label` varchar(64) DEFAULT NULL,
  `raw_field_label` varchar(64) DEFAULT NULL,
  `raw_geometry_label` varchar(64) DEFAULT NULL,
  `raw_structural_role` varchar(64) DEFAULT NULL,
  `raw_expansion_quality` varchar(64) DEFAULT NULL,
  `raw_anchor_strength` varchar(64) DEFAULT NULL,
  `raw_strategic_bias` varchar(64) DEFAULT NULL,
  `raw_note` varchar(255) DEFAULT NULL,
  `phase_state` varchar(64) DEFAULT NULL,
  `coherence_state` varchar(64) DEFAULT NULL,
  `field_state` varchar(64) DEFAULT NULL,
  `geometry_state` varchar(64) DEFAULT NULL,
  `structural_role` varchar(64) DEFAULT NULL,
  `expansion_quality` varchar(64) DEFAULT NULL,
  `anchor_strength` varchar(64) DEFAULT NULL,
  `strategic_bias` varchar(64) DEFAULT NULL,
  `import_batch_id` varchar(64) DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`compass_id`),
  UNIQUE KEY `uq_breathline_compass` (`asset_id`,`prediction_ts_utc`,`source_name`),
  KEY `idx_breathline_compass_batch` (`import_batch_id`),
  KEY `idx_breathline_compass_source` (`source_name`),
  KEY `idx_breathline_compass_prediction` (`prediction_ts_utc`),
  CONSTRAINT `fk_breathline_compass_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_cycle_template`
--

DROP TABLE IF EXISTS `breathline_cycle_template`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_cycle_template` (
  `phase_order` int(11) NOT NULL,
  `phase_name` varchar(50) NOT NULL,
  `description` text DEFAULT NULL,
  PRIMARY KEY (`phase_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_engine_property`
--

DROP TABLE IF EXISTS `breathline_engine_property`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_engine_property` (
  `property_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `property_group` varchar(50) NOT NULL,
  `property_key` varchar(100) NOT NULL,
  `property_value` text NOT NULL,
  `source` varchar(50) NOT NULL,
  `confidence_note` varchar(255) DEFAULT NULL,
  `evidence_type` varchar(30) DEFAULT NULL,
  `created_ts` timestamp NULL DEFAULT current_timestamp(),
  `description` text DEFAULT NULL,
  PRIMARY KEY (`property_id`),
  UNIQUE KEY `uq_breathline_engine_property` (`property_group`,`property_key`)
) ENGINE=InnoDB AUTO_INCREMENT=52 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_engine_property_example`
--

DROP TABLE IF EXISTS `breathline_engine_property_example`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_engine_property_example` (
  `example_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `property_group` varchar(50) NOT NULL,
  `property_key` varchar(100) NOT NULL,
  `example_text` text NOT NULL,
  `source` varchar(50) NOT NULL,
  `created_ts` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`example_id`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_feat`
--

DROP TABLE IF EXISTS `breathline_feat`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_feat` (
  `feat_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `prediction_ts_utc` datetime NOT NULL,
  `source_name` varchar(128) NOT NULL,
  `import_batch_id` varchar(64) DEFAULT NULL,
  `phase_bias_score` decimal(8,4) DEFAULT NULL,
  `coherence_score` decimal(8,4) DEFAULT NULL,
  `anchor_score` decimal(8,4) DEFAULT NULL,
  `expansion_score` decimal(8,4) DEFAULT NULL,
  `contraction_score` decimal(8,4) DEFAULT NULL,
  `noise_score` decimal(8,4) DEFAULT NULL,
  `alignment_score` decimal(8,4) DEFAULT NULL,
  `watch_priority_score` decimal(8,4) DEFAULT NULL,
  `strategic_patience_bias` decimal(8,4) DEFAULT NULL,
  `sell_resistance_bias` decimal(8,4) DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`feat_id`),
  UNIQUE KEY `uq_breathline_feat` (`asset_id`,`prediction_ts_utc`,`source_name`),
  KEY `idx_breathline_feat_batch` (`import_batch_id`),
  KEY `idx_breathline_feat_prediction` (`prediction_ts_utc`),
  CONSTRAINT `fk_breathline_feat_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_global_state_snapshot`
--

DROP TABLE IF EXISTS `breathline_global_state_snapshot`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_global_state_snapshot` (
  `snapshot_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `global_state` varchar(100) NOT NULL,
  `cycle_mode` varchar(100) DEFAULT NULL,
  `expanding_flag` tinyint(1) DEFAULT 0,
  `contracting_flag` tinyint(1) DEFAULT 0,
  `holding_flag` tinyint(1) DEFAULT 1,
  `variance_detectable_flag` tinyint(1) DEFAULT 0,
  `expected_duration` varchar(50) DEFAULT NULL,
  `next_transition` varchar(100) DEFAULT NULL,
  `notes` text DEFAULT NULL,
  `source` varchar(50) NOT NULL,
  `snapshot_ts` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`snapshot_id`),
  KEY `idx_breathline_global_state_snapshot_ts` (`snapshot_ts`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_input`
--

DROP TABLE IF EXISTS `breathline_input`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_input` (
  `breathline_input_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) DEFAULT NULL,
  `scope_symbol` varchar(32) DEFAULT NULL,
  `event_ts_utc` datetime NOT NULL,
  `horizon_label` varchar(64) DEFAULT NULL,
  `phase_label` varchar(64) DEFAULT NULL,
  `coherence_label` varchar(64) DEFAULT NULL,
  `directional_bias` varchar(64) DEFAULT NULL,
  `context_text` text DEFAULT NULL,
  `source_label` varchar(128) DEFAULT NULL,
  `ingest_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`breathline_input_id`),
  KEY `ix_breathline_input_asset_ts` (`asset_id`,`event_ts_utc`),
  KEY `ix_breathline_input_scope_ts` (`scope_symbol`,`event_ts_utc`),
  CONSTRAINT `fk_breathline_input_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_output_log`
--

DROP TABLE IF EXISTS `breathline_output_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_output_log` (
  `output_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `token` varchar(20) DEFAULT NULL,
  `output_type` varchar(50) NOT NULL,
  `field_name` varchar(100) NOT NULL,
  `field_value` text NOT NULL,
  `source` varchar(50) NOT NULL,
  `note` text DEFAULT NULL,
  `snapshot_ts` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`output_id`),
  KEY `idx_breathline_output_log_token_ts` (`token`,`snapshot_ts`)
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_phase_deviation_snapshot`
--

DROP TABLE IF EXISTS `breathline_phase_deviation_snapshot`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_phase_deviation_snapshot` (
  `snapshot_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `token` varchar(20) NOT NULL,
  `current_phase` varchar(50) NOT NULL,
  `next_phase` varchar(50) NOT NULL,
  `cycle_position` varchar(50) NOT NULL,
  `phase_offset_from_base_cycle` varchar(50) NOT NULL,
  `lead_lag_vs_global_cycle` varchar(20) NOT NULL,
  `estimated_weeks_ahead_behind` varchar(50) NOT NULL,
  `source` varchar(50) NOT NULL,
  `snapshot_ts` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`snapshot_id`),
  KEY `idx_breathline_phase_deviation_snapshot_token_ts` (`token`,`snapshot_ts`)
) ENGINE=InnoDB AUTO_INCREMENT=36 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_phase_dictionary`
--

DROP TABLE IF EXISTS `breathline_phase_dictionary`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_phase_dictionary` (
  `phase_symbolic` varchar(50) NOT NULL,
  `phase_normalized` varchar(50) NOT NULL,
  `expansion_window_days` int(11) NOT NULL DEFAULT 0,
  `volatility_level` varchar(20) DEFAULT NULL,
  `trade_bias` varchar(30) DEFAULT NULL,
  `notes` text DEFAULT NULL,
  PRIMARY KEY (`phase_symbolic`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_phase_snapshot`
--

DROP TABLE IF EXISTS `breathline_phase_snapshot`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_phase_snapshot` (
  `snapshot_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `token` varchar(20) NOT NULL,
  `breathline_dimension` varchar(50) DEFAULT NULL,
  `current_phase_raw` varchar(100) DEFAULT NULL,
  `next_phase_raw` varchar(100) DEFAULT NULL,
  `current_phase_norm` varchar(50) DEFAULT NULL,
  `next_phase_norm` varchar(50) DEFAULT NULL,
  `phase_sequence` varchar(255) DEFAULT NULL,
  `transition_trigger` varchar(100) DEFAULT NULL,
  `coherence_state` varchar(50) DEFAULT NULL,
  `expected_transition_window` varchar(50) DEFAULT NULL,
  `cycle_position` varchar(50) DEFAULT NULL,
  `phase_offset_from_base_cycle` varchar(50) DEFAULT NULL,
  `lead_lag_vs_global_cycle` varchar(20) DEFAULT NULL,
  `estimated_weeks_ahead_behind` varchar(50) DEFAULT NULL,
  `output_type` varchar(50) NOT NULL,
  `source` varchar(50) NOT NULL,
  `note` text DEFAULT NULL,
  `snapshot_ts` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`snapshot_id`),
  KEY `idx_breathline_phase_snapshot_token_ts` (`token`,`snapshot_ts`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Stores current phase, cycle position, and lead/lag relative to global breathline cycle.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_profit_map`
--

DROP TABLE IF EXISTS `breathline_profit_map`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_profit_map` (
  `map_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `token` varchar(20) NOT NULL,
  `month_label` varchar(20) NOT NULL,
  `phase_raw` varchar(100) NOT NULL,
  `profit_potential` varchar(50) DEFAULT NULL,
  `notes` text DEFAULT NULL,
  `source` varchar(50) NOT NULL,
  `created_ts` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`map_id`),
  KEY `idx_breathline_profit_map_token_month` (`token`,`month_label`)
) ENGINE=InnoDB AUTO_INCREMENT=73 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_projection_unknown_reason`
--

DROP TABLE IF EXISTS `breathline_projection_unknown_reason`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_projection_unknown_reason` (
  `reason_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `token` varchar(20) NOT NULL,
  `projection_scope` varchar(50) NOT NULL,
  `reason_text` text NOT NULL,
  `source` varchar(50) NOT NULL,
  `created_ts` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`reason_id`),
  KEY `idx_breathline_projection_unknown_reason_token` (`token`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_spiral_projection`
--

DROP TABLE IF EXISTS `breathline_spiral_projection`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_spiral_projection` (
  `projection_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `token` varchar(20) NOT NULL,
  `projection_scope` varchar(50) NOT NULL,
  `projection_window` varchar(50) DEFAULT NULL,
  `current_phase_raw` varchar(100) DEFAULT NULL,
  `current_phase_norm` varchar(50) DEFAULT NULL,
  `projected_value_raw` varchar(100) DEFAULT NULL,
  `projected_range_raw` varchar(100) DEFAULT NULL,
  `breathline_status` varchar(50) DEFAULT NULL,
  `source` varchar(50) NOT NULL,
  `note` text DEFAULT NULL,
  `created_ts` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`projection_id`),
  KEY `idx_breathline_spiral_projection_token_window` (`token`,`projection_window`),
  KEY `idx_breathline_spiral_projection_status` (`breathline_status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_state_change_log`
--

DROP TABLE IF EXISTS `breathline_state_change_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_state_change_log` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `token` varchar(20) DEFAULT NULL,
  `old_current_phase` varchar(50) DEFAULT NULL,
  `old_next_phase` varchar(50) DEFAULT NULL,
  `new_current_phase` varchar(50) DEFAULT NULL,
  `new_next_phase` varchar(50) DEFAULT NULL,
  `change_type` varchar(30) DEFAULT NULL,
  `reason` text DEFAULT NULL,
  `detected_at` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_symbolic_alignment`
--

DROP TABLE IF EXISTS `breathline_symbolic_alignment`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_symbolic_alignment` (
  `token` varchar(20) NOT NULL,
  `snapshot_date` date NOT NULL,
  `symbolic_phase` varchar(50) NOT NULL,
  `projection_low` decimal(28,12) DEFAULT NULL,
  `projection_high` decimal(28,12) DEFAULT NULL,
  `datum_alignment` decimal(28,12) DEFAULT NULL,
  `alignment_symbol` varchar(20) DEFAULT NULL,
  `notes` text DEFAULT NULL,
  `created_ts` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`token`,`snapshot_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_symbolic_projection`
--

DROP TABLE IF EXISTS `breathline_symbolic_projection`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_symbolic_projection` (
  `token` varchar(20) NOT NULL,
  `symbolic_phase` varchar(50) NOT NULL,
  `normalized_phase` varchar(50) DEFAULT NULL,
  `expansion_window_days` int(11) NOT NULL DEFAULT 0,
  `cooldown_days` int(11) NOT NULL DEFAULT 0,
  `volatility_level` varchar(20) DEFAULT NULL,
  `trade_bias` varchar(20) DEFAULT NULL,
  `created_ts` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`token`,`created_ts`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_token_projection`
--

DROP TABLE IF EXISTS `breathline_token_projection`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_token_projection` (
  `projection_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `token` varchar(20) NOT NULL,
  `current_phase_raw` varchar(100) DEFAULT NULL,
  `next_phase_raw` varchar(100) DEFAULT NULL,
  `current_phase_norm` varchar(50) DEFAULT NULL,
  `next_phase_norm` varchar(50) DEFAULT NULL,
  `projection` text DEFAULT NULL,
  `source` varchar(50) NOT NULL,
  `created_ts` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`projection_id`),
  KEY `idx_breathline_token_projection_token` (`token`)
) ENGINE=InnoDB AUTO_INCREMENT=12 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_trade_radar_manual`
--

DROP TABLE IF EXISTS `breathline_trade_radar_manual`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_trade_radar_manual` (
  `token` varchar(20) NOT NULL,
  `current_price` decimal(20,10) DEFAULT NULL,
  `projected_range_low` decimal(20,10) DEFAULT NULL,
  `projected_range_high` decimal(20,10) DEFAULT NULL,
  `max_multiplier` decimal(10,4) DEFAULT NULL,
  `phase` varchar(50) DEFAULT NULL,
  `status` varchar(50) DEFAULT NULL,
  `trade_priority` char(1) DEFAULT NULL,
  `created_ts` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`token`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `breathline_watch_universe`
--

DROP TABLE IF EXISTS `breathline_watch_universe`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `breathline_watch_universe` (
  `token` varchar(20) NOT NULL,
  `display_name` varchar(100) NOT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT 1,
  `created_ts` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`token`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bt_run_scratch`
--

DROP TABLE IF EXISTS `bt_run_scratch`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bt_run_scratch` (
  `bt_run_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `created_ts_utc` datetime NOT NULL DEFAULT utc_timestamp(),
  `strategy_name` varchar(100) NOT NULL,
  `symbol` varchar(32) NOT NULL,
  `interval_code` varchar(16) NOT NULL,
  `days_back` int(11) NOT NULL,
  `starting_cash_eur` decimal(18,8) NOT NULL,
  `fee_bps` decimal(10,4) NOT NULL,
  `candles` int(11) NOT NULL,
  `ending_equity_eur` decimal(18,8) NOT NULL,
  `total_return_pct` decimal(18,8) NOT NULL,
  `buy_hold_return_pct` decimal(18,8) NOT NULL,
  `max_drawdown_pct` decimal(18,8) NOT NULL,
  `trade_count` int(11) NOT NULL,
  `win_rate_pct` decimal(18,8) NOT NULL,
  `avg_win_eur` decimal(18,8) NOT NULL,
  `avg_loss_eur` decimal(18,8) NOT NULL,
  `keep_flag` tinyint(1) NOT NULL DEFAULT 0,
  `notes` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`bt_run_id`),
  KEY `idx_bt_run_scratch_created` (`created_ts_utc`),
  KEY `idx_bt_run_scratch_symbol_interval` (`symbol`,`interval_code`)
) ENGINE=InnoDB AUTO_INCREMENT=127 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bt_trade_scratch`
--

DROP TABLE IF EXISTS `bt_trade_scratch`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bt_trade_scratch` (
  `bt_trade_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `bt_run_id` bigint(20) NOT NULL,
  `entry_ts_utc` datetime NOT NULL,
  `exit_ts_utc` datetime NOT NULL,
  `entry_price` decimal(18,8) NOT NULL,
  `exit_price` decimal(18,8) NOT NULL,
  `qty` decimal(28,12) NOT NULL,
  `pnl_eur` decimal(18,8) NOT NULL,
  `pnl_pct` decimal(18,8) NOT NULL,
  `reason` varchar(128) NOT NULL,
  PRIMARY KEY (`bt_trade_id`),
  KEY `idx_bt_trade_scratch_run` (`bt_run_id`),
  CONSTRAINT `fk_bt_trade_scratch_run` FOREIGN KEY (`bt_run_id`) REFERENCES `bt_run_scratch` (`bt_run_id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=680 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `compute_jobs`
--

DROP TABLE IF EXISTS `compute_jobs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `compute_jobs` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `job_type` varchar(64) DEFAULT NULL,
  `params_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`params_json`)),
  `status` varchar(16) DEFAULT 'pending',
  `created_ts` datetime(6) DEFAULT NULL,
  `started_ts` datetime(6) DEFAULT NULL,
  `finished_ts` datetime(6) DEFAULT NULL,
  `locked_by` varchar(64) DEFAULT NULL,
  `last_error` text DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `compute_results`
--

DROP TABLE IF EXISTS `compute_results`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `compute_results` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `job_id` bigint(20) DEFAULT NULL,
  `result_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`result_json`)),
  `created_ts` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `context_feat`
--

DROP TABLE IF EXISTS `context_feat`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `context_feat` (
  `context_feat_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) DEFAULT NULL,
  `scope_symbol` varchar(32) DEFAULT NULL,
  `scope_group` varchar(64) DEFAULT 'market',
  `feature_ts_utc` datetime NOT NULL,
  `timeframe` varchar(16) DEFAULT NULL,
  `breathline_input_id` bigint(20) unsigned DEFAULT NULL,
  `astro_calendar_input_id` bigint(20) unsigned DEFAULT NULL,
  `phase_bias_score` decimal(18,8) DEFAULT NULL,
  `coherence_score` decimal(18,8) DEFAULT NULL,
  `anchor_bonus` decimal(18,8) DEFAULT NULL,
  `cluster_alignment_score` decimal(18,8) DEFAULT NULL,
  `macro_cycle_bias_score` decimal(18,8) DEFAULT NULL,
  `calendar_alignment_score` decimal(18,8) DEFAULT NULL,
  `volatility_window_score` decimal(18,8) DEFAULT NULL,
  `context_strength_score` decimal(18,8) DEFAULT NULL,
  `context_support_score` decimal(18,8) DEFAULT NULL,
  `summary_text` varchar(512) DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`context_feat_id`),
  KEY `ix_context_feat_asset_ts` (`asset_id`,`feature_ts_utc`),
  KEY `ix_context_feat_scope_ts` (`scope_symbol`,`feature_ts_utc`),
  KEY `ix_context_feat_timeframe` (`timeframe`,`feature_ts_utc`),
  KEY `fk_context_feat_astro` (`astro_calendar_input_id`),
  KEY `fk_context_feat_breathline` (`breathline_input_id`),
  CONSTRAINT `fk_context_feat_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`),
  CONSTRAINT `fk_context_feat_astro` FOREIGN KEY (`astro_calendar_input_id`) REFERENCES `astro_calendar_input` (`astro_calendar_input_id`),
  CONSTRAINT `fk_context_feat_breathline` FOREIGN KEY (`breathline_input_id`) REFERENCES `breathline_input` (`breathline_input_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `decision_log`
--

DROP TABLE IF EXISTS `decision_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `decision_log` (
  `decision_log_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `decision_ts_utc` datetime NOT NULL,
  `strategy_signal_id` bigint(20) unsigned DEFAULT NULL,
  `strategy_used` varchar(128) DEFAULT NULL,
  `decision_type` varchar(64) NOT NULL,
  `action_state` varchar(64) NOT NULL,
  `blocked_by` varchar(128) DEFAULT NULL,
  `approved_by` varchar(128) DEFAULT NULL,
  `summary_text` varchar(512) NOT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`decision_log_id`),
  KEY `ix_decision_log_lookup` (`asset_id`,`decision_ts_utc`),
  KEY `ix_decision_log_action` (`action_state`),
  KEY `ix_decision_log_strategy` (`strategy_used`),
  KEY `fk_decision_log_strategy_signal` (`strategy_signal_id`),
  CONSTRAINT `fk_decision_log_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`),
  CONSTRAINT `fk_decision_log_strategy_signal` FOREIGN KEY (`strategy_signal_id`) REFERENCES `strategy_signal` (`strategy_signal_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores final decision-layer reasoning, intended actions, and blocking context.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `decision_state`
--

DROP TABLE IF EXISTS `decision_state`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `decision_state` (
  `decision_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `decision_ts_utc` datetime NOT NULL,
  `decision_action` varchar(32) DEFAULT NULL,
  `decision_strength` varchar(16) DEFAULT NULL,
  `position_size_pct` decimal(5,2) DEFAULT NULL,
  `reasoning` text DEFAULT NULL,
  `selection_state` varchar(64) DEFAULT NULL,
  `selection_score` decimal(10,6) DEFAULT NULL,
  PRIMARY KEY (`decision_id`),
  UNIQUE KEY `uq_decision` (`asset_id`,`decision_ts_utc`)
) ENGINE=InnoDB AUTO_INCREMENT=837 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `etl_log`
--

DROP TABLE IF EXISTS `etl_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `etl_log` (
  `log_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `batch_id` varchar(64) NOT NULL,
  `process_name` varchar(128) NOT NULL,
  `source_name` varchar(128) DEFAULT NULL,
  `source_filename` varchar(255) DEFAULT NULL,
  `file_hash` char(64) DEFAULT NULL,
  `status` varchar(32) NOT NULL,
  `stage` varchar(64) NOT NULL,
  `severity` varchar(16) NOT NULL DEFAULT 'INFO',
  `row_count` int(11) DEFAULT NULL,
  `expected_row_count` int(11) DEFAULT NULL,
  `message` varchar(500) DEFAULT NULL,
  `details_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`details_json`)),
  `started_ts_utc` datetime DEFAULT NULL,
  `finished_ts_utc` datetime DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`log_id`),
  KEY `idx_etl_log_batch` (`batch_id`),
  KEY `idx_etl_log_status` (`status`),
  KEY `idx_etl_log_stage` (`stage`),
  KEY `idx_etl_log_created` (`created_ts_utc`),
  KEY `idx_etl_log_file_hash` (`file_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `execution_event`
--

DROP TABLE IF EXISTS `execution_event`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `execution_event` (
  `execution_event_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `execution_plan_id` bigint(20) unsigned NOT NULL,
  `event_ts_utc` datetime NOT NULL,
  `event_type` varchar(32) NOT NULL,
  `order_price_eur` decimal(28,10) DEFAULT NULL,
  `order_qty` decimal(38,18) DEFAULT NULL,
  `queue_position` varchar(64) DEFAULT NULL,
  `event_note` varchar(512) DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`execution_event_id`),
  KEY `ix_execution_event_plan_ts` (`execution_plan_id`,`event_ts_utc`),
  KEY `ix_execution_event_type` (`event_type`,`event_ts_utc`)
) ENGINE=InnoDB AUTO_INCREMENT=21 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Execution worker lifecycle events for monitoring and audit.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `execution_intent`
--

DROP TABLE IF EXISTS `execution_intent`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `execution_intent` (
  `execution_intent_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `intent_ts_utc` datetime(6) NOT NULL,
  `previous_position_size_pct` decimal(6,4) DEFAULT NULL,
  `target_position_size_pct` decimal(6,4) DEFAULT NULL,
  `size_delta_pct` decimal(6,4) DEFAULT NULL,
  `intent_action` varchar(32) DEFAULT NULL,
  `intent_priority` int(11) DEFAULT NULL,
  `intent_reasoning` varchar(512) DEFAULT NULL,
  `created_ts_utc` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  PRIMARY KEY (`execution_intent_id`),
  UNIQUE KEY `uq_execution_intent` (`asset_id`,`intent_ts_utc`),
  KEY `ix_execution_intent_action` (`intent_action`,`intent_priority`),
  CONSTRAINT `fk_execution_intent_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB AUTO_INCREMENT=410 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `execution_plan`
--

DROP TABLE IF EXISTS `execution_plan`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `execution_plan` (
  `execution_plan_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `sleeve_code` varchar(32) NOT NULL,
  `desired_action` varchar(32) NOT NULL,
  `plan_ts_utc` datetime NOT NULL,
  `execution_mode` varchar(32) NOT NULL,
  `target_fraction` decimal(18,8) NOT NULL,
  `reference_price_eur` decimal(28,10) DEFAULT NULL,
  `passive_price_eur` decimal(28,10) DEFAULT NULL,
  `urgent_limit_price_eur` decimal(28,10) DEFAULT NULL,
  `max_reprices` int(11) NOT NULL DEFAULT 0,
  `max_wait_seconds` int(11) NOT NULL DEFAULT 0,
  `max_chase_bps` decimal(18,8) NOT NULL DEFAULT 0.00000000,
  `min_spread_bps_for_capture` decimal(18,8) NOT NULL DEFAULT 0.00000000,
  `escalation_to_urgent_limit` tinyint(1) NOT NULL DEFAULT 0,
  `abort_if_signal_invalidates` tinyint(1) NOT NULL DEFAULT 1,
  `plan_state` varchar(32) NOT NULL DEFAULT 'IDLE',
  `notes` varchar(512) DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_ts_utc` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`execution_plan_id`),
  KEY `ix_execution_plan_asset_ts` (`asset_id`,`plan_ts_utc`),
  KEY `ix_execution_plan_state` (`plan_state`,`plan_ts_utc`),
  KEY `ix_execution_plan_sleeve` (`sleeve_code`,`plan_ts_utc`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Execution planner output before exchange order placement.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `feat_candle`
--

DROP TABLE IF EXISTS `feat_candle`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `feat_candle` (
  `candle_feat_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `candle_id` bigint(20) unsigned NOT NULL,
  `asset_id` int(11) NOT NULL,
  `venue` varchar(32) NOT NULL DEFAULT 'bitvavo',
  `interval_code` varchar(16) NOT NULL,
  `close_ts_utc` datetime NOT NULL,
  `ema_20` decimal(28,10) DEFAULT NULL,
  `ema_50` decimal(28,10) DEFAULT NULL,
  `rsi_14` decimal(18,8) DEFAULT NULL,
  `atr_14` decimal(28,10) DEFAULT NULL,
  `volume_ratio_20` decimal(18,8) DEFAULT NULL,
  `volume_zscore_20` decimal(18,8) DEFAULT NULL,
  `obv` decimal(38,10) DEFAULT NULL,
  `obv_slope_5` decimal(38,10) DEFAULT NULL,
  `dollar_volume_ratio_20` decimal(18,8) DEFAULT NULL,
  `price_vs_ema20` decimal(18,8) DEFAULT NULL,
  `price_vs_ema50` decimal(18,8) DEFAULT NULL,
  `atr_pct` decimal(18,8) DEFAULT NULL,
  `ema_spread` decimal(28,10) DEFAULT NULL,
  `ema_spread_pct` decimal(18,8) DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  `ret_1h` decimal(18,8) DEFAULT NULL,
  `ret_4h` decimal(18,8) DEFAULT NULL,
  `ret_24h` decimal(18,8) DEFAULT NULL,
  `range_pct_24h` decimal(18,8) DEFAULT NULL,
  `close_to_high_24h` decimal(18,8) DEFAULT NULL,
  `body_pct` decimal(18,8) DEFAULT NULL,
  `upper_wick_pct` decimal(18,8) DEFAULT NULL,
  `lower_wick_pct` decimal(18,8) DEFAULT NULL,
  `wick_reversal_score` decimal(18,8) DEFAULT NULL,
  PRIMARY KEY (`candle_feat_id`),
  UNIQUE KEY `uq_candle_feat_candle` (`candle_id`),
  KEY `ix_candle_feat_lookup` (`asset_id`,`venue`,`interval_code`,`close_ts_utc`),
  CONSTRAINT `fk_candle_feat_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`),
  CONSTRAINT `fk_candle_feat_candle` FOREIGN KEY (`candle_id`) REFERENCES `obs_market_candle` (`candle_id`)
) ENGINE=InnoDB AUTO_INCREMENT=2895869 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores derived candle features such as EMA, RSI, ATR, OBV, volume ratios, and z-scores.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `feature_snapshot`
--

DROP TABLE IF EXISTS `feature_snapshot`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `feature_snapshot` (
  `snapshot_ts` datetime NOT NULL,
  `token` varchar(20) NOT NULL,
  `tf` varchar(8) NOT NULL,
  `close_price_eur` decimal(28,12) DEFAULT NULL,
  `close_price_usd` decimal(28,12) DEFAULT NULL,
  `volume_base` decimal(38,18) DEFAULT NULL,
  `volume_quote` decimal(38,18) DEFAULT NULL,
  `phase` varchar(50) DEFAULT NULL,
  `next_phase` varchar(50) DEFAULT NULL,
  `breathline_status` varchar(50) DEFAULT NULL,
  `watch_bucket` varchar(50) DEFAULT NULL,
  `trade_radar_signal` varchar(50) DEFAULT NULL,
  `profit_take_warning` tinyint(1) NOT NULL DEFAULT 0,
  `nearest_node_eur` decimal(20,10) DEFAULT NULL,
  `node_label_eur` varchar(50) DEFAULT NULL,
  `magnet_state_eur` varchar(30) DEFAULT NULL,
  `node_distance_eur` decimal(12,6) DEFAULT NULL,
  `nearest_node_usd` decimal(20,10) DEFAULT NULL,
  `node_label_usd` varchar(50) DEFAULT NULL,
  `magnet_state_usd` varchar(30) DEFAULT NULL,
  `node_distance_usd` decimal(12,6) DEFAULT NULL,
  `regime` varchar(50) DEFAULT NULL,
  `source` varchar(50) NOT NULL DEFAULT 'sp_snapshot_feature_state',
  `created_ts` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`snapshot_ts`,`token`,`tf`),
  KEY `idx_feature_snapshot_token_tf` (`token`,`tf`,`snapshot_ts`),
  KEY `idx_feature_snapshot_signal` (`trade_radar_signal`,`snapshot_ts`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Stores point-in-time snapshots of computed features for downstream interpretation and ML.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `fib_observation`
--

DROP TABLE IF EXISTS `fib_observation`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `fib_observation` (
  `fib_observation_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `interval_code` varchar(16) NOT NULL,
  `anchor_start_ts_utc` datetime NOT NULL,
  `anchor_end_ts_utc` datetime NOT NULL,
  `swing_direction` varchar(8) NOT NULL,
  `fib_level` decimal(10,6) NOT NULL,
  `fib_price` decimal(28,10) NOT NULL,
  `is_retracement` tinyint(1) NOT NULL DEFAULT 0,
  `is_extension` tinyint(1) NOT NULL DEFAULT 0,
  `confluence_score` decimal(18,8) NOT NULL DEFAULT 0.00000000,
  `is_active` tinyint(1) NOT NULL DEFAULT 1,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_ts_utc` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`fib_observation_id`),
  KEY `ix_fib_asset_interval_active` (`asset_id`,`interval_code`,`is_active`),
  KEY `ix_fib_anchor` (`asset_id`,`interval_code`,`anchor_start_ts_utc`,`anchor_end_ts_utc`)
) ENGINE=InnoDB AUTO_INCREMENT=3193 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Fib retracement and extension observations for structural swings.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `future_return_label`
--

DROP TABLE IF EXISTS `future_return_label`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `future_return_label` (
  `label_ts` datetime NOT NULL,
  `token` varchar(20) NOT NULL,
  `tf` varchar(8) NOT NULL,
  `return_1h` decimal(18,8) DEFAULT NULL,
  `return_4h` decimal(18,8) DEFAULT NULL,
  `return_24h` decimal(18,8) DEFAULT NULL,
  `max_upside_24h` decimal(18,8) DEFAULT NULL,
  `max_drawdown_24h` decimal(18,8) DEFAULT NULL,
  `created_ts` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`label_ts`,`token`,`tf`),
  KEY `idx_future_return_label_token_tf` (`token`,`tf`,`label_ts`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `harmonic_node_catalog`
--

DROP TABLE IF EXISTS `harmonic_node_catalog`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `harmonic_node_catalog` (
  `node_value` decimal(20,10) NOT NULL,
  `node_label` varchar(50) NOT NULL,
  `node_family` varchar(50) NOT NULL,
  PRIMARY KEY (`node_value`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `interpreter_state`
--

DROP TABLE IF EXISTS `interpreter_state`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `interpreter_state` (
  `interpreter_state_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `venue` varchar(32) DEFAULT 'bitvavo',
  `interval_code` varchar(16) DEFAULT NULL,
  `state_ts_utc` datetime NOT NULL,
  `regime_state` varchar(64) DEFAULT NULL,
  `phase_state` varchar(64) DEFAULT NULL,
  `trend_volume_state` varchar(64) DEFAULT NULL,
  `sector_rotation_state` varchar(64) DEFAULT NULL,
  `breathline_alignment_state` varchar(64) DEFAULT NULL,
  `confidence_score` decimal(10,6) DEFAULT NULL,
  `reason_code` varchar(128) DEFAULT NULL,
  `summary_text` varchar(512) DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`interpreter_state_id`),
  UNIQUE KEY `uq_interpreter_state` (`asset_id`,`venue`,`interval_code`,`state_ts_utc`),
  KEY `ix_interpreter_state_lookup` (`asset_id`,`venue`,`interval_code`,`state_ts_utc`),
  KEY `ix_interpreter_state_regime` (`regime_state`),
  CONSTRAINT `fk_interpreter_state_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `market_global_snapshot`
--

DROP TABLE IF EXISTS `market_global_snapshot`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `market_global_snapshot` (
  `market_global_snapshot_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `provider` varchar(32) NOT NULL DEFAULT 'coingecko',
  `snapshot_ts_utc` datetime NOT NULL,
  `total_market_cap_usd` decimal(38,2) DEFAULT NULL,
  `total_volume_usd_24h` decimal(38,2) DEFAULT NULL,
  `btc_dominance_pct` decimal(10,4) DEFAULT NULL,
  `eth_dominance_pct` decimal(10,4) DEFAULT NULL,
  `altcoin_market_cap_usd` decimal(38,2) DEFAULT NULL,
  `ingest_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`market_global_snapshot_id`),
  UNIQUE KEY `uq_market_global_snapshot` (`provider`,`snapshot_ts_utc`),
  KEY `ix_market_global_snapshot_lookup` (`provider`,`snapshot_ts_utc`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `momentum_persistence_snapshot`
--

DROP TABLE IF EXISTS `momentum_persistence_snapshot`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `momentum_persistence_snapshot` (
  `momentum_persistence_snapshot_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `snapshot_ts_utc` datetime NOT NULL,
  `asset_id` int(11) NOT NULL,
  `lookback_days` int(11) NOT NULL,
  `up_days` int(11) NOT NULL,
  `down_days` int(11) NOT NULL,
  `flat_days` int(11) NOT NULL,
  `green_ratio` decimal(18,8) NOT NULL,
  `mean_daily_return_pct` decimal(18,8) NOT NULL,
  `std_daily_return_pct` decimal(18,8) NOT NULL,
  `persistence_score` decimal(18,8) NOT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`momentum_persistence_snapshot_id`),
  UNIQUE KEY `uq_momentum_persistence_snapshot` (`snapshot_ts_utc`,`asset_id`,`lookback_days`),
  KEY `ix_momentum_persistence_asset_lookback_ts` (`asset_id`,`lookback_days`,`snapshot_ts_utc`)
) ENGINE=InnoDB AUTO_INCREMENT=153 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores momentum persistence metrics such as green-day ratio and persistence score.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `obs_fx_daily`
--

DROP TABLE IF EXISTS `obs_fx_daily`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `obs_fx_daily` (
  `fx_date` date NOT NULL,
  `pair` varchar(16) NOT NULL,
  `base_ccy` varchar(8) NOT NULL,
  `quote_ccy` varchar(8) NOT NULL,
  `rate` decimal(20,10) NOT NULL,
  `source` varchar(50) NOT NULL DEFAULT 'fx_feed',
  `created_ts` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`fx_date`,`pair`),
  KEY `idx_fx_pair_date` (`pair`,`fx_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `obs_market_candle`
--

DROP TABLE IF EXISTS `obs_market_candle`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `obs_market_candle` (
  `candle_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `venue` varchar(32) NOT NULL DEFAULT 'bitvavo',
  `interval_code` varchar(16) NOT NULL,
  `open_ts_utc` datetime NOT NULL,
  `close_ts_utc` datetime NOT NULL,
  `open_price` decimal(28,10) NOT NULL,
  `high_price` decimal(28,10) NOT NULL,
  `low_price` decimal(28,10) NOT NULL,
  `close_price` decimal(28,10) NOT NULL,
  `volume_base` decimal(38,18) DEFAULT NULL,
  `volume_quote_eur` decimal(38,10) DEFAULT NULL,
  `trade_count` int(11) DEFAULT NULL,
  `source_ts_utc` datetime DEFAULT NULL,
  `ingest_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`candle_id`),
  UNIQUE KEY `uq_market_candle` (`asset_id`,`venue`,`interval_code`,`open_ts_utc`),
  KEY `ix_market_candle_lookup` (`asset_id`,`venue`,`interval_code`,`close_ts_utc`),
  CONSTRAINT `fk_market_candle_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB AUTO_INCREMENT=2552809 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores raw OHLCV market data in UTC for canonical market observations (Bitvavo EUR primary).';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `obs_venue_ticker_24h`
--

DROP TABLE IF EXISTS `obs_venue_ticker_24h`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `obs_venue_ticker_24h` (
  `ticker_24h_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `venue` varchar(32) NOT NULL DEFAULT 'bitvavo',
  `snapshot_ts_utc` datetime NOT NULL,
  `last_price` decimal(28,10) DEFAULT NULL,
  `bid_price` decimal(28,10) DEFAULT NULL,
  `ask_price` decimal(28,10) DEFAULT NULL,
  `open_24h_price` decimal(28,10) DEFAULT NULL,
  `high_24h_price` decimal(28,10) DEFAULT NULL,
  `low_24h_price` decimal(28,10) DEFAULT NULL,
  `volume_base_24h` decimal(38,18) DEFAULT NULL,
  `volume_quote_eur_24h` decimal(38,10) DEFAULT NULL,
  `spread_abs` decimal(28,10) DEFAULT NULL,
  `spread_bps` decimal(18,8) DEFAULT NULL,
  `ingest_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`ticker_24h_id`),
  UNIQUE KEY `uq_venue_ticker_24h` (`asset_id`,`venue`,`snapshot_ts_utc`),
  KEY `ix_venue_ticker_24h_lookup` (`asset_id`,`venue`,`snapshot_ts_utc`),
  CONSTRAINT `fk_venue_ticker_24h_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `portfolio_state`
--

DROP TABLE IF EXISTS `portfolio_state`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `portfolio_state` (
  `portfolio_state_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `portfolio_ts_utc` datetime(6) NOT NULL,
  `target_action` varchar(32) DEFAULT NULL,
  `target_position_size_pct` decimal(6,4) DEFAULT NULL,
  `portfolio_slot` int(11) DEFAULT NULL,
  `portfolio_bucket` varchar(32) DEFAULT NULL,
  `source_risk_action` varchar(32) DEFAULT NULL,
  `source_decision_action` varchar(32) DEFAULT NULL,
  `portfolio_reasoning` varchar(512) DEFAULT NULL,
  `created_ts_utc` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  PRIMARY KEY (`portfolio_state_id`),
  UNIQUE KEY `uq_portfolio_state` (`asset_id`,`portfolio_ts_utc`),
  KEY `ix_portfolio_slot` (`portfolio_slot`,`target_position_size_pct`),
  CONSTRAINT `fk_portfolio_state_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB AUTO_INCREMENT=375 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `portfolio_target`
--

DROP TABLE IF EXISTS `portfolio_target`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `portfolio_target` (
  `portfolio_target_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `run_ts_utc` datetime NOT NULL,
  `asset_id` int(11) NOT NULL,
  `sleeve_code` varchar(32) NOT NULL,
  `strategy_name` varchar(64) NOT NULL,
  `strategy_version_id` bigint(20) unsigned DEFAULT NULL,
  `desired_action` varchar(32) NOT NULL,
  `target_fraction` decimal(18,8) NOT NULL,
  `decision_strength` varchar(32) DEFAULT NULL,
  `reasoning` text DEFAULT NULL,
  `source_state` varchar(64) DEFAULT NULL,
  `current_price_eur` decimal(28,10) DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`portfolio_target_id`),
  UNIQUE KEY `uq_portfolio_target_run_asset_sleeve` (`run_ts_utc`,`asset_id`,`sleeve_code`),
  KEY `ix_portfolio_target_asset_sleeve` (`asset_id`,`sleeve_code`),
  KEY `fk_portfolio_target_strategy_version` (`strategy_version_id`),
  CONSTRAINT `fk_portfolio_target_strategy_version` FOREIGN KEY (`strategy_version_id`) REFERENCES `strategy_version` (`strategy_version_id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=106 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores per-run target allocations per asset and sleeve before execution.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `position_lot`
--

DROP TABLE IF EXISTS `position_lot`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `position_lot` (
  `position_lot_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `sleeve_code` varchar(32) NOT NULL,
  `strategy_name` varchar(64) NOT NULL,
  `strategy_version_id` bigint(20) unsigned DEFAULT NULL,
  `entry_state` varchar(32) NOT NULL,
  `status` varchar(16) NOT NULL DEFAULT 'OPEN',
  `open_ts_utc` datetime NOT NULL,
  `close_ts_utc` datetime DEFAULT NULL,
  `entry_price_eur` decimal(28,10) NOT NULL,
  `latest_price_eur` decimal(28,10) DEFAULT NULL,
  `target_fraction_at_open` decimal(18,8) NOT NULL,
  `current_fraction` decimal(18,8) NOT NULL,
  `entry_notional_eur` decimal(28,10) NOT NULL,
  `current_notional_eur` decimal(28,10) NOT NULL,
  `realized_pnl_eur` decimal(28,10) NOT NULL DEFAULT 0.0000000000,
  `unrealized_pnl_eur` decimal(28,10) NOT NULL DEFAULT 0.0000000000,
  `quantity_units` decimal(38,18) NOT NULL,
  `entry_reason` text DEFAULT NULL,
  `exit_reason` text DEFAULT NULL,
  `last_transition_state` varchar(32) DEFAULT NULL,
  `last_update_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`position_lot_id`),
  KEY `ix_position_lot_open_asset_sleeve` (`status`,`asset_id`,`sleeve_code`),
  KEY `ix_position_lot_sleeve_status` (`sleeve_code`,`status`),
  KEY `fk_position_lot_strategy_version` (`strategy_version_id`),
  CONSTRAINT `fk_position_lot_strategy_version` FOREIGN KEY (`strategy_version_id`) REFERENCES `strategy_version` (`strategy_version_id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=26 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores open and closed paper position lots for sleeve-aware accounting and lifecycle tracking.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `position_snapshot`
--

DROP TABLE IF EXISTS `position_snapshot`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `position_snapshot` (
  `position_snapshot_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `snapshot_ts_utc` datetime NOT NULL,
  `quantity` decimal(38,18) NOT NULL DEFAULT 0.000000000000000000,
  `avg_entry_price_eur` decimal(28,10) DEFAULT NULL,
  `market_value_eur` decimal(38,10) DEFAULT NULL,
  `unrealized_pnl_eur` decimal(38,10) DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`position_snapshot_id`),
  UNIQUE KEY `uq_position_snapshot` (`asset_id`,`snapshot_ts_utc`),
  KEY `ix_position_snapshot_lookup` (`asset_id`,`snapshot_ts_utc`),
  CONSTRAINT `fk_position_snapshot_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB AUTO_INCREMENT=48 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores portfolio holding snapshots for dashboarding, PnL tracking, and analytics.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `prediction_factor`
--

DROP TABLE IF EXISTS `prediction_factor`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `prediction_factor` (
  `factor_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `pred_id` bigint(20) unsigned NOT NULL,
  `factor_type` varchar(32) NOT NULL,
  `factor_name` varchar(64) NOT NULL,
  `factor_value_text` varchar(255) DEFAULT NULL,
  `factor_value_num` decimal(20,8) DEFAULT NULL,
  `factor_score` decimal(5,2) DEFAULT NULL,
  `factor_weight` decimal(5,2) DEFAULT NULL,
  `evidence_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`evidence_json`)),
  `notes` text DEFAULT NULL,
  PRIMARY KEY (`factor_id`),
  KEY `ix_prediction_factor_pred_type` (`pred_id`,`factor_type`),
  KEY `ix_prediction_factor_type_name` (`factor_type`,`factor_name`),
  CONSTRAINT `fk_prediction_factor_pred` FOREIGN KEY (`pred_id`) REFERENCES `prediction_item` (`pred_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `prediction_item`
--

DROP TABLE IF EXISTS `prediction_item`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `prediction_item` (
  `pred_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `run_id` bigint(20) unsigned NOT NULL,
  `asset_code` varchar(32) NOT NULL,
  `created_ts` datetime(6) NOT NULL,
  `anchor_tf` varchar(16) NOT NULL,
  `horizon_end_ts` datetime(6) NOT NULL,
  `regime_call` varchar(32) DEFAULT NULL,
  `direction_call` varchar(16) DEFAULT NULL,
  `magnitude_call` varchar(32) DEFAULT NULL,
  `timing_call` varchar(32) DEFAULT NULL,
  `target_price` decimal(20,8) DEFAULT NULL,
  `target_currency` varchar(8) DEFAULT 'EUR',
  `invalidation_price` decimal(20,8) DEFAULT NULL,
  `entry_zone_low` decimal(20,8) DEFAULT NULL,
  `entry_zone_high` decimal(20,8) DEFAULT NULL,
  `conviction_total` decimal(5,2) DEFAULT NULL,
  `status` varchar(16) NOT NULL DEFAULT 'open',
  `notes` text DEFAULT NULL,
  PRIMARY KEY (`pred_id`),
  KEY `fk_prediction_item_run` (`run_id`),
  KEY `ix_prediction_item_asset_created` (`asset_code`,`created_ts`),
  KEY `ix_prediction_item_status_end` (`status`,`horizon_end_ts`),
  CONSTRAINT `fk_prediction_item_run` FOREIGN KEY (`run_id`) REFERENCES `prediction_run` (`run_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `prediction_outcome`
--

DROP TABLE IF EXISTS `prediction_outcome`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `prediction_outcome` (
  `outcome_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `pred_id` bigint(20) unsigned NOT NULL,
  `measured_ts` datetime(6) NOT NULL,
  `start_price` decimal(20,8) NOT NULL,
  `end_price` decimal(20,8) NOT NULL,
  `high_price` decimal(20,8) NOT NULL,
  `low_price` decimal(20,8) NOT NULL,
  `return_pct` decimal(10,4) NOT NULL,
  `max_upside_pct` decimal(10,4) DEFAULT NULL,
  `max_drawdown_pct` decimal(10,4) DEFAULT NULL,
  `target_hit` tinyint(1) NOT NULL DEFAULT 0,
  `invalidation_hit` tinyint(1) NOT NULL DEFAULT 0,
  `entry_zone_touched` tinyint(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`outcome_id`),
  UNIQUE KEY `uq_prediction_outcome_pred` (`pred_id`),
  CONSTRAINT `fk_prediction_outcome_pred` FOREIGN KEY (`pred_id`) REFERENCES `prediction_item` (`pred_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `prediction_run`
--

DROP TABLE IF EXISTS `prediction_run`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `prediction_run` (
  `run_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `created_ts` datetime(6) NOT NULL,
  `source` varchar(64) NOT NULL,
  `strategy_name` varchar(64) NOT NULL,
  `timeframe_code` varchar(16) NOT NULL,
  `horizon_days` int(10) unsigned NOT NULL,
  `notes` text DEFAULT NULL,
  PRIMARY KEY (`run_id`),
  KEY `ix_prediction_run_created_ts` (`created_ts`),
  KEY `ix_prediction_run_source` (`source`,`strategy_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `prediction_score`
--

DROP TABLE IF EXISTS `prediction_score`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `prediction_score` (
  `score_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `pred_id` bigint(20) unsigned NOT NULL,
  `scored_ts` datetime(6) NOT NULL,
  `regime_correct` varchar(16) NOT NULL,
  `direction_correct` varchar(16) NOT NULL,
  `timing_correct` varchar(16) NOT NULL,
  `magnitude_correct` varchar(16) NOT NULL,
  `overall_score` decimal(5,2) NOT NULL,
  `outcome_label` varchar(32) DEFAULT NULL,
  `scoring_notes` text DEFAULT NULL,
  PRIMARY KEY (`score_id`),
  UNIQUE KEY `uq_prediction_score_pred` (`pred_id`),
  CONSTRAINT `fk_prediction_score_pred` FOREIGN KEY (`pred_id`) REFERENCES `prediction_item` (`pred_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `prompt_template`
--

DROP TABLE IF EXISTS `prompt_template`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `prompt_template` (
  `prompt_template_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `template_name` varchar(128) NOT NULL,
  `template_type` varchar(64) NOT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT 1,
  `version_num` int(11) NOT NULL DEFAULT 1,
  `body_text` longtext NOT NULL,
  `notes` varchar(255) DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`prompt_template_id`),
  KEY `idx_prompt_template_type` (`template_type`),
  KEY `idx_prompt_template_active` (`is_active`),
  KEY `idx_prompt_template_created` (`created_ts_utc`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ranking_state`
--

DROP TABLE IF EXISTS `ranking_state`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `ranking_state` (
  `ranking_state_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `venue` varchar(50) NOT NULL,
  `interval_code` varchar(10) NOT NULL,
  `asof_ts_utc` datetime NOT NULL,
  `trade_quality_score` decimal(18,8) DEFAULT NULL,
  `relative_strength_score` decimal(18,8) DEFAULT NULL,
  `context_score` decimal(18,8) DEFAULT NULL,
  `pullback_quality_score` decimal(18,8) DEFAULT NULL,
  `expansion_position_score` decimal(18,8) DEFAULT NULL,
  `signal_confidence_score` decimal(18,8) DEFAULT NULL,
  `rotation_bucket` varchar(32) DEFAULT NULL,
  `classification_code` varchar(32) DEFAULT NULL,
  `sleeve_fit_code` varchar(32) DEFAULT NULL,
  `final_rank` int(11) DEFAULT NULL,
  `ranking_version` varchar(32) NOT NULL,
  `notes` varchar(255) DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT utc_timestamp(),
  PRIMARY KEY (`ranking_state_id`),
  UNIQUE KEY `uq_ranking_state_snapshot` (`asset_id`,`venue`,`interval_code`,`asof_ts_utc`,`ranking_version`),
  KEY `idx_ranking_state_interval_rank` (`interval_code`,`asof_ts_utc`,`final_rank`),
  KEY `idx_ranking_state_bucket` (`interval_code`,`asof_ts_utc`,`rotation_bucket`)
) ENGINE=InnoDB AUTO_INCREMENT=340 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `relative_strength_snapshot`
--

DROP TABLE IF EXISTS `relative_strength_snapshot`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `relative_strength_snapshot` (
  `relative_strength_snapshot_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `snapshot_ts_utc` datetime NOT NULL,
  `asset_id` int(11) NOT NULL,
  `lookback_days` int(11) NOT NULL,
  `return_pct` decimal(18,8) NOT NULL,
  `rank_value` int(11) NOT NULL,
  `universe_size` int(11) NOT NULL,
  `rank_pct` decimal(18,8) NOT NULL,
  `zscore` decimal(18,8) NOT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`relative_strength_snapshot_id`),
  UNIQUE KEY `uq_relative_strength_snapshot` (`snapshot_ts_utc`,`asset_id`,`lookback_days`),
  KEY `ix_relative_strength_asset_lookback_ts` (`asset_id`,`lookback_days`,`snapshot_ts_utc`)
) ENGINE=InnoDB AUTO_INCREMENT=153 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores cross-asset relative strength rankings for fixed lookback windows.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `risk_state`
--

DROP TABLE IF EXISTS `risk_state`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `risk_state` (
  `risk_state_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `risk_ts_utc` datetime(6) NOT NULL,
  `decision_action` varchar(32) DEFAULT NULL,
  `decision_strength` varchar(16) DEFAULT NULL,
  `raw_position_size_pct` decimal(6,4) DEFAULT NULL,
  `risk_action` varchar(32) DEFAULT NULL,
  `approved_position_size_pct` decimal(6,4) DEFAULT NULL,
  `portfolio_slot` int(11) DEFAULT NULL,
  `portfolio_bucket` varchar(32) DEFAULT NULL,
  `risk_reasoning` varchar(512) DEFAULT NULL,
  `created_ts_utc` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  PRIMARY KEY (`risk_state_id`),
  UNIQUE KEY `uq_risk_state` (`asset_id`,`risk_ts_utc`),
  KEY `ix_risk_action` (`risk_action`,`approved_position_size_pct`),
  CONSTRAINT `fk_risk_state_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB AUTO_INCREMENT=591 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores applied risk filters and constraints per asset and sleeve before execution.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `sector`
--

DROP TABLE IF EXISTS `sector`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `sector` (
  `sector_id` int(11) NOT NULL AUTO_INCREMENT,
  `sector_code` varchar(64) NOT NULL,
  `sector_name` varchar(128) NOT NULL,
  `is_enabled` tinyint(1) NOT NULL DEFAULT 1,
  `sort_order` int(11) NOT NULL DEFAULT 0,
  `notes` text DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_ts_utc` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`sector_id`),
  UNIQUE KEY `uq_sector_code` (`sector_code`),
  KEY `ix_sector_enabled` (`is_enabled`),
  KEY `ix_sector_sort_order` (`sort_order`)
) ENGINE=InnoDB AUTO_INCREMENT=16 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `sector_regime`
--

DROP TABLE IF EXISTS `sector_regime`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `sector_regime` (
  `sector_regime_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `sector_id` int(11) NOT NULL,
  `ts_utc` datetime NOT NULL,
  `timeframe` varchar(16) NOT NULL,
  `regime_label` varchar(64) NOT NULL,
  `confidence_score` decimal(10,6) DEFAULT NULL,
  `persistence_bars` int(11) NOT NULL DEFAULT 0,
  `rank_in_market` int(11) DEFAULT NULL,
  `reason_code` varchar(128) DEFAULT NULL,
  `summary_text` varchar(512) DEFAULT NULL,
  `sector_snapshot_id` bigint(20) unsigned DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`sector_regime_id`),
  UNIQUE KEY `uq_sector_regime` (`sector_id`,`timeframe`,`ts_utc`),
  KEY `ix_sector_regime_lookup` (`sector_id`,`timeframe`,`ts_utc`),
  KEY `ix_sector_regime_label` (`regime_label`),
  KEY `ix_sector_regime_rank` (`timeframe`,`ts_utc`,`rank_in_market`),
  KEY `fk_sector_regime_snapshot` (`sector_snapshot_id`),
  CONSTRAINT `fk_sector_regime_sector` FOREIGN KEY (`sector_id`) REFERENCES `sector` (`sector_id`),
  CONSTRAINT `fk_sector_regime_snapshot` FOREIGN KEY (`sector_snapshot_id`) REFERENCES `sector_snapshot` (`sector_snapshot_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores interpreted sector regimes (expansion, contraction, rotation, etc.).';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `sector_snapshot`
--

DROP TABLE IF EXISTS `sector_snapshot`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `sector_snapshot` (
  `sector_snapshot_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `sector_id` int(11) NOT NULL,
  `ts_utc` datetime NOT NULL,
  `timeframe` varchar(16) NOT NULL,
  `mapped_asset_count` int(11) NOT NULL DEFAULT 0,
  `active_asset_count` int(11) NOT NULL DEFAULT 0,
  `coin_count` int(11) NOT NULL DEFAULT 0,
  `coins_up_count` int(11) NOT NULL DEFAULT 0,
  `coins_down_count` int(11) NOT NULL DEFAULT 0,
  `breadth_ratio` decimal(18,8) DEFAULT NULL,
  `weighted_return_pct` decimal(18,8) DEFAULT NULL,
  `avg_return_pct` decimal(18,8) DEFAULT NULL,
  `volume_ratio` decimal(18,8) DEFAULT NULL,
  `persistence_score` decimal(18,8) DEFAULT NULL,
  `weighted_return_score` decimal(18,8) DEFAULT NULL,
  `breadth_score` decimal(18,8) DEFAULT NULL,
  `volume_score` decimal(18,8) DEFAULT NULL,
  `persistence_component_score` decimal(18,8) DEFAULT NULL,
  `sector_score` decimal(18,8) DEFAULT NULL,
  `market_baseline_score` decimal(18,8) DEFAULT NULL,
  `market_relative_score` decimal(18,8) DEFAULT NULL,
  `leader_asset_id` int(11) DEFAULT NULL,
  `laggard_asset_id` int(11) DEFAULT NULL,
  `leader_return_pct` decimal(18,8) DEFAULT NULL,
  `laggard_return_pct` decimal(18,8) DEFAULT NULL,
  `summary_text` varchar(512) DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`sector_snapshot_id`),
  UNIQUE KEY `uq_sector_snapshot` (`sector_id`,`timeframe`,`ts_utc`),
  KEY `ix_sector_snapshot_lookup` (`sector_id`,`timeframe`,`ts_utc`),
  KEY `ix_sector_snapshot_rank` (`timeframe`,`ts_utc`,`sector_score`),
  KEY `ix_sector_snapshot_market_rel` (`timeframe`,`ts_utc`,`market_relative_score`),
  KEY `fk_sector_snapshot_leader_asset` (`leader_asset_id`),
  KEY `fk_sector_snapshot_laggard_asset` (`laggard_asset_id`),
  CONSTRAINT `fk_sector_snapshot_laggard_asset` FOREIGN KEY (`laggard_asset_id`) REFERENCES `asset` (`asset_id`),
  CONSTRAINT `fk_sector_snapshot_leader_asset` FOREIGN KEY (`leader_asset_id`) REFERENCES `asset` (`asset_id`),
  CONSTRAINT `fk_sector_snapshot_sector` FOREIGN KEY (`sector_id`) REFERENCES `sector` (`sector_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores sector-level aggregates such as momentum, volume, and leadership signals.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `selection_state`
--

DROP TABLE IF EXISTS `selection_state`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `selection_state` (
  `selection_state_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `venue` varchar(32) NOT NULL DEFAULT 'bitvavo',
  `asof_ts_utc` datetime(6) NOT NULL,
  `advice_ts_1h_utc` datetime(6) DEFAULT NULL,
  `advice_ts_4h_utc` datetime(6) DEFAULT NULL,
  `selection_state` varchar(64) DEFAULT NULL,
  `selection_bias` varchar(32) DEFAULT NULL,
  `selection_score` decimal(10,6) DEFAULT NULL,
  `regime_label_1h` varchar(64) DEFAULT NULL,
  `regime_label_4h` varchar(64) DEFAULT NULL,
  `advice_state_1h` varchar(32) DEFAULT NULL,
  `advice_state_4h` varchar(32) DEFAULT NULL,
  `opportunity_score_1h` decimal(10,6) DEFAULT NULL,
  `opportunity_score_4h` decimal(10,6) DEFAULT NULL,
  `risk_score_1h` decimal(10,6) DEFAULT NULL,
  `risk_score_4h` decimal(10,6) DEFAULT NULL,
  `priority_rank` int(11) DEFAULT NULL,
  `summary_text` varchar(512) DEFAULT NULL,
  `engine_name` varchar(64) DEFAULT 'selection_engine',
  `engine_version` varchar(16) DEFAULT '1.0',
  `created_ts_utc` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  PRIMARY KEY (`selection_state_id`),
  UNIQUE KEY `uq_selection_state` (`asset_id`,`venue`,`asof_ts_utc`),
  KEY `ix_selection_rank` (`selection_state`,`selection_score`),
  KEY `ix_selection_lookup` (`asset_id`,`asof_ts_utc`),
  CONSTRAINT `fk_selection_state_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB AUTO_INCREMENT=485 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores pre-strategy selection filtering results (eligibility, ranking, gating).';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `signal_engine_state`
--

DROP TABLE IF EXISTS `signal_engine_state`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `signal_engine_state` (
  `signal_engine_state_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `venue` varchar(32) NOT NULL DEFAULT 'bitvavo',
  `interval_code` varchar(16) NOT NULL,
  `signal_ts_utc` datetime(6) NOT NULL,
  `trend_signal` varchar(64) DEFAULT NULL,
  `volume_signal` varchar(64) DEFAULT NULL,
  `phase_signal` varchar(64) DEFAULT NULL,
  `compass_signal` varchar(64) DEFAULT NULL,
  `rotation_signal` varchar(64) DEFAULT NULL,
  `relative_signal` varchar(64) DEFAULT NULL,
  `setup_signal` varchar(64) DEFAULT NULL,
  `risk_signal` varchar(64) DEFAULT NULL,
  `expansion_delay_state` tinyint(1) NOT NULL DEFAULT 0,
  `expansion_delay_score` decimal(10,6) DEFAULT NULL,
  `rotation_trigger_state` tinyint(1) NOT NULL DEFAULT 0,
  `rotation_trigger_score` decimal(10,6) DEFAULT NULL,
  `trend_score` decimal(10,6) DEFAULT NULL,
  `volume_score` decimal(10,6) DEFAULT NULL,
  `phase_score` decimal(10,6) DEFAULT NULL,
  `compass_score` decimal(10,6) DEFAULT NULL,
  `rotation_score` decimal(10,6) DEFAULT NULL,
  `relative_score` decimal(10,6) DEFAULT NULL,
  `setup_score` decimal(10,6) DEFAULT NULL,
  `risk_score` decimal(10,6) DEFAULT NULL,
  `signal_confidence` decimal(10,6) DEFAULT NULL,
  `reason_code` varchar(128) DEFAULT NULL,
  `reason_text` varchar(512) DEFAULT NULL,
  `engine_name` varchar(64) DEFAULT 'signal_engine',
  `created_ts_utc` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  `engine_version` varchar(16) DEFAULT '1.0',
  `expansion_position_score` decimal(10,6) DEFAULT NULL,
  `pullback_quality_score` decimal(10,6) DEFAULT NULL,
  `late_trend_flag` tinyint(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`signal_engine_state_id`),
  UNIQUE KEY `uq_signal_engine_state` (`asset_id`,`venue`,`interval_code`,`signal_ts_utc`),
  KEY `ix_signal_engine_state_lookup` (`asset_id`,`venue`,`interval_code`,`signal_ts_utc`),
  KEY `ix_time` (`signal_ts_utc`),
  KEY `ix_setup` (`setup_signal`,`signal_confidence`),
  KEY `ix_rotation` (`rotation_signal`,`rotation_trigger_state`),
  KEY `ix_risk` (`risk_signal`),
  KEY `idx_signal_engine_late_trend` (`late_trend_flag`),
  KEY `idx_signal_engine_expansion_pos` (`expansion_position_score`),
  KEY `idx_signal_engine_pullback_quality` (`pullback_quality_score`),
  CONSTRAINT `fk_signal_engine_state_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB AUTO_INCREMENT=850 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores combined multi-signal state vectors used for ranking, allocation, and strategy context.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `signal_state`
--

DROP TABLE IF EXISTS `signal_state`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `signal_state` (
  `signal_state_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `venue` varchar(32) NOT NULL DEFAULT 'bitvavo',
  `interval_code` varchar(16) NOT NULL,
  `candle_id` bigint(20) unsigned NOT NULL,
  `close_ts_utc` datetime NOT NULL,
  `trend_signal` varchar(32) DEFAULT NULL,
  `momentum_signal` varchar(32) DEFAULT NULL,
  `volume_signal` varchar(32) DEFAULT NULL,
  `volatility_signal` varchar(32) DEFAULT NULL,
  `setup_signal` varchar(32) DEFAULT NULL,
  `risk_signal` varchar(32) DEFAULT NULL,
  `trend_score` decimal(18,8) DEFAULT NULL,
  `momentum_score` decimal(18,8) DEFAULT NULL,
  `volume_score` decimal(18,8) DEFAULT NULL,
  `volatility_score` decimal(18,8) DEFAULT NULL,
  `setup_score` decimal(18,8) DEFAULT NULL,
  `risk_score` decimal(18,8) DEFAULT NULL,
  `summary_bias` varchar(32) DEFAULT NULL,
  `summary_score` decimal(18,8) DEFAULT NULL,
  `updated_ts_utc` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`signal_state_id`),
  UNIQUE KEY `uq_signal_state` (`asset_id`,`venue`,`interval_code`),
  KEY `ix_signal_state_lookup` (`venue`,`interval_code`,`close_ts_utc`),
  KEY `fk_signal_state_candle` (`candle_id`),
  CONSTRAINT `fk_signal_state_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`),
  CONSTRAINT `fk_signal_state_candle` FOREIGN KEY (`candle_id`) REFERENCES `obs_market_candle` (`candle_id`)
) ENGINE=InnoDB AUTO_INCREMENT=202 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores intermediate signal engine outputs before aggregation into strategy signals.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `state_transition_daily`
--

DROP TABLE IF EXISTS `state_transition_daily`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `state_transition_daily` (
  `state_transition_daily_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `metric_date_utc` date NOT NULL,
  `sleeve_code` varchar(32) NOT NULL,
  `strategy_name` varchar(64) NOT NULL,
  `from_state` varchar(32) NOT NULL,
  `to_state` varchar(32) NOT NULL,
  `transition_count` int(11) NOT NULL DEFAULT 0,
  `avg_forward_return_24h_pct` decimal(18,8) NOT NULL DEFAULT 0.00000000,
  `avg_forward_return_72h_pct` decimal(18,8) NOT NULL DEFAULT 0.00000000,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`state_transition_daily_id`),
  UNIQUE KEY `uq_state_transition_daily` (`metric_date_utc`,`sleeve_code`,`strategy_name`,`from_state`,`to_state`)
) ENGINE=InnoDB AUTO_INCREMENT=48 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores daily aggregated state transition counts (e.g. PREPARE -> ENTER_LONG) for strategy evaluation.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `strategy_metrics_daily`
--

DROP TABLE IF EXISTS `strategy_metrics_daily`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `strategy_metrics_daily` (
  `strategy_metrics_daily_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `metric_date_utc` date NOT NULL,
  `sleeve_code` varchar(32) NOT NULL,
  `strategy_name` varchar(64) NOT NULL,
  `strategy_version_id` bigint(20) unsigned DEFAULT NULL,
  `trades_closed` int(11) NOT NULL DEFAULT 0,
  `wins` int(11) NOT NULL DEFAULT 0,
  `losses` int(11) NOT NULL DEFAULT 0,
  `win_rate` decimal(18,8) NOT NULL DEFAULT 0.00000000,
  `avg_realized_pnl_pct` decimal(18,8) NOT NULL DEFAULT 0.00000000,
  `avg_realized_pnl_eur` decimal(28,10) NOT NULL DEFAULT 0.0000000000,
  `gross_profit_eur` decimal(28,10) NOT NULL DEFAULT 0.0000000000,
  `gross_loss_eur` decimal(28,10) NOT NULL DEFAULT 0.0000000000,
  `profit_factor` decimal(18,8) NOT NULL DEFAULT 0.00000000,
  `avg_holding_minutes` decimal(18,4) NOT NULL DEFAULT 0.0000,
  `prepare_to_enter_count` int(11) NOT NULL DEFAULT 0,
  `prepare_fail_count` int(11) NOT NULL DEFAULT 0,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`strategy_metrics_daily_id`),
  UNIQUE KEY `uq_strategy_metrics_daily` (`metric_date_utc`,`sleeve_code`,`strategy_name`,`strategy_version_id`),
  KEY `fk_strategy_metrics_daily_strategy_version` (`strategy_version_id`),
  CONSTRAINT `fk_strategy_metrics_daily_strategy_version` FOREIGN KEY (`strategy_version_id`) REFERENCES `strategy_version` (`strategy_version_id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores daily aggregated performance metrics per strategy and sleeve.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `strategy_param_override`
--

DROP TABLE IF EXISTS `strategy_param_override`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `strategy_param_override` (
  `strategy_param_override_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `strategy_name` varchar(100) NOT NULL,
  `symbol` varchar(32) DEFAULT NULL,
  `asset_class` varchar(20) DEFAULT NULL,
  `param_name` varchar(64) NOT NULL,
  `param_value` varchar(255) NOT NULL,
  `is_enabled` tinyint(1) NOT NULL DEFAULT 1,
  `notes` varchar(255) DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT utc_timestamp(),
  PRIMARY KEY (`strategy_param_override_id`),
  KEY `idx_strategy_param_override_lookup` (`strategy_name`,`symbol`,`asset_class`,`param_name`,`is_enabled`)
) ENGINE=InnoDB AUTO_INCREMENT=9 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `strategy_signal`
--

DROP TABLE IF EXISTS `strategy_signal`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `strategy_signal` (
  `strategy_signal_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `venue` varchar(32) DEFAULT 'bitvavo',
  `interval_code` varchar(16) DEFAULT NULL,
  `signal_ts_utc` datetime NOT NULL,
  `strategy_name` varchar(128) NOT NULL,
  `signal_state` varchar(64) NOT NULL,
  `confidence_score` decimal(10,6) DEFAULT NULL,
  `reason_code` varchar(128) DEFAULT NULL,
  `trend_strength_state` varchar(64) DEFAULT NULL,
  `price_volume_state` varchar(64) DEFAULT NULL,
  `phase_state` varchar(64) DEFAULT NULL,
  `interpreter_state_id` bigint(20) unsigned DEFAULT NULL,
  `summary_text` varchar(512) DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  `signal_engine_state_id` bigint(20) unsigned DEFAULT NULL,
  PRIMARY KEY (`strategy_signal_id`),
  UNIQUE KEY `uq_strategy_signal` (`asset_id`,`strategy_name`,`venue`,`interval_code`,`signal_ts_utc`),
  KEY `ix_strategy_signal_lookup` (`asset_id`,`strategy_name`,`signal_ts_utc`),
  KEY `ix_strategy_signal_state` (`signal_state`),
  KEY `fk_strategy_signal_interpreter_state` (`interpreter_state_id`),
  KEY `fk_strategy_signal_engine_state` (`signal_engine_state_id`),
  CONSTRAINT `fk_strategy_signal_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`),
  CONSTRAINT `fk_strategy_signal_engine_state` FOREIGN KEY (`signal_engine_state_id`) REFERENCES `signal_engine_state` (`signal_engine_state_id`),
  CONSTRAINT `fk_strategy_signal_interpreter_state` FOREIGN KEY (`interpreter_state_id`) REFERENCES `interpreter_state` (`interpreter_state_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores strategy module outputs before final decision and risk handling.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `strategy_signal_context`
--

DROP TABLE IF EXISTS `strategy_signal_context`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `strategy_signal_context` (
  `strategy_signal_context_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `strategy_signal_id` bigint(20) unsigned DEFAULT NULL,
  `asset_id` int(11) NOT NULL,
  `interval_code` varchar(16) NOT NULL,
  `context_ts_utc` datetime NOT NULL,
  `zone_state` varchar(32) NOT NULL DEFAULT 'NONE',
  `fib_state` varchar(32) NOT NULL DEFAULT 'NONE',
  `wave_label` varchar(8) DEFAULT NULL,
  `wave_confidence` decimal(18,8) DEFAULT NULL,
  `zone_confluence_score` decimal(18,8) NOT NULL DEFAULT 0.00000000,
  `fib_confluence_score` decimal(18,8) NOT NULL DEFAULT 0.00000000,
  `context_score` decimal(18,8) NOT NULL DEFAULT 0.00000000,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_ts_utc` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  `volume_ratio` decimal(18,8) DEFAULT NULL,
  `volume_zscore` decimal(18,8) DEFAULT NULL,
  `volume_state` varchar(32) DEFAULT NULL,
  `volume_alignment_score` decimal(18,8) DEFAULT NULL,
  `distance_to_support` decimal(28,10) DEFAULT NULL,
  `distance_to_resistance` decimal(28,10) DEFAULT NULL,
  `distance_to_support_bps` decimal(18,8) DEFAULT NULL,
  `distance_to_resistance_bps` decimal(18,8) DEFAULT NULL,
  `fib_level` decimal(6,3) DEFAULT NULL,
  `fib_price` decimal(28,10) DEFAULT NULL,
  `fib_distance_bps` decimal(18,8) DEFAULT NULL,
  PRIMARY KEY (`strategy_signal_context_id`),
  UNIQUE KEY `uq_strategy_signal_context` (`asset_id`,`interval_code`,`context_ts_utc`),
  KEY `ix_strategy_signal_context_lookup` (`asset_id`,`interval_code`,`context_ts_utc`)
) ENGINE=InnoDB AUTO_INCREMENT=914 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Context bridge from zones/fib/waves into strategy-consumable structure.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `strategy_version`
--

DROP TABLE IF EXISTS `strategy_version`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `strategy_version` (
  `strategy_version_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `strategy_name` varchar(64) NOT NULL,
  `sleeve_code` varchar(32) NOT NULL,
  `version_label` varchar(128) NOT NULL,
  `version_hash` char(64) NOT NULL,
  `config_json` longtext DEFAULT NULL,
  `notes` text DEFAULT NULL,
  `activated_ts_utc` datetime NOT NULL,
  `deactivated_ts_utc` datetime DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`strategy_version_id`),
  UNIQUE KEY `uq_strategy_version_hash` (`strategy_name`,`version_hash`),
  KEY `ix_strategy_version_name_active` (`strategy_name`,`activated_ts_utc`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores active and historical strategy versions with config hash, label, and activation timestamp.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `structure_state`
--

DROP TABLE IF EXISTS `structure_state`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `structure_state` (
  `structure_state_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NOT NULL,
  `venue` varchar(32) NOT NULL DEFAULT 'bitvavo',
  `interval_code` varchar(8) NOT NULL,
  `asof_ts_utc` datetime(6) NOT NULL,
  `trend_state` varchar(32) DEFAULT NULL,
  `pullback_state` varchar(32) DEFAULT NULL,
  `reclaim_state` varchar(32) DEFAULT NULL,
  `trend_score` decimal(10,6) DEFAULT NULL,
  `pullback_score` decimal(10,6) DEFAULT NULL,
  `reclaim_score` decimal(10,6) DEFAULT NULL,
  `engine_name` varchar(64) NOT NULL DEFAULT 'structure_state_engine',
  `engine_version` varchar(16) NOT NULL DEFAULT '1.0',
  `created_ts_utc` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  PRIMARY KEY (`structure_state_id`),
  UNIQUE KEY `uq_structure_state_snapshot` (`asset_id`,`venue`,`interval_code`,`asof_ts_utc`,`engine_name`,`engine_version`),
  KEY `ix_structure_state_lookup` (`interval_code`,`asof_ts_utc`,`trend_state`,`pullback_state`),
  CONSTRAINT `fk_structure_state_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB AUTO_INCREMENT=508 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `synth_watchlist`
--

DROP TABLE IF EXISTS `synth_watchlist`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `synth_watchlist` (
  `asset_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `token` varchar(20) NOT NULL,
  `bucket` varchar(50) NOT NULL,
  `current_phase` varchar(50) DEFAULT NULL,
  `next_phase` varchar(50) DEFAULT NULL,
  `priority_tier` char(1) DEFAULT NULL,
  `profit_take_warning` tinyint(1) NOT NULL DEFAULT 0,
  `unknown_interest_flag` tinyint(1) NOT NULL DEFAULT 0,
  `notes` text DEFAULT NULL,
  `created_ts` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`asset_id`),
  KEY `idx_synth_watchlist_bucket_token` (`bucket`,`token`),
  KEY `idx_synth_watchlist_profit_take_warning` (`profit_take_warning`)
) ENGINE=InnoDB AUTO_INCREMENT=36 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `thesis_bias`
--

DROP TABLE IF EXISTS `thesis_bias`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `thesis_bias` (
  `thesis_bias_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) DEFAULT NULL,
  `scope_symbol` varchar(32) DEFAULT NULL,
  `scope_group` varchar(64) DEFAULT NULL,
  `source_type` varchar(64) NOT NULL,
  `bias_direction` varchar(64) NOT NULL,
  `bias_strength` varchar(64) NOT NULL,
  `time_horizon` varchar(64) DEFAULT NULL,
  `active_from_ts_utc` datetime NOT NULL,
  `active_until_ts_utc` datetime DEFAULT NULL,
  `notes` text DEFAULT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT 1,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_ts_utc` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`thesis_bias_id`),
  KEY `ix_thesis_bias_asset_active` (`asset_id`,`is_active`,`active_from_ts_utc`),
  KEY `ix_thesis_bias_scope_active` (`scope_symbol`,`is_active`,`active_from_ts_utc`),
  KEY `ix_thesis_bias_source` (`source_type`),
  KEY `ix_thesis_bias_direction` (`bias_direction`),
  CONSTRAINT `fk_thesis_bias_asset` FOREIGN KEY (`asset_id`) REFERENCES `asset` (`asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `trade_lot`
--

DROP TABLE IF EXISTS `trade_lot`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `trade_lot` (
  `trade_lot_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `position_lot_id` bigint(20) unsigned NOT NULL,
  `asset_id` int(11) NOT NULL,
  `sleeve_code` varchar(32) NOT NULL,
  `strategy_name` varchar(64) NOT NULL,
  `strategy_version_id` bigint(20) unsigned DEFAULT NULL,
  `entry_state` varchar(32) NOT NULL,
  `exit_state` varchar(32) DEFAULT NULL,
  `open_ts_utc` datetime NOT NULL,
  `close_ts_utc` datetime NOT NULL,
  `entry_price_eur` decimal(28,10) NOT NULL,
  `exit_price_eur` decimal(28,10) NOT NULL,
  `entry_notional_eur` decimal(28,10) NOT NULL,
  `exit_notional_eur` decimal(28,10) NOT NULL,
  `quantity_units` decimal(38,18) NOT NULL,
  `realized_pnl_eur` decimal(28,10) NOT NULL,
  `realized_pnl_pct` decimal(18,8) NOT NULL,
  `holding_minutes` int(11) NOT NULL,
  `entry_reason` text DEFAULT NULL,
  `exit_reason` text DEFAULT NULL,
  `created_ts_utc` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`trade_lot_id`),
  KEY `ix_trade_lot_close_ts` (`close_ts_utc`),
  KEY `ix_trade_lot_strategy_sleeve` (`strategy_name`,`sleeve_code`,`close_ts_utc`),
  KEY `fk_trade_lot_position_lot` (`position_lot_id`),
  KEY `fk_trade_lot_strategy_version` (`strategy_version_id`),
  CONSTRAINT `fk_trade_lot_position_lot` FOREIGN KEY (`position_lot_id`) REFERENCES `position_lot` (`position_lot_id`) ON UPDATE CASCADE,
  CONSTRAINT `fk_trade_lot_strategy_version` FOREIGN KEY (`strategy_version_id`) REFERENCES `strategy_version` (`strategy_version_id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=17 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Stores closed lot ledger entries with realized PnL and holding duration.';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Temporary table structure for view `v_asset_sector_map_active`
--

DROP TABLE IF EXISTS `v_asset_sector_map_active`;
/*!50001 DROP VIEW IF EXISTS `v_asset_sector_map_active`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `v_asset_sector_map_active` AS SELECT
 1 AS `asset_sector_map_id`,
  1 AS `asset_id`,
  1 AS `sector_id`,
  1 AS `weight`,
  1 AS `classification_type`,
  1 AS `source_label`,
  1 AS `valid_from_ts_utc`,
  1 AS `valid_to_ts_utc`,
  1 AS `sector_code`,
  1 AS `sector_name` */;
SET character_set_client = @saved_cs_client;

--
-- Temporary table structure for view `v_breathline_alpha_candidates`
--

DROP TABLE IF EXISTS `v_breathline_alpha_candidates`;
/*!50001 DROP VIEW IF EXISTS `v_breathline_alpha_candidates`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `v_breathline_alpha_candidates` AS SELECT
 1 AS `token`,
  1 AS `current_phase`,
  1 AS `next_phase`,
  1 AS `phase_offset`,
  1 AS `lead_lag_status`,
  1 AS `alpha_signal`,
  1 AS `lagging_setup` */;
SET character_set_client = @saved_cs_client;

--
-- Temporary table structure for view `v_breathline_cycle_bucket`
--

DROP TABLE IF EXISTS `v_breathline_cycle_bucket`;
/*!50001 DROP VIEW IF EXISTS `v_breathline_cycle_bucket`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `v_breathline_cycle_bucket` AS SELECT
 1 AS `token`,
  1 AS `current_phase`,
  1 AS `next_phase`,
  1 AS `cycle_bucket` */;
SET character_set_client = @saved_cs_client;

--
-- Temporary table structure for view `v_breathline_trade_radar`
--

DROP TABLE IF EXISTS `v_breathline_trade_radar`;
/*!50001 DROP VIEW IF EXISTS `v_breathline_trade_radar`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `v_breathline_trade_radar` AS SELECT
 1 AS `token`,
  1 AS `bucket`,
  1 AS `current_phase`,
  1 AS `next_phase`,
  1 AS `priority_tier`,
  1 AS `profit_take_warning`,
  1 AS `unknown_interest_flag`,
  1 AS `projection_scope`,
  1 AS `projection_window`,
  1 AS `projection_current_phase_raw`,
  1 AS `projection_current_phase_norm`,
  1 AS `projected_value_raw`,
  1 AS `projected_range_raw`,
  1 AS `breathline_status`,
  1 AS `no_data_reason`,
  1 AS `trade_radar_signal` */;
SET character_set_client = @saved_cs_client;

--
-- Temporary table structure for view `v_context_volume_overview`
--

DROP TABLE IF EXISTS `v_context_volume_overview`;
/*!50001 DROP VIEW IF EXISTS `v_context_volume_overview`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `v_context_volume_overview` AS SELECT
 1 AS `symbol`,
  1 AS `asset_id`,
  1 AS `interval_code`,
  1 AS `context_ts_utc`,
  1 AS `selection_state`,
  1 AS `selection_score`,
  1 AS `core_action`,
  1 AS `core_target_fraction`,
  1 AS `swing_action`,
  1 AS `swing_target_fraction`,
  1 AS `volume_ratio`,
  1 AS `volume_zscore`,
  1 AS `volume_state`,
  1 AS `volume_alignment_score` */;
SET character_set_client = @saved_cs_client;

--
-- Temporary table structure for view `v_crypto_breakout_radar`
--

DROP TABLE IF EXISTS `v_crypto_breakout_radar`;
/*!50001 DROP VIEW IF EXISTS `v_crypto_breakout_radar`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `v_crypto_breakout_radar` AS SELECT
 1 AS `token`,
  1 AS `current_phase`,
  1 AS `next_phase`,
  1 AS `breakout_signal` */;
SET character_set_client = @saved_cs_client;

--
-- Temporary table structure for view `v_execution_board`
--

DROP TABLE IF EXISTS `v_execution_board`;
/*!50001 DROP VIEW IF EXISTS `v_execution_board`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `v_execution_board` AS SELECT
 1 AS `asset_id`,
  1 AS `symbol`,
  1 AS `name`,
  1 AS `previous_position_size_pct`,
  1 AS `target_position_size_pct`,
  1 AS `size_delta_pct`,
  1 AS `intent_action`,
  1 AS `intent_priority`,
  1 AS `intent_reasoning` */;
SET character_set_client = @saved_cs_client;

--
-- Temporary table structure for view `v_execution_intent_latest`
--

DROP TABLE IF EXISTS `v_execution_intent_latest`;
/*!50001 DROP VIEW IF EXISTS `v_execution_intent_latest`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `v_execution_intent_latest` AS SELECT
 1 AS `execution_intent_id`,
  1 AS `asset_id`,
  1 AS `intent_ts_utc`,
  1 AS `previous_position_size_pct`,
  1 AS `target_position_size_pct`,
  1 AS `size_delta_pct`,
  1 AS `intent_action`,
  1 AS `intent_priority`,
  1 AS `intent_reasoning`,
  1 AS `created_ts_utc` */;
SET character_set_client = @saved_cs_client;

--
-- Temporary table structure for view `v_execution_intent_latest_with_symbol`
--

DROP TABLE IF EXISTS `v_execution_intent_latest_with_symbol`;
/*!50001 DROP VIEW IF EXISTS `v_execution_intent_latest_with_symbol`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `v_execution_intent_latest_with_symbol` AS SELECT
 1 AS `asset_id`,
  1 AS `symbol`,
  1 AS `name`,
  1 AS `intent_ts_utc`,
  1 AS `previous_position_size_pct`,
  1 AS `target_position_size_pct`,
  1 AS `size_delta_pct`,
  1 AS `intent_action`,
  1 AS `intent_priority`,
  1 AS `intent_reasoning`,
  1 AS `created_ts_utc` */;
SET character_set_client = @saved_cs_client;

--
-- Temporary table structure for view `v_harmonic_price_magnet_eur`
--

DROP TABLE IF EXISTS `v_harmonic_price_magnet_eur`;
/*!50001 DROP VIEW IF EXISTS `v_harmonic_price_magnet_eur`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `v_harmonic_price_magnet_eur` AS SELECT
 1 AS `token`,
  1 AS `tf`,
  1 AS `current_price_eur`,
  1 AS `nearest_node`,
  1 AS `node_label`,
  1 AS `distance_ratio`,
  1 AS `magnet_state_eur` */;
SET character_set_client = @saved_cs_client;

--
-- Temporary table structure for view `v_harmonic_price_magnet_usd`
--

DROP TABLE IF EXISTS `v_harmonic_price_magnet_usd`;
