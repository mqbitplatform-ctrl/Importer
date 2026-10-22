-- OPTIONAL side table (NOT a change to `liens`).
--
-- When `import --persist-rejects` is used, every rejected or held source row
-- is written here so it can be queried / reviewed in the database instead of
-- only in the run's rejects_<SRC>.csv / held_<SRC>.csv files.
-- Enable via import.rejects_table in config.json. Requires the same sign-off
-- as lien_import_log (handoff section 14).

CREATE TABLE IF NOT EXISTS lien_import_rejects (
  id             BIGINT       NOT NULL AUTO_INCREMENT,
  run_id         VARCHAR(40)  NOT NULL,      -- the run directory timestamp/tag
  lien_source    CHAR(2)      NOT NULL,
  source_format  VARCHAR(40)  NOT NULL,
  source_file    VARCHAR(255) NOT NULL,
  source_row_num INT          NOT NULL,
  disposition    VARCHAR(24)  NOT NULL,      -- REJECT_MISSING | REJECT_INVALID | HOLD_TRUST_ESTATE | HOLD_AMBIGUOUS
  reasons        TEXT         NOT NULL,
  name_or_company VARCHAR(255) NULL,
  amount_raw     VARCHAR(40)  NULL,
  filing_date_raw VARCHAR(40) NULL,
  creditor       VARCHAR(120) NULL,
  recorded_at    DATETIME     NOT NULL,
  PRIMARY KEY (id),
  KEY ix_rejects_run (run_id),
  KEY ix_rejects_disp (disposition)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
