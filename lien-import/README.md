# lien-import

Console utility for the Zairmail **Lien Database Consolidation** project: load the
historical lien CSVs (ATT/ESS, TNU Combined, TNU Starter) into the existing MySQL
`liens` table next to the untouched LexisNexis (`LN`) data, report on it, and run the
**Free America Tax** lien-pull automation.

Scope and rules: `../Lien Database Consolidation and Free America Tax Automation.md`.
`liens` schema is never altered; `LN` rows are never touched.

---

## For a non-technical operator

**Easiest: the installer.** Give the user `dist\LienImport-Setup-<version>.exe`. They
double-click it -> Install -> a **Lien Import** desktop icon opens the window. Python is
bundled, no admin rights needed; user data goes to `Documents\Lien Import` (config.json,
`lien-data\inbox|processed|failed`, `output`) and survives uninstall/upgrade.

To build it (developer PC, needs Python + Inno Setup 6 -
`winget install --id JRSoftware.InnoSetup -e`): double-click **`build-installer.bat`**
(optional argument: version, default `1.0.0`). It makes a private `.build-venv`,
bundles the app with PyInstaller (`packaging\launcher.py` -> `build\pyinstaller\dist`),
then compiles `packaging\LienImport.iss` into `dist\`. Re-run it after any code change
and send the new Setup.exe - installing over the old version keeps the user's data.
The installed app is the window only; the text menu (FAT pulls) still runs from this
folder via `lien-import.bat`.

Without the installer:

1. **`setup.bat`** - run once. Checks Python, installs what's needed, and opens
   `config.json` for the database details.
2. **`lien-import-gui.bat`** - a window: paste a connection string (or type
   host/port/user/password), the **Database / schema** is pre-set to `zm_dba`,
   **Test Connection**, choose a file/folder/zip + source, **Check File
   (Preview)**, then **Import** (only enabled after a preview of that exact
   file, and asks to confirm), **Verify Counts**. (`lien_import/gui.py`,
   stdlib Tkinter - no extra dependency.)
3. **`lien-import.bat`** - a numbered text menu with every tool, including
   statistics and the FAT pull. Drag a file onto the window when it asks.

**Many files at once (recommended):** drop files / whole folders / zips into
`lien-data\inbox`, then **Check All** + **Import All** in the window (or menu
**A**). Each file's source is detected from its header, each file is imported
once (content SHA-256 ledger), and finished files move to `lien-data\processed`
(problem files to `lien-data\failed` with a `.reason.txt`).

Full walk-through: **`QUICKSTART.md`**.

## Install (developer / manual)

```
python -m pip install -r requirements.txt      # runtime dep: PyMySQL only
cp config.example.json config.json             # then edit db + options
```

Python 3.11+ (developed on 3.14). Every config value can also come from the environment
(`LIEN_DB_HOST`, `LIEN_DB_PORT`, `LIEN_DB_NAME`, `LIEN_DB_USER`, `LIEN_DB_PASSWORD`,
`LIEN_DB_CHARSET`, `LIEN_LIENS_TABLE`) - these override `config.json`.

---

## Commands

```
python -m lien_import discover     --input PATH [--source ES|TN]
python -m lien_import analyze       --input PATH --source ES|TN            # file mode
python -m lien_import analyze       --db [--source ES|TN|LN]               # DB mode
python -m lien_import deliverable A --input PATH --source ES|TN            # Discovery Summary
python -m lien_import deliverable C --input PATH --source ES|TN            # Preview/Audit Results
python -m lien_import preview       --input PATH --source ES|TN [--check-existing] [--limit N] [--allow-duplicates]
python -m lien_import import        --input PATH --source ES|TN [--commit] [--limit N] [--force] [--persist-rejects] [--allow-duplicates]
python -m lien_import verify        --source ES|TN|LN
python -m lien_import auto-import   [--inbox PATH] [--commit] [--open-inbox] [--allow-duplicates]
python -m lien_import fat-analyze   [--source ES|TN|LN]
python -m lien_import fat-pull      --job NAME --limit N [--commit --start-case-id ID]
python -m lien_import fat-status
```

`--input` accepts a single `.csv`, a directory (searched recursively), or a `.zip`.

`--allow-duplicates` (or `"allow_duplicates": true` under `import` in config.json, or the
GUI checkbox): a lien repeated across files / rows is kept as **separate rows** instead of
once. The lien_id then also covers the CSV file name + row number, so re-importing the same
file still adds nothing. Do not mix modes for one source: rows imported in normal mode get
different ids than in this mode, so switching would insert those liens a second time.

| Command | Writes DB? | Purpose (handoff §) |
|---|---|---|
| `discover` | never | Profile every distinct CSV layout: columns, row counts, % populated, sample values, date/amount format detection, matched adapter (§5, §18.A) |
| `analyze` | never | Statistical + data-quality report: Federal/State × Business/Individual cross-tab, amount bands, filing-year histogram, jurisdiction + name-kind distributions, top creditors, per-format §12. File mode (pre-import) or DB mode (consolidated inventory) (§6, §12) |
| `deliverable A` | never | Generate the **Discovery Summary** markdown per format (mapping, transformations, heuristics, assumptions, problems) (§18.A) |
| `deliverable C` | never | Generate the **Preview/Audit Results** markdown - §12 counts combined + per format + examples (§18.C) |
| `preview` | never (reads only with `--check-existing`) | Full normalise + validate + classify + de-dupe; writes the audit + reject/held/sample files. Run on the full archives before any import (§12) |
| `import` | only with `--commit` | Insert `would_insert` rows. Dry-run (rollback) without `--commit`. `--force` past `max_commit_rows`, `--persist-rejects` writes rejects to a table (§11, §15) |
| `verify` | never | Count `liens` rows for a source and reconcile against the last audit's `would_insert` (§15) |
| `auto-import` | only with `--commit` | Every CSV/ZIP in the inbox (`paths.inbox_dir`), source auto-detected per file. Preview runs one pass per source over all its files (cross-file duplicates counted once). `--commit` imports file by file, records each in `lien_import_files` (SHA-256 of content - a re-dropped or renamed copy is skipped), moves it to `processed_dir`; unrecognised/failed files go to `failed_dir` with a `.reason.txt`. Exit code 2 if any file failed, 3 if the inbox is empty |
| `fat-analyze` | never | How many liens across LN+TN+ES match the FAT criteria (Federal, Individual, ≥ $5,000, not yet assigned), by source/state/amount (§16) |
| `fat-pull` | only with `--commit` | Select the next N liens (newest load first), give them sequential `FREEAMTAX Case ID`s from `--start-case-id` (from Logics), record them in zm_dba's existing `liens_custom_data` exactly like the manual process, write `fat_pull_<job>.csv` for the mail run (§16) |
| `fat-status` | never | Every past FAT pull: date, lien count, Case ID range |

### Typical order per source (consolidation)

```
python -m lien_import discover     --input D:\lien-date-to-add-to-db\ATT-ESS-...zip --source ES
python -m lien_import analyze       --input D:\lien-date-to-add-to-db\ATT-ESS-...zip --source ES
python -m lien_import deliverable A --input D:\lien-date-to-add-to-db\ATT-ESS-...zip --source ES
python -m lien_import deliverable C --input D:\lien-date-to-add-to-db\ATT-ESS-...zip --source ES
#   -> review, circulate with docs/Deliverable-B / -D, get sign-off
python -m lien_import import  --input ...same... --source ES --limit 50 --commit    # small test
python -m lien_import verify  --source ES
python -m lien_import import  --input ...same... --source ES --commit                # full source
python -m lien_import import  --input ...same... --source ES --commit                # re-run -> inserts 0
```

### FAT automation

```
python -m lien_import analyze     --db                       # sanity-check the consolidated table
python -m lien_import fat-analyze                             # size the pull
python -m lien_import fat-status                                   # past pulls + Case IDs
python -m lien_import fat-pull     --job FAT-2026-10 --limit 10500   # preview, writes nothing
python -m lien_import fat-pull     --job FAT-2026-10 --limit 10500 \n                                   --start-case-id 98731 --commit   # record + CSV
```

**How FAT works in zm_dba (verified on the live data):** Free America Tax is Zairmail
customer `user_index` 61379. Each pulled lien is one row in the existing
`liens_custom_data` table (`lcdata_name = 'FREEAMTAX Case ID'`, `lcdata_value` = the
Case ID). "Not already assigned" is checked against that table, so liens pulled by
the old manual process are never pulled again, and other customers' rows
(TNU 60275, ESS 60243, Protection Tax 61017) don't block FAT.

Case IDs come from **Logics**: past pulls jump between batches (38630 -> 38636,
87159 -> 88230), so the tool never computes one. `--commit` requires
`--start-case-id`, and refuses a start that isn't above the highest Case ID
already used (catches typos like `98` for `98731`).

---

## Output artifacts (per run, `output/<timestamp>_<cmd>_<source>/`)

| File | Contents |
|---|---|
| `audit_<SRC>.{txt,json}` | §12 counts **combined and per format**, Federal/State × Business/Individual cross-tab, jurisdiction-inference source stats, missing/invalid field tally, unmapped header signatures |
| `rejects_<SRC>.csv` | rows not imported (missing/invalid required value) + reasons |
| `held_<SRC>.csv` | Trust/Estate + Ambiguous rows (held pending Wilson's decision, §7) |
| `samples_<SRC>.txt` | up to 40 example INSERT classifications for review |
| `analysis.{txt,json}` | (analyze) full distribution report |
| `Deliverable-*.md` | (deliverable) the generated document |
| `fat_pull_<job>.csv` | (fat-pull) the mail pull: all `liens` columns + `FREEAMTAX Case ID` + job + user index |
| `run.log` | full run log |

Reconciliation invariant, checked per format and combined:

```
examined == would_insert + duplicates_within_source
            + missing_required_values + rejected_other
            + trust_estate_held + ambiguous_entity_held
