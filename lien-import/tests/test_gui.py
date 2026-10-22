"""GUI wiring tests.

Tkinter widgets themselves aren't meaningfully testable without a real
window system, but on this project's target platform (Windows) a headless
``tk.Tk()`` actually constructs fine, so we drive the real widget tree and
its callbacks directly (no `mainloop()` - we pump the event queue by hand)
rather than re-testing pure logic in isolation twice.

Module-skipped automatically (with reason) wherever `tk.Tk()` cannot be
constructed - e.g. a Linux CI box with no display/Xvfb.

A second group of tests additionally talks to a live MySQL/MariaDB and is
skipped unless `LIEN_DB_HOST` is set, mirroring test_db_integration.py.
"""

from __future__ import annotations

import os
import time
from datetime import date
from pathlib import Path
from unittest import mock

import pytest

tk = pytest.importorskip("tkinter")

from lien_import.gui import LienImportApp  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
RUN_DATE = date(2026, 8, 28)


@pytest.fixture(scope="session")
def root():
    # One Tcl/Tk interpreter for the whole test session: repeatedly creating
    # and destroying tk.Tk() within a single process is unreliable on this
    # platform (observed: "invalid command name tcl_findLibrary" on the
    # second instance). Tests clear the root's children instead of tearing
    # the interpreter down between them.
    try:
        r = tk.Tk()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"no Tk display available in this environment: {exc}")
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture()
def app(root, tmp_path):
    for child in root.winfo_children():
        child.destroy()
    a = LienImportApp(root, tmp_path / "config.json")
    a.cfg.output_dir = tmp_path / "out"  # keep test runs out of the operator's ./output
    return a


def _pump(root, app, timeout=20.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline and app.busy:
        root.update()
        time.sleep(interval)
    root.update()


# --------------------------------------------------------------- no DB needed

def test_builds_with_import_disabled(app):
    assert app.btn_import.instate(["disabled"])


def test_schema_defaults_to_zm_dba_when_no_config(app):
    assert app.var_schema.get() == "zm_dba"


def test_saved_schema_wins_over_default(root, tmp_path):
    import json

    for child in root.winfo_children():
        child.destroy()
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"database": {
        "host": "db.example.com", "name": "other_db", "user": "u", "password": "p",
    }}), encoding="utf-8")
    with mock.patch.dict(os.environ, {}, clear=False):
        for k in ("LIEN_DB_HOST", "LIEN_DB_NAME", "LIEN_DB_USER", "LIEN_DB_PASSWORD"):
            os.environ.pop(k, None)
        a = LienImportApp(root, cfg_path)
    assert a.var_schema.get() == "other_db"
    assert a.var_host.get() == "db.example.com"


def test_placeholder_values_are_blanked(root, tmp_path):
    import json

    for child in root.winfo_children():
        child.destroy()
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"database": {
        "host": "REPLACE_ME", "name": "REPLACE_ME", "user": "REPLACE_ME", "password": "REPLACE_ME",
    }}), encoding="utf-8")
    with mock.patch.dict(os.environ, {}, clear=False):
        for k in ("LIEN_DB_HOST", "LIEN_DB_NAME", "LIEN_DB_USER", "LIEN_DB_PASSWORD"):
            os.environ.pop(k, None)
        a = LienImportApp(root, cfg_path)
    assert a.var_host.get() == ""
    assert a.var_user.get() == ""
    assert a.var_password.get() == ""
    assert a.var_schema.get() == "zm_dba"


def test_connection_string_fills_fields(app):
    app.var_connstr.set("mysql://root:secret@db.example.com:3307/lineitem")
    with mock.patch("lien_import.gui.messagebox.showinfo"):
        app._on_fill_from_connstr()
    assert app.var_host.get() == "db.example.com"
    assert app.var_port.get() == "3307"
    assert app.var_user.get() == "root"
    assert app.var_password.get() == "secret"
    assert app.var_schema.get() == "lineitem"


def test_connection_string_partial_does_not_blank_other_fields(app):
    app.var_user.set("keepme")
    app.var_password.set("keepme-too")
    app.var_connstr.set("db.example.com:3307/lineitem")  # no credentials in the string
    with mock.patch("lien_import.gui.messagebox.showinfo"):
        app._on_fill_from_connstr()
    assert app.var_host.get() == "db.example.com"
    assert app.var_user.get() == "keepme"
    assert app.var_password.get() == "keepme-too"


