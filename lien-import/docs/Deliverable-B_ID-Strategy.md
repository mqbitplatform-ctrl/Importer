# Deliverable B - `lien_id` Generation Strategy

Handoff section 8 / 18.B. **Requires client sign-off before the production import.**

## Requirements (restated)

- Max length 15 characters.
- Unique within the applicable `lien_source`.
- Stable / deterministic - the same source record produces the same id on a later run.
- Re-running an import must not create a second copy of a record.
- Source filing numbers / index / Case # / PIN are **not** used as the id (they are
  captured separately as provenance).

## Method

1. **Natural key** - a normalised string built from the identity-bearing fields of the
   mapped record:

   ```
   natural_key = UPPER( entity_name | address | zip5 | filing_type | filing_date_iso | amount )
   ```

   where
   - `entity_name` = business name, or `first middle-initial last` for individuals,
     with all non-alphanumeric characters removed;
   - `address` = the street address, non-alphanumerics removed;
   - `zip5` = first 5 digits of the ZIP;
   - `filing_type` = `F` / `S`;
   - `filing_date_iso` = `YYYY-MM-DD`;
   - `amount` = `0.00`-formatted.

2. **Hash** -

   ```
   lien_id = crockford_base32( SHA1( lien_source + "::" + natural_key ) )[:15]
   ```

   Crockford base32 alphabet (`0-9A-Z` minus `I L O U`). 15 chars x 5 bits = **75 bits**
   of address space.

3. **Collision handling** - if the candidate id already exists for that source with a
   *different* recorded natural-key hash (checked against `lien_import_log` and the
   in-run set), the natural key is salted (`natural_key#1`, `#2`, ...) and re-hashed
   until a free id is found. Every collision is logged. At 75 bits the expected number
   of collisions across tens of millions of rows is effectively zero; the fallback
   exists only so the importer can never silently overwrite.

## Why this satisfies each requirement

| Requirement | How |
|---|---|
| <= 15 chars | fixed 15-char base32 output |
| unique within source | `lien_source` is hashed in; collisions salted |
| deterministic / same record -> same id | pure function of the normalised source fields |
| re-run doesn't duplicate | id is stable, and the importer inserts only when `(lien_source, lien_id)` is absent from `liens` (and `lien_import_log`) |
| same lien in two files of one source (section 9) | both files produce the same natural key -> same id -> second is skipped as a duplicate |
| ES vs TN kept separate (section 9) | different `lien_source` -> different hash input -> different id |

## Open points for sign-off

- **B1.** Confirm the natural-key field list. Alternative: include the source's own
  filing number when it is present and known-stable (would make within-source dedupe
  stricter but weaker across the two TNU formats).
- **B2.** Confirm 15 chars of hash is acceptable (no human-readable prefix). A 2-char
  format tag + 13 hash chars is possible at a small cost to address space.
- **B3.** Confirm `lien_import_log` may be created (needed for collision detection and
  re-run tracing) - see Deliverable D.
