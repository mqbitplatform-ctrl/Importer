from lien_import.analytics import _band, analyze_files, render_text
from lien_import.config import AppConfig
from decimal import Decimal


def test_band_boundaries():
    assert _band(Decimal("999")) == "< $1k"
    assert _band(Decimal("5000")) == "$5k - $10k"
    assert _band(Decimal("4999.99")) == "$1k - $5k"
    assert _band(Decimal("1000000")) == ">= $1M"
    assert _band(None) == "(unparseable)"


def test_analyze_files_att_ess(att_ess_csv):
    rep = analyze_files("ES", str(att_ess_csv), AppConfig())
    assert rep["mode"] == "file"
    s12 = rep["audit"]["combined"]["section12"]
    assert s12["total_examined"] == 25
    assert s12["would_insert"] == 25
    ct = rep["audit"]["combined"]["cross_tab"]
    assert ct["federal"]["individual"] == 20
    assert ct["federal"]["business"] == 2
    assert ct["state"]["business"] == 1
    d = rep["distributions"]
    assert sum(d["amount_bands"].values()) == 25
    assert d["name_kind"]["Individual"] == 22
    assert d["name_kind"]["Business"] == 3
    assert "Business" in d["name_kind_examples"]
    # render must not raise
    assert "ANALYSIS (file)" in render_text(rep)


def test_analyze_files_combined_state_all_business(combined_state_csv):
    rep = analyze_files("TN", str(combined_state_csv), AppConfig())
    ct = rep["audit"]["combined"]["cross_tab"]
    assert ct["state"]["business"] == 22
    assert ct["federal"]["individual"] == 0
    assert rep["distributions"]["filing_type"] == {"S": 22}
