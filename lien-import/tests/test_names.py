import pytest

from lien_import.normalize.names import name_kind, split_person_name


@pytest.mark.parametrize(
    "name,kind",
    [
        ("Jeffrey M Trexler", "Individual"),
        ("Donna Murphy", "Individual"),
        ("Hanny Antonieta Gorbalan", "Individual"),
        ("A Acevedo", "Individual"),          # abbreviated first name (Combined-Federal)
        ("A B Aiardo", "Individual"),
        ("Thomas A Griffeth", "Individual"),
        ("Ccb Shop Company Llc", "Business"),
        ("Big Dawgz Burgers Inc", "Business"),
        ("Creative Motovation Llc", "Business"),
        ("007 Handy Man", "Business"),        # leading digit
        ("1 Auto Repair", "Business"),
        ("1 Edi Source Inc", "Business"),
        ("John Smith Revocable Trust", "TrustEstate"),
        ("Estate Of Jane Doe", "TrustEstate"),
        ("Smith & Jones", "Ambiguous"),
        ("", "Ambiguous"),
    ],
)
def test_name_kind(name, kind):
    assert name_kind(name) == kind


@pytest.mark.parametrize(
    "full,expected",
    [
        ("Jeffrey M Trexler", ("Jeffrey", "M", "Trexler")),
        ("Donna Murphy", ("Donna", None, "Murphy")),
        ("A B Aiardo", ("A", "B", "Aiardo")),
        ("Mary Jane Watson Parker", ("Mary", "J", "Watson Parker")),
        ("Cher", ("Cher", None, None)),  # lone token -> given name
        ("John Smith Jr", ("John", None, "Smith Jr")),
    ],
)
def test_split_person_name(full, expected):
    assert split_person_name(full) == expected
