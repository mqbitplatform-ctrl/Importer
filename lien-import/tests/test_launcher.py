"""packaging/launcher.py - start-up of the installed app (where user data lives)."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from unittest import mock

LAUNCHER = Path(__file__).resolve().parents[1] / "packaging" / "launcher.py"


def _load():
    spec = importlib.util.spec_from_file_location("lien_launcher", LAUNCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_data_dir_defaults_to_documents_lien_import():
    launcher = _load()
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("LIEN_IMPORT_HOME", None)
        d = launcher.data_dir()
    assert d.name == "Lien Import"
    assert d.parent == launcher._documents()


def test_main_creates_user_folders_and_runs_from_there(tmp_path, monkeypatch):
    launcher = _load()
    home = tmp_path / "home"
    monkeypatch.setenv("LIEN_IMPORT_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    seen = {}

    def fake_gui_main():
        seen["cwd"] = Path.cwd()
        return 0

    with mock.patch("lien_import.gui.main", fake_gui_main):
        assert launcher.main() == 0
    assert seen["cwd"] == home
    for sub in ("lien-data/inbox", "lien-data/processed", "lien-data/failed", "output"):
        assert (home / sub).is_dir()
