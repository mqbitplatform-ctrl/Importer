-- OPTIONAL side table (NOT a change to `liens`).
--
-- Purpose: make re-runs idempotent and every inserted lien traceable back to
-- its exact source file + row (+ the source's own identifier), and let the
-- importer detect a genuine lien_id hash collision (same id, different
-- natural key).
--
-- Creating this requires client sign-off (handoff section 14: "Any proposed
-- schema change should be discussed before implementation"). If it is not
-- approved, set import.use_import_log_table = false in config.json and the
-- importer falls back to the (lien_source, lien_id) primary key of `liens`
-- for duplicate detection.

CREATE TABLE IF NOT EXISTS lien_import_log (
  lien_source       CHAR(2)      NOT NULL,
  lien_id           VARCHAR(15)  NOT NULL,
  natural_key_sha1  CHAR(40)     NOT NULL,
  source_format     VARCHAR(40)  NOT NULL,   -- att_ess | tnu_combined | tnu_starter
  source_file       VARCHAR(255) NOT NULL,
  source_row_num    INT          NOT NULL,
  source_ref        VARCHAR(80)  NULL,       -- PIN / Case # / Filing Number (provenance only)
  imported_at       DATETIME     NOT NULL,
  PRIMARY KEY (lien_source, lien_id),
  KEY ix_import_log_sha1 (natural_key_sha1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
