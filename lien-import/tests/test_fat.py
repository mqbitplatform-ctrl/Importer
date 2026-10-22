from decimal import Decimal

from lien_import.config import FatConfig
from lien_import.fat.criteria import FatCriteria


def test_criteria_from_config_defaults():
    c = FatCriteria.from_config(FatConfig())
    assert c.user_index == "61379"
    assert c.filing_type == "F"
    assert c.entity_type == "I"
    assert c.min_amount == Decimal("5000")
    assert c.sources == []


def test_config_defaults_point_at_existing_zm_dba_table():
    fc = FatConfig()
    assert fc.assignment_table == "liens_custom_data"
    assert fc.case_id_name == "FREEAMTAX Case ID"


def test_where_all_sources_checks_liens_custom_data_for_this_customer():
    c = FatCriteria.from_config(FatConfig())
    sql, params = c.where("l", "liens_custom_data")
    assert "l.lien_filing_type = %s" in sql
    assert "l.lien_entity_type = %s" in sql
    assert "l.lien_amount >= %s" in sql
    assert "NOT EXISTS" in sql and "liens_custom_data" in sql
    assert "a.lcdata_lien_source = l.lien_source" in sql
    assert "a.lcdata_lien_id = l.lien_id" in sql
    assert "a.lcdata_user_index = %s" in sql   # only THIS customer's assignments
    assert "lien_source IN" not in sql
    assert params == ["F", "I", "5000", 61379]


def test_where_with_source_filter_keeps_param_order():
    c = FatCriteria.from_config(FatConfig(sources=["ES", "TN"]))
    sql, params = c.where("l", "liens_custom_data")
    assert "l.lien_source IN (%s,%s)" in sql
    assert params == ["F", "I", "5000", "ES", "TN", 61379]


def test_where_can_disable_exclude_assigned():
    c = FatCriteria.from_config(FatConfig())
    c.exclude_assigned = False
    sql, params = c.where()
    assert "NOT EXISTS" not in sql
    assert params == ["F", "I", "5000"]
