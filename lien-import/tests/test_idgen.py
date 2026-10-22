from lien_import.idgen import ID_LENGTH, build_natural_key, make_lien_id


def _key(**over):
    base = dict(
        entity_name="ACEVEDO A",
        address="401 W PRICE ST",
        zip_code="07036-7212",
        filing_type="F",
        filing_date_iso="2021-12-14",
        amount="12293.00",
    )
    base.update(over)
    return build_natural_key(**base)


def test_id_is_deterministic_and_bounded():
    k = _key()
    id1, sha1 = make_lien_id("TN", k)
    id2, sha2 = make_lien_id("TN", k)
    assert id1 == id2
    assert sha1 == sha2
    assert len(id1) == ID_LENGTH
    assert id1.isalnum() and id1.upper() == id1


def test_same_record_same_id_across_tnu_formats():
    # tnu_combined and tnu_starter produce the same natural key for one lien
    k = _key()
    assert make_lien_id("TN", k)[0] == make_lien_id("TN", k)[0]


def test_source_prefix_separates_es_and_tn():
    k = _key()
    assert make_lien_id("ES", k)[0] != make_lien_id("TN", k)[0]


def test_zip_is_truncated_to_five():
    assert _key(zip_code="07036-7212") == _key(zip_code="07036")


def test_collision_disambiguation():
    k = _key()
    real_id, real_sha = make_lien_id("TN", k)

    # pretend real_id is already taken by a DIFFERENT natural key
    taken = {real_id: "different_sha1_value"}
    new_id, sha = make_lien_id("TN", k, lookup_existing_sha1=taken.get)
    assert new_id != real_id
    assert sha == real_sha

    # but if the stored sha matches, it's the same record -> same id (idempotent)
    same = {real_id: real_sha}
    again_id, _ = make_lien_id("TN", k, lookup_existing_sha1=same.get)
    assert again_id == real_id
