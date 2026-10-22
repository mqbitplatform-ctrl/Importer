# Deliverable E - Implementation Plan & Estimate

Handoff section 18.E. Send for review before the full production import.

## Proposed implementation

A Python 3 console utility (`lien_import`) - already built and validated against the
four sample CSVs (80 unit/sample tests, 6 live-MySQL integration tests). One runtime
dependency (`PyMySQL`). Commands:

| Command | Purpose |
|---|---|
| `discover` | profile source CSV layouts |
| `analyze` | statistical + data-quality report (file or DB) |
| `deliverable A` / `deliverable C` | generate the Discovery Summary / Preview-Audit documents from a run |
| `preview` | normalise + validate + audit, no writes |
| `import` | insert (dry-run unless `--commit`; `--limit`, `--force`, `--persist-rejects`) |
| `verify` | reconcile `liens` counts against the last audit |
| `fat-analyze` / `fat-pull` / `fat-status` | Free America Tax lien-pull automation |

Architecture: one adapter class per source format behind a registry; shared
normalisation (money / date / name / geography); deterministic id generation;
idempotent loader; audit with per-format breakdown + cross-tab.

## Objects created (all additive - `liens` and `LN` untouched)

| Object | Kind | Notes |
|---|---|---|
| `lien_import_log` | table | re-run tracing + collision detection (sign-off Q3) |
| `lien_import_rejects` | table | optional, `--persist-rejects` (Q4) |
| `liens_custom_data` | **existing** table - FAT writes rows (user_index 61379), never alters it | FAT automation |

## Work still required (fill in after real-data discovery)

1. Obtain the 3 archives + production DB access; run `discover` and `analyze`.
2. Add adapters for any CSV layouts the samples didn't show.
3. Tune / document heuristics against real data (section 6).
4. Generate Deliverables A and C from the full archives; circulate with Deliverable D.
5. On sign-off: `import --limit` test batches -> `verify` -> full `import --commit`
   per source -> re-run to prove idempotency.
6. FAT phase: confirm pull order + mail-file shape (Deliverable D F1, F3); Case IDs are entered from Logics per pull.

## Testing approach

- Unit tests for every parser / classifier / id generator.
- Sample-file integration tests (asserted mapped output + audit counts).
- Live-MySQL integration tests (preview -> import -> idempotent re-import -> dry-run ->
  rejects table -> FAT pull), skipped unless `LIEN_DB_*` is set.
- Independent post-import validation script that re-derives every field from the source
  CSVs and diffs against the DB.

## Estimated hours

_To be completed after inspecting the real archives and the production database_
(discovery + adapter work + heuristic tuning + preview/audit + supervised import +
FAT phase). The framework is in place; the estimate is driven by how many additional
CSV layouts and data-quality issues the full archives contain.

## Risks / assumptions

- Built from 4 sample rows per format - real archives may differ (extra layouts, date/
  amount variants, encodings).
- `liens` / `liens_custom_data` DDL verified against a restored copy of zm_dba
  (MariaDB 10.4); re-check on the production MySQL 5.6 server once it is running.
- FAT pull order inferred from past pulls in zm_dba, not a written rule (Deliverable D F1).