```

---

## Field mapping & id strategy

Per-format mapping, transformations, heuristics and assumptions live in
`lien_import/adapters/mapping_docs.py` and are rendered into Deliverable A.
The `lien_id` scheme is `docs/Deliverable-B_ID-Strategy.md`:

```
natural_key = UPPER( entity_name | address | zip5 | filing_type | filing_date_iso | amount )
lien_id     = crockford_base32( SHA1( source_code + "::" + natural_key ) )[:15]
```

Same lien in two files of one source → same natural key → same id → de-duplicated
(§9). `ES` and `TN` never collide (`source_code` hashed in).

### Idempotency

* in-run: first id wins (`INSERT`), rest `SKIP_DUPLICATE`
* vs DB: ids already in `liens` for the source → `SKIP_DUPLICATE`
* `lien_import_log` (opt-in, recommended): records `lien_source, lien_id,
  natural_key_sha1, source_format, source_file, source_row_num, source_ref,
  imported_at` - makes re-runs safe + every row traceable + detects a true hash
  collision. New table, **not** a `liens` change; needs sign-off (§14). Disable with
  `import.use_import_log_table = false`.

Cross-source de-duplication is intentionally **not** attempted (§9).

---

## Database objects (all additive; `liens` / `LN` untouched)

| Object | Created by | SQL |
|---|---|---|
| `lien_import_log` | `import --commit` (if enabled) | `sql/lien_import_log.sql` |
| `lien_import_rejects` | `import --persist-rejects` | `sql/lien_import_rejects.sql` |
| `lien_import_files` | `auto-import --commit` (file ledger: one row per imported file) | created in code - `batch.ensure_ledger_table` |
| `liens_custom_data` | **existing** zm_dba table - FAT writes rows, never creates it | `sql/liens_custom_data_reference.sql` (local copies only) |

`sql/liens_reference.sql` is a **reconstruction** of the production `liens` DDL from
the handoff - confirm with `SHOW CREATE TABLE liens` before trusting it.

---

## Tests

```
python -m pytest                 # 80 unit + sample-file tests, no DB needed
```

Live-DB integration (`tests/test_db_integration.py`, 6 tests) covers preview → import →
idempotent re-import → dry-run → `source_ref` capture → rejects table → `max_commit_rows`
guard → full FAT pull flow. **Skipped** unless `LIEN_DB_*` env vars point at a
**throwaway** MySQL/MariaDB schema:

```
LIEN_DB_HOST=127.0.0.1 LIEN_DB_NAME=lien_test LIEN_DB_USER=root LIEN_DB_PASSWORD= \
  python -m pytest tests/test_db_integration.py -q