def test_unparseable_connection_string_warns_and_changes_nothing(app):
    app.var_host.set("already-set")
    app.var_connstr.set("   ")
    with mock.patch("lien_import.gui.messagebox.showinfo") as mock_info:
        app._on_fill_from_connstr()
    mock_info.assert_called_once()
    assert app.var_host.get() == "already-set"


def test_changing_file_invalidates_a_passed_preview(app):
    app._preview_passed_for = ("old.csv", "ES")
    app._refresh_import_button()
    assert app.btn_import.instate(["disabled"])  # key doesn't match current (empty) file

    app.var_file.set("old.csv")
    app.var_source.set("ES")
    app._preview_passed_for = ("old.csv", "ES")
    app._refresh_import_button()
    assert app.btn_import.instate(["!disabled"])

    app.var_file.set("new.csv")  # changed file -> must invalidate
    assert app._preview_passed_for is None
    assert app.btn_import.instate(["disabled"])


def test_changing_source_invalidates_a_passed_preview(app):
    app.var_file.set("some.csv")
    app.var_source.set("ES")
    app._preview_passed_for = ("some.csv", "ES")
    app._refresh_import_button()
    assert app.btn_import.instate(["!disabled"])

    app.var_source.set("TN")  # changed source, same file -> must invalidate
    assert app._preview_passed_for is None
    assert app.btn_import.instate(["disabled"])


def test_import_without_preview_is_refused(app, root):
    app.var_file.set(str(DATA / "ATT-ESS-example.csv"))
    app.var_source.set("ES")
    with mock.patch("lien_import.gui.messagebox.showwarning") as warn, \
         mock.patch("lien_import.gui.messagebox.askyesno") as ask:
        app._on_import()
    warn.assert_called_once()
    ask.assert_not_called()


def test_preview_missing_file_warns(app):
    app.var_file.set(str(DATA / "does_not_exist.csv"))
    app.var_source.set("ES")
    with mock.patch("lien_import.gui.messagebox.showwarning") as warn:
        app._on_preview()
    warn.assert_called_once()


def _point_at_tmp_inbox(app, tmp_path):
    app.cfg.output_dir = tmp_path / "out"
    app.cfg.inbox_dir = tmp_path / "inbox"
    app.cfg.processed_dir = tmp_path / "processed"
    app.cfg.failed_dir = tmp_path / "failed"
    app.cfg.inbox_dir.mkdir()
    return app.cfg.inbox_dir


def test_import_all_disabled_until_inbox_checked(app):
    assert app.btn_import_all.instate(["disabled"])
    with mock.patch("lien_import.gui.messagebox.showwarning") as warn, \
         mock.patch("lien_import.gui.messagebox.askyesno") as ask:
        app._on_import_inbox()
    warn.assert_called_once()
    ask.assert_not_called()


def test_check_all_on_empty_inbox_says_so(app, tmp_path):
    _point_at_tmp_inbox(app, tmp_path)
    with mock.patch("lien_import.gui.messagebox.showinfo") as info:
        app._on_check_inbox()
    info.assert_called_once()
    assert not app.busy


def test_check_all_previews_every_file_then_enables_import_all(app, root, tmp_path):
    import shutil

    inbox = _point_at_tmp_inbox(app, tmp_path)
    shutil.copy(DATA / "ATT-ESS-example.csv", inbox / "es.csv")
    (inbox / "tnu").mkdir()
    shutil.copy(DATA / "Combined-State_example.csv", inbox / "tnu" / "state.csv")

    app._on_check_inbox()
    _pump(root, app)

    assert app.btn_import_all.instate(["!disabled"])
    assert "would be inserted" in app.var_status.get()
    text = app.log_text.get("1.0", "end")
    assert "es.csv" in text and "state.csv" in text
    # preview never moves anything
    assert (inbox / "es.csv").exists() and (inbox / "tnu" / "state.csv").exists()


def test_import_all_refused_when_inbox_changed_after_check(app, root, tmp_path):
    import shutil

    inbox = _point_at_tmp_inbox(app, tmp_path)
    shutil.copy(DATA / "ATT-ESS-example.csv", inbox / "es.csv")
    app._on_check_inbox()
    _pump(root, app)
    assert app.btn_import_all.instate(["!disabled"])

    shutil.copy(DATA / "Combined-State_example.csv", inbox / "late.csv")  # dropped after the check
    with mock.patch("lien_import.gui.messagebox.showwarning") as warn, \
         mock.patch("lien_import.gui.messagebox.askyesno") as ask:
        app._on_import_inbox()
    warn.assert_called_once()
    ask.assert_not_called()
    assert app.btn_import_all.instate(["disabled"])


