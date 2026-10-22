"""Per-format mapping / transformation / heuristic / assumption register.

Feeds Deliverable A (Discovery Summary) and the audit "assumptions" section
(handoff sections 5, 11 pt3, 12, 18.A). Keep this in sync with the adapter
code - it is the human-readable statement of what each adapter does.
"""

from __future__ import annotations

FORMAT_DOCS: dict[str, dict] = {
    "att_ess": {
        "source_code": "ES",
        "archive": "ATT-ESS-May-2024-to-July-2025.zip",
        "mapping": {
            "lien_source": "constant 'ES'",
            "lien_id": "generated (SHA1 of natural key -> base32, 15 chars)",
            "lien_filing_type": "`Type` column (Federal/State); fallback `Filing #` prefix 19F-/19S-",
            "lien_jurisdiction": "State liens: state named in `Creditor 1` ('State Of X'); Federal liens: `State` column",
            "lien_entity_type": "classified from `Full Name` (no explicit B/I field)",
            "lien_amount": "`Amount` - strip $ and commas",
            "lien_filing_date": "`Filing Date` - m/d/yy or m/d/yyyy",
            "lien_release_date": "always NULL (not supplied)",
            "lien_load_date": "import run date",
            "lien_business_name": "`Full Name` when classified Business",
            "lien_first_name/middle_initial/last_name": "split from `Full Name` when classified Individual",
            "lien_address/city/state/zip": "`Address` / `City` / `State` / `Zip Code` -> stored like existing LN rows: UPPER-case ASCII, ZIP5",
            "lien_plaintiff": "Federal -> 'INTERNAL REVENUE SERVICE'; State -> 'STATE OF <NAME>'",
            "lien_filing_county": "`County` -> UPPER, no COUNTY/PARISH suffix, no . or '",
        },
        "not_mapped": ["ListID", "PIN", "Filing #", "Phone number", "Respond By"],
        "transformations": [
            "money: strip $ and thousands separators",
            "date: parse m/d/yy (2-digit year -> 20xx) and m/d/yyyy",
            "name: split single 'First [Middle] Last [Suffix]' string",
        ],
        "heuristics": [
            "Business vs Individual from Full Name via name_kind() (ported Get-NameKind, no $5k filter)",
            "Trust/Estate and Ambiguous names are HELD, not imported",
        ],
        "assumptions": [
            "one CSV layout across all files in the archive (confirm in discovery)",
            "`Type` column present and reliable; `Filing #` prefix corroborates",
            "`PIN`/`Filing #` kept only as provenance (import log), never as lien_id",
        ],
        "known_problems": [
            "person name only as a single field -> classification + split required",
            "no explicit Business/Individual indicator",
            "2-digit filing years",
        ],
    },
    "tnu_combined": {
        "source_code": "TN",
        "archive": "Combined-TNU_2024-02-29.zip (Combined-Federal / Combined-State)",
        "mapping": {
            "lien_source": "constant 'TN'",
            "lien_id": "generated (same scheme; natural key shared with tnu_starter so a lien in both files de-duplicates)",
            "lien_filing_type": "`Creditor` ('Federal Taxing Authorities' / 'State Of X'); fallback `Note` ('FEDERAL/STATE TAX LIEN'), then file name",
            "lien_jurisdiction": "State: `Creditor` 'State Of X' -> `Note` filing office -> `State`; Federal: `State` -> `Note` filing office",
            "lien_entity_type": "`Company` populated & person fields blank -> B; else classify person name",
            "lien_amount": "`Amount` - plain integer in samples",
            "lien_filing_date": "`Filling Date` (typo) - m/d/yyyy [h:mm:ss AM/PM]",
            "lien_release_date": "always NULL",
            "lien_load_date": "import run date",
            "lien_business_name": "`Company`",
            "lien_first_name/middle_initial/last_name": "`First Name` / `Middle Initial` / `Last Name` (first name may be an initial only)",
            "lien_address/city/state/zip": "`Address` / `City` / `State` / `Zip` -> stored like existing LN rows: UPPER-case ASCII, ZIP5",
            "lien_plaintiff": "Federal -> 'INTERNAL REVENUE SERVICE'; State -> 'STATE OF <NAME>'",
            "lien_filing_county": "`Filling County` (typo) -> UPPER, 'Union County' -> 'UNION'",
        },
        "not_mapped": ["Full Name (derived)", "Note (parsed for filing number + filing office only)"],
        "transformations": [
            "header typo `Filling` -> `filing`",
            "date: parse m/d/yyyy and m/d/yyyy h:mm:ss AM/PM",
            "Note: regex-extract 'Filing Number:' (provenance) and 'Filing Office:..., XX' (jurisdiction fallback)",
        ],
        "heuristics": [
            "B/I primarily from which columns are populated (Company vs person)",
            "State jurisdiction taken from the creditor, which can differ from the mailing address",
        ],
        "assumptions": [
            "`Company` is only populated for genuine businesses",
            "`Creditor` reliably distinguishes Federal vs State",
            "amounts have no cents / currency symbols (seen so far)",
        ],
        "known_problems": [
            "first names abbreviated to an initial in Combined-Federal samples",
            "structured data embedded in a free-text `Note` blob",
            "`Filling County` may not match the `Note` filing office",
        ],
    },
    "tnu_starter": {
        "source_code": "TN",
        "archive": "TNU-Starter-Full-List.zip",
        "mapping": {
            "lien_source": "constant 'TN'",
            "lien_id": "generated (natural key shared with tnu_combined)",
            "lien_filing_type": "`Creditor` ('Federal Taxing Authorities' / 'Internal Revenue Service' / 'State ...'); fallback `Source` tag prefix (Fed.../St...)",
            "lien_jurisdiction": "Federal: `State` column; State: state named in `Creditor`",
            "lien_entity_type": "`Business Name` populated -> B; else Individual from person fields",
            "lien_amount": "`Amount Owed` - strip commas",
            "lien_filing_date": "`Filing Date` - m/d/yyyy",
            "lien_release_date": "always NULL",
            "lien_load_date": "import run date",
            "lien_business_name": "`Business Name`",
            "lien_first_name/middle_initial/last_name": "`First Name` / `Middle Name` / `Last Name`; empty last + present middle -> middle promoted to last",
            "lien_address/city/state/zip": "`Address` / `City` / `State` / `Zip` -> stored like existing LN rows: UPPER-case ASCII, ZIP5",
            "lien_plaintiff": "Federal -> 'INTERNAL REVENUE SERVICE'; State -> 'STATE OF <NAME>'",
            "lien_filing_county": "`Filing County` -> UPPER, 'El Dorado County' -> 'EL DORADO'",
        },
        "not_mapped": ["index", "year", "Case #", "Source", "Cell", "Home", "Date"],
        "transformations": [
            "money: strip commas",
            "date: parse m/d/yyyy",
            "empty last name -> promote middle name to last name (flagged)",
        ],
        "heuristics": [
            "B/I from presence of `Business Name`",
            "`Source` tag prefix used only as a Federal/State fallback",
        ],
        "assumptions": [
            "`Case #` / `index` are not stable cross-file ids -> content fingerprint used instead",
            "`Business Name` only populated for businesses",
        ],
        "known_problems": [
            "rows with blank last name (name in the middle-name column)",
            "several non-lien columns (contact info, export timestamps)",
        ],
    },
}