```

Stand up the tables in a test schema (the `.sql` files contain `--` comments and,
- strip comments and split on `;`):

```python
import re, pymysql
c = pymysql.connect(host="127.0.0.1", user="root", password="")
cur = c.cursor()
cur.execute("CREATE DATABASE IF NOT EXISTS lien_test CHARACTER SET utf8mb4")
cur.execute("USE lien_test")
for f in ("liens_reference", "liens_custom_data_reference", "lien_import_log", "lien_import_rejects"):
    sql = re.sub(r"(?m)^\s*--.*$", "", open(f"sql/{f}.sql").read())
    for stmt in filter(str.strip, sql.split(";")):
        cur.execute(stmt)
c.commit()
```

(The `fat-*` and `import` commands create these tables themselves via
`CREATE TABLE IF NOT EXISTS`; the `.sql` files are only for manual setup / review.)

---

## "Configure real data" checklist

1. `config.json`: `database.*` (host/port/name/user/password), confirm `liens_table`.
2. Run `SHOW CREATE TABLE liens` on the server; reconcile with `sql/liens_reference.sql`.
3. Decide `import.use_import_log_table` (recommended `true` - needs §14 sign-off).
4. Point `--input` at the real archives in `D:\lien-date-to-add-to-db`.
5. `discover` + `analyze` each archive → add an adapter for any unmatched layout
   (one class in `lien_import/adapters/` + a line in `REGISTRY` + an entry in
   `mapping_docs.py`).
6. Tune `name_kind()` keywords if real data needs it; note changes in the completion doc.
7. Generate Deliverables A + C; circulate with B + D; get sign-off.
8. Import per source with `--limit` first, then full, then re-run to prove idempotency.
9. FAT: `fat-analyze` / `fat-status`, then `fat-pull` with the count and the first
   Case ID from Logics.

---

## Performance (large archives)

The pipeline **streams** - source files and ZIP members are read incrementally
(never loaded whole) and processed in chunks. Peak Python heap for a 1,000,000-row
preview measured at ~190 MB, and ~1 MB after it returns (nothing accumulates).

| Setting (`config.json` -> `import`) | Default | Effect |
|---|---|---|
| `chunk_size` | 10000 | source rows normalised + de-duped + PK-sorted per pass |
| `workers` | 1 | `>1` runs the CPU-bound parse/normalise/classify across N processes (`ProcessPoolExecutor`); 4 is the sweet spot, ~1.7x over serial. Needs a script entry point - always true for `python -m lien_import` |
| `commit_every_chunks` | 2 | DB commit cadence on `import --commit`; also the crash-resume granularity |
| `batch_size` | 2000 | rows per `executemany` INSERT (capped by the server's `max_allowed_packet`) |

**Read side** (`preview` / `analyze` / `discover`) - CPU-bound, this is where you iterate:

| Operation | rows/s | 1M rows | 10M rows |
|---|---|---|---|
| serial | ~13,000 | ~75 s | ~13 min |
| `workers=4` | ~23,000 | ~45 s | ~7 min |

Peak Python heap for a 1M-row preview: ~190 MB, ~1 MB after it returns (nothing accumulates).

**Write side** (`import --commit`) - bound by InnoDB maintaining the `liens` table's
**8 secondary indexes** as it grows (this is the production schema; we do not alter it,
handoff §14). Each chunk is sorted by `lien_id` before insert so primary-key writes are
near-sequential. Measured on a local Windows MariaDB 10.4 with realistically varied data:
~3,300 rows/s (`chunk_size=25000, batch_size=2000`) -> **1M rows ≈ 5 min, 5M ≈ 25 min**.
A properly provisioned server is faster. Insert time per chunk rises as the table fills;
levers if it matters on the real load, in order of preference:

1. bigger `chunk_size` (25k-50k) - more PK-sorted locality per batch;
2. raise the server's `innodb_buffer_pool_size` for the run (DBA);
3. DBA drops the 8 `liens` secondary indexes, runs the import, rebuilds them - the
   standard bulk-load pattern, but a DBA call and out of this tool's scope.

**First import into an empty source uses an append fast path**: no per-chunk DB
existence checks, whole-run de-dupe set in RAM (~150 B/row). Re-imports into a
non-empty source take the safe path: per-chunk DB de-dupe, RAM bounded to one chunk.

**Resumable**: `import --commit` commits per window, so a failed or interrupted run
loses at most `chunk_size * commit_every_chunks` rows - re-run the same command, the
importer is idempotent and continues from where it stopped, with a `progress:` log line
every `progress_every` rows. `max_commit_rows` (default 250,000) stops a first run that
would insert more than that until you pass `--force` (having reviewed the preview).

Starting point for a very large single archive:
`{"chunk_size": 25000, "batch_size": 2000, "commit_every_chunks": 2, "workers": 4}`.

## Known limitations / open items

* Built + validated against the **four sample CSVs only**. Full archives must go through
  `discover` + `preview` first.
* `sql/liens_reference.sql` / `liens_custom_data_reference.sql` are copied from
  `SHOW CREATE TABLE` on a restored copy of zm_dba (MariaDB 10.4). Production is
  MySQL 5.6 - re-check against it once that server is up.
* Imported rows are formatted like the existing LexisNexis rows (UPPER-case ASCII,
  5-digit ZIP, county without COUNTY/PARISH). Addresses are **not** USPS-standardised
  the way LN's are (`HICKORY KNL`); that would need an address-standardisation service.
* `lien_id` scheme + same-source natural key: pending sign-off (`docs/Deliverable-B`).
* Trust/Estate + Ambiguous rows are **held, not imported** (§7) - awaiting Wilson.
* FAT pull order is "newest load first" - inferred from the 6 past pulls (they drained
  the 2025-06..09 loads first, and the preview continues exactly where the last pull
  stopped), not from a written rule. Confirm with the FAT process document (`docs/Deliverable-D` F1).
* Combined-Federal first names are abbreviated to an initial in the sample - imported
  as-is; confirm that is expected.