def test_allow_duplicates_checkbox_feeds_config_and_resets_previews(app):
    assert app._gather_config().imports.allow_duplicates is False
    app.var_file.set("some.csv")
    app._preview_passed_for = ("some.csv", app.var_source.get())
    app._inbox_checked = [("x", 1, 1.0)]
    app.var_allow_dups.set(True)
    assert app._gather_config().imports.allow_duplicates is True
    assert app._preview_passed_for is None and app._inbox_checked is None
    assert app.btn_import.instate(["disabled"]) and app.btn_import_all.instate(["disabled"])


def test_friendly_error_classifies_pymysql_vs_other():
    class FakePymysqlError(Exception):
        __module__ = "pymysql.err"

    exc = FakePymysqlError(1049, "Unknown database 'x'")
    msg = LienImportApp._friendly_error(exc)
    assert "no database with that name" in msg

    msg2 = LienImportApp._friendly_error(ValueError("plain python error"))
    assert msg2 == "plain python error"


# ------------------------------------------------------------- needs live DB

_needs_live_db = pytest.mark.skipif(
    not os.environ.get("LIEN_DB_HOST"),
    reason="requires MySQL; set LIEN_DB_* env vars and point at a throwaway schema",
)


@_needs_live_db
class TestLiveDatabase:
    @pytest.fixture()
    def live_cfg(self):
        from lien_import.config import load_config

        return load_config(None)  # env-only

    @pytest.fixture()
    def fresh_db(self, live_cfg):
        from lien_import import db as dbmod

        sql_dir = Path(__file__).resolve().parents[1] / "sql"
        conn = dbmod.connect(live_cfg)
        with conn.cursor() as cur:
            for t in ("lien_import_log", live_cfg.database.liens_table):
                cur.execute(f"DROP TABLE IF EXISTS `{t}`")
            cur.execute(
                (sql_dir / "liens_reference.sql").read_text(encoding="utf-8")
                .replace("IF NOT EXISTS liens", f"IF NOT EXISTS `{live_cfg.database.liens_table}`")
            )
            cur.execute((sql_dir / "lien_import_log.sql").read_text(encoding="utf-8"))
        conn.commit()
        yield conn
        conn.close()

    def test_connect_preview_import_verify_idempotent(self, app, root, live_cfg, fresh_db):
        db = live_cfg.database
        app.var_host.set(db.host)
        app.var_port.set(str(db.port))
        app.var_schema.set(db.name)
        app.var_user.set(db.user)
        app.var_password.set(db.password)

        app._on_test_connection()
        _pump(root, app)
        assert app.var_conn_status.get().startswith("Connected")

        sample = str(DATA / "ATT-ESS-example.csv")
        app.var_file.set(sample)
        app.var_source.set("ES")
        assert app.btn_import.instate(["disabled"])

        app._on_preview()
        _pump(root, app)
        assert app._preview_passed_for == (sample, "ES")
        assert app.btn_import.instate(["!disabled"])

        with mock.patch("lien_import.gui.messagebox.askyesno", return_value=True):
            app._on_import()
        _pump(root, app)
        assert "Import complete" in app.var_status.get()

        app._on_verify()
        _pump(root, app)
        assert "25" in app.var_status.get()

        # re-run: idempotent, zero new rows
        with mock.patch("lien_import.gui.messagebox.askyesno", return_value=True):
            app._on_preview()
            _pump(root, app)
            app._on_import()
            _pump(root, app)
        assert "0 written" in app.var_status.get() or "Import complete - 0" in app.var_status.get()

    def test_check_all_then_import_all_moves_files(self, app, root, live_cfg, fresh_db, tmp_path):
        import shutil

        db = live_cfg.database
        app.var_host.set(db.host)
        app.var_port.set(str(db.port))
        app.var_schema.set(db.name)
        app.var_user.set(db.user)
        app.var_password.set(db.password)
        with fresh_db.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS `lien_import_files`")
        fresh_db.commit()

        inbox = _point_at_tmp_inbox(app, tmp_path)
        shutil.copy(DATA / "ATT-ESS-example.csv", inbox / "es.csv")

        app._on_check_inbox()
        _pump(root, app)
        with mock.patch("lien_import.gui.messagebox.askyesno", return_value=True):
            app._on_import_inbox()
        _pump(root, app)

        assert "Import All complete - 1 file" in app.var_status.get()
        assert not (inbox / "es.csv").exists()
        assert [p.name for p in (tmp_path / "processed").rglob("*.csv")] == ["es.csv"]
        assert app.btn_import_all.instate(["disabled"])  # must check again before the next run
