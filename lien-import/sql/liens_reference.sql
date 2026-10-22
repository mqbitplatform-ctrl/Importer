-- Reference DDL for the production `liens` table in zm_dba.
--
-- Copied from `SHOW CREATE TABLE liens` on a restored copy of zm_dba
-- (2026-10, 1.39M LexisNexis rows). The production instance is MySQL 5.6.
--
-- NOT run by the importer against production - the real table already
-- exists. Used only to stand up a local throwaway copy for tests
-- (`setup-local-db`, test fixtures).

CREATE TABLE IF NOT EXISTS liens (
  `lien_source` char(2) NOT NULL,                  -- 'LN' = LexisNexis, 'ES' = ATT/ESS, 'TN' = TNU
  `lien_id` varchar(15) NOT NULL,                  -- unique within lien_source (LN ids are 10 chars)
  `lien_filing_type` char(1) NOT NULL,             -- 'S' = state, 'F' = federal
  `lien_jurisdiction` char(2) NOT NULL,            -- US state abbreviation
  `lien_entity_type` char(1) NOT NULL,             -- 'B' = business, 'I' = individual
  `lien_amount` decimal(15,2) NOT NULL DEFAULT 0.00,
  `lien_filing_date` date NOT NULL,
  `lien_release_date` date DEFAULT NULL,
  `lien_load_date` date NOT NULL,
  `lien_business_name` varchar(200) DEFAULT NULL,
  `lien_first_name` varchar(60) DEFAULT NULL,
  `lien_middle_initial` char(1) DEFAULT NULL,
  `lien_last_name` varchar(60) DEFAULT NULL,
  `lien_address` varchar(255) DEFAULT NULL,
  `lien_city` varchar(100) DEFAULT NULL,
  `lien_state` char(2) DEFAULT NULL,
  `lien_zip` varchar(10) DEFAULT NULL,             -- existing rows: always 5 digits
  `lien_plaintiff` varchar(50) DEFAULT NULL,       -- 'INTERNAL REVENUE SERVICE' / 'STATE OF <NAME>'
  `lien_filing_county` varchar(100) DEFAULT NULL,  -- existing rows: no COUNTY suffix
  PRIMARY KEY (`lien_source`,`lien_id`),
  KEY `idx_lien_filing_type` (`lien_filing_type`),
  KEY `idx_lien_jurisdiction` (`lien_jurisdiction`),
  KEY `idx_lien_entity_type` (`lien_entity_type`),
  KEY `idx_lien_amount` (`lien_amount`),
  KEY `idx_lien_filing_date` (`lien_filing_date`),
  KEY `idx_lien_release_date` (`lien_release_date`),
  KEY `idx_lien_load_date` (`lien_load_date`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;
