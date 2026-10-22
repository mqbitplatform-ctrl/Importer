# Deliverable D - Open Questions

Handoff section 18.D. Decisions that need client / business input rather than an
implementation assumption. Owner: **Wilson** (scope), with Saleha on scheduling.

## Consolidation (blocks the production import)

| # | Question | Current tool behaviour / default |
|---|---|---|
| Q1 | **Trust/Estate and genuinely ambiguous** entity rows - how to handle? | Held out of the import, counted and listed in `held_<SRC>.csv`. Nothing imported until you decide (section 7). |
| Q2 | Approve the **`lien_id` strategy** (Deliverable B). | Implemented as described; not run to production yet. |
| Q3 | May we create **`lien_import_log`** (new side table, `liens` untouched)? Needed for re-run tracing + collision detection. | Built and used by default; can be disabled (`use_import_log_table=false`). |
| Q4 | May we create **`lien_import_rejects`** (optional side table) so rejected/held rows are queryable in the DB? | Off unless `import --persist-rejects`. |
| Q5 | Confirm the **"same source record" natural key** (entity name + address + zip5 + filing type + filing date + amount). | That is the default fingerprint. |
| Q6 | Are **first-initial-only first names** (seen in the Combined-Federal sample) representative of the real archive? Affects mail usability. | Imported as-is. |
| Q7 | Rough **row counts** per archive (for batch sizing / the `max_commit_rows` guard). | Guard defaults to 250,000 rows per commit; `--force` overrides. |
| Q8 | Any restriction on storing this lien data on **developer machines** (PII)? | - |
| Q9 | Known **CSV encoding** of the source files? | Tries utf-8-sig, falls back to cp1252 / latin-1, logs which. |

## Real-archive findings (full read-only preview, 2026-10-22)

The three real folders (109 files, 5.1M rows) were previewed end to end. These
rules were added or changed because of what the real data contains (handoff
section 6: "modify or add heuristics where necessary and document them").
Each needs a yes/no. Because a rule decides the entity name used in the
`lien_id`, **freeze these rules before the production import**.

| # | Finding / rule | Effect on the preview |
|---|---|---|
| R1 | TNU Starter uses fillers for missing names: Last Name `NA` (50,378), `N/A` (17,729), `Doe` (14,723); Middle Name `N/A` (16,535). **Rule:** treat these as blank, never store them. | No more `JASON NA` / `JASON DOE` names. |
| R2 | When the last name was a filler and there is **no middle name**, the First Name column holds a **business** name (`Glass Doctor`, `Freeway Building Materials`, `Doordash` - about 95% of a random sample; ~82,000 rows). **Rule:** Business. With a middle name (`Christopher C` + `NA`) it is a person: Individual with an empty last name. | TNU Starter held 5,753 -> 109; ~3,100 businesses no longer mis-marked Individual (they would have been in FAT pulls). |
| R3 | The client's heuristic sent `Pac West Real Estate Corp` to Trust/Estate. **Rule:** "Real Estate" is a business word, not an estate; a legal suffix (LLC, INC, CORP, LTD, LP, LLP, PLLC, PC, COMPANY) wins over Trust/Estate words (`Southwest Investment Trust Lp`). | ATT/ESS Trust/Estate held 3,666 -> 1,416. |
| R4 | 25,000 ATT/ESS rows (files 60243-425..429) use dates like `2023-10-11 00:00:00`. **Rule:** accept that format. | 25,000 rows no longer rejected. |
| R5 | ATT/ESS rows with no Type and no `F`/`S` filing number prefix. **Rule:** use the creditor (`State Of X` -> State, `Internal Revenue Service` -> Federal). | 12 rows recovered; 125 still have no filing type (rejected). |
| R6 | 29,721 TNU Starter rows have **no filing date and no year**. | Rejected (filing date is required). Is there another source for these dates, or is rejecting them right? |
| R7 | ~2,480 rows have amount `-`, `pending`, `$-`, `0` or blank. | Rejected (amount is required and must be > 0). Confirm. |
| R8 | The ATT/ESS mail files contain **test pieces**: name `Test R Piece`, creditor `Chris Baker`, amount `$-` / `$0.00`. | Rejected automatically (no amount, no filing type) - they never reach `liens`. |

Preview totals after these rules (would insert / held / rejected):
ATT/ESS 1,781,765 / 1,416 / 164 (2,241,656 duplicates across the monthly files);
TNU Combined 258,978 / 1 / 0; TNU Starter 771,555 / 109 / 32,341.

## Free America Tax automation (section 16)

Answered from a restored copy of zm_dba (2026-10): Free America Tax is Zairmail
customer `user_index` 61379; the existing process records each pulled lien in
`liens_custom_data` (`lcdata_name = 'FREEAMTAX Case ID'`, `lcdata_value` = Case ID).
69,000 liens across 6 pulls (10,000-14,000 each), all Federal / Individual / >= $5,000.
The tool now reads and writes that same table - no new FAT tables.

| # | Question | Tool behaviour today |
|---|---|---|
| F1 | Provide the **existing FAT process document**. In particular: the **order** liens are picked in. | Newest load first - inferred from the 6 past pulls (and the preview continues exactly where the 2026-07-17 pull stopped), not from a written rule. |
| F2 | ~~Where is "already assigned" tracked?~~ **Answered:** `liens_custom_data`, user_index 61379. | Implemented. Other customers' rows (TNU 60275, ESS 60243, Protection Tax 61017) don't block FAT. |
| F3 | Is the generated `fat_pull_<job>.csv` (all `liens` columns + `FREEAMTAX Case ID` + job + user index) the right shape for the mail job, or does the existing process produce a Zairmail mailing list instead? | CSV only. |
| F4 | Should FAT pulls run **on demand** or on a **schedule**? Past pulls were roughly every 2-4 weeks. | On demand (menu / CLI). |
| F5 | Should **released** liens (`lien_release_date` set) be excluded? Not in the section 16 criteria; zero F/I/>=$5k liens are released today. | Not excluded. |

## Logics Case IDs (`Shubham task info.docx`)

| # | Question | Tool behaviour today |
|---|---|---|
| L1 | ~~What are the "IDs in Logics"?~~ **Answered:** the `FREEAMTAX Case ID`s. They are contiguous within a pull but jump between pulls (38630 -> 38636, 87159 -> 88230), so they are allocated in Logics, not in zm_dba. | The operator types the first Case ID Logics gave them; the tool assigns the rest in order and refuses a start that isn't above the highest Case ID already used. |
| L2 | Does Logics need the pulled liens **back** (an import file or API call) to create the cases, or is entering the starting number enough? | Not automated - the CSV carries the Case IDs. |
