import json

import pytest

from lien_import.config import AppConfig, DbConfig, load_config, save_config, to_dict


@pytest.fixture(autouse=True)
def _no_env_overrides(monkeypatch):
    # load_config() lets LIEN_DB_* env vars override the file; these tests
    # check the file round-trip itself, so they must not see a live-DB env.
    for key in ("LIEN_DB_HOST", "LIEN_DB_PORT", "LIEN_DB_NAME", "LIEN_DB_USER",
                "LIEN_DB_PASSWORD", "LIEN_DB_CHARSET", "LIEN_LIENS_TABLE"):
        monkeypatch.delenv(key, raising=False)


def test_save_then_load_round_trips(tmp_path):
    cfg = AppConfig()
    cfg.database = DbConfig(
        host="db.example.com", port=3307, name="lineitem", user="root",
        password="s3cret", charset="utf8mb4", liens_table="liens",
    )
    path = tmp_path / "config.json"
    save_config(cfg, path)

    loaded = load_config(path)
    assert loaded.database.host == "db.example.com"
    assert loaded.database.port == 3307
    assert loaded.database.name == "lineitem"
    assert loaded.database.user == "root"
    assert loaded.database.password == "s3cret"
    assert loaded.database.is_configured


def test_save_creates_valid_json(tmp_path):
    path = tmp_path / "config.json"
    save_config(AppConfig(), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "database" in data and "import" in data and "fat" in data


def test_save_preserves_unknown_existing_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"database": {}, "note": "do not drop me"}), encoding="utf-8")
    save_config(AppConfig(), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["note"] == "do not drop me"


def test_save_overwrites_database_section(tmp_path):
    path = tmp_path / "config.json"
    cfg1 = AppConfig()
    cfg1.database = DbConfig(host="old-host", name="old-db", user="u")
    save_config(cfg1, path)

    cfg2 = AppConfig()
    cfg2.database = DbConfig(host="new-host", name="new-db", user="u2")
    save_config(cfg2, path)

    loaded = load_config(path)
    assert loaded.database.host == "new-host"
    assert loaded.database.name == "new-db"


def test_to_dict_matches_load_config_shape(tmp_path):
    cfg = AppConfig()
    cfg.imports.chunk_size = 999
    cfg.fat.user_index = "12345"
    d = to_dict(cfg)
    assert d["import"]["chunk_size"] == 999
    assert d["fat"]["user_index"] == "12345"
    assert d["fat"]["assignment_table"] == "liens_custom_data"
    assert d["fat"]["case_id_name"] == "FREEAMTAX Case ID"
