# Completion Documentation - Lien Database Consolidation

Handoff section 19. Fill in when the consolidation is complete. The goal: someone
other than the original developer can operate the import later without reconstructing
how it works.

## What was implemented

_(summary of the `lien_import` utility and any adapters added for real-archive layouts)_

## Source files / datasets imported

| Archive | Format(s) | `lien_source` | Files | Rows examined |
|---|---|---|---|---|
| ATT-ESS-May-2024-to-July-2025.zip | | ES | | |
| Combined-TNU_2024-02-29.zip | | TN | | |
| TNU-Starter-Full-List.zip | | TN | | |

## Record counts by source

| `lien_source` | Rows inserted | Duplicates skipped | Rejected (missing) | Rejected (other) | Held (Trust/Estate) | Held (Ambiguous) |
|---|---|---|---|---|---|---|
| ES | | | | | | |
| TN | | | | | | |

_(from the final `audit_<SRC>.json` of each import run)_

## Records skipped / rejected and why

_(reference the `rejects_<SRC>.csv` / `held_<SRC>.csv` / `lien_import_rejects` table;
summarise the reason breakdown)_

## Heuristics used

- Business/Individual: `name_kind()` (ported `Get-NameKind`, no $5,000 filter) - list any
  keyword additions/changes made for real data.
- Federal/State: `Type` column / `Creditor` / `Note` / file name / `Source` tag.
- Jurisdiction: creditor "State Of X" (state liens) / address state (federal) / Note
  filing office.

## Generated-ID approach

See `docs/Deliverable-B_ID-Strategy.md` (as signed off). Note any change made.

## Files / code created or changed

_(list adapter modules, config, SQL)_

## Database changes

- `lien_import_log` - created (Y/N)
- `lien_import_rejects` - created (Y/N)
- `liens_custom_data` - FAT rows added (count, Case ID range) - table itself unchanged
- `liens` / `LN` rows - unchanged (confirm)

## How to run another import

```
python -m lien_import discover --input <archive> --source <ES|TN>
python -m lien_import preview  --input <archive> --source <ES|TN>
python -m lien_import import   --input <archive> --source <ES|TN> --limit 50 --commit
python -m lien_import verify   --source <ES|TN>
python -m lien_import import   --input <archive> --source <ES|TN> --commit
```

## How duplicate prevention works

Deterministic `lien_id` from a natural key + insert-only-if-`(lien_source, lien_id)`-
absent (+ `lien_import_log`). Re-running any import inserts 0 rows.

## Logging / output locations

`output/<timestamp>_<cmd>_<source>/` - `audit_<SRC>.{txt,json}`, `rejects_<SRC>.csv`,
`held_<SRC>.csv`, `samples_<SRC>.txt`, `run.log`.

## Known limitations

_(from README "Known limitations" + anything found during the real import)_

## Remaining open items

_(unresolved Deliverable D questions; FAT phase status)_

## Recommended next steps

_(e.g. FAT automation rollout, Logics Case ID hand-off, periodic re-import cadence)_
