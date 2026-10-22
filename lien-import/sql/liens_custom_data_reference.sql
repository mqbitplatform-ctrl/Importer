-- Reference DDL for the production `liens_custom_data` table in zm_dba.
--
-- Copied from `SHOW CREATE TABLE liens_custom_data` on a restored copy of
-- zm_dba (2026-10). This is the EXISTING table Zairmail uses to record which
-- customer each lien was pulled for - one row per (lien, customer):
--
--   61379  Free America Tax       lcdata_name = 'FREEAMTAX Case ID',
--                                 lcdata_value = the Case ID (from Logics)
--   61017  Protection Tax
--   60275  Tax Network USA (TNU)
--   60243  Elite Sales Solutions (ESS)
--
-- The FAT pull (`fat-analyze` / `fat-pull`) reads it for "not already
-- assigned" and writes one row per pulled lien, exactly like the manual
-- process. NOT run against production - only for local throwaway copies.

CREATE TABLE IF NOT EXISTS liens_custom_data (
  `lcdata_lien_source` char(2) NOT NULL,
  `lcdata_lien_id` varchar(15) NOT NULL,
  `lcdata_user_index` bigint(10) NOT NULL,
  `lcdata_name` varchar(30) DEFAULT NULL,
  `lcdata_value` varchar(30) DEFAULT NULL,
  `lcdata_info` varchar(100) DEFAULT NULL,
  `lcdata_last_used` datetime DEFAULT NULL,
  PRIMARY KEY (`lcdata_lien_source`,`lcdata_lien_id`,`lcdata_user_index`),
  KEY `idx_lcdata_user_index` (`lcdata_user_index`),
  KEY `idx_lcdata_name` (`lcdata_name`),
  KEY `idx_lcdata_info` (`lcdata_info`),
  KEY `idx_lcdata_last_used` (`lcdata_last_used`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;
