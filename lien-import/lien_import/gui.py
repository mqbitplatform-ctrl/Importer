"""Lien Import - simple desktop GUI.

For a non-technical operator: connect to the database by pasting a
connection string and/or filling in the fields (including the database /
schema name), pick a source file, preview it, then import. Every action
calls the exact same ``lien_import`` pipeline the command line / batch
launcher use - this is a new front end, not a second implementation.

Launch:
    python -m lien_import.gui
    (or double-click lien-import-gui.bat, which launches this with pythonw)

Design notes:
  * All non-UI logic (connection-string parsing, config load/save, the
    pipeline run itself) lives in plain functions/modules that are unit
    tested without a display - see connstr.py, config.py, and the pipeline/
    db modules. This file only wires widgets to those.
  * Database and file-import work runs on a background thread so the window
    never freezes; results reach the UI only through a thread-safe queue,
    polled on the Tk main loop (`root.after`) - the only safe way to update
    Tk widgets from another thread.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Optional

from . import db as dbmod
from .config import AppConfig, DbConfig, load_config, save_config
from .connstr import parse_connection_string
from .logging_setup import setup_logging

SOURCES = [("ATT / ESS", "ES"), ("TNU (Combined-Federal / Combined-State / TNU Starter)", "TN")]

# The Zairmail lien database (MySQL 5.6 instance, per the client). Pre-filled
# when no schema has been saved yet; the user can still overwrite it.
DEFAULT_SCHEMA = "zm_dba"


class _QueueLogHandler(logging.Handler):
    """Pushes formatted log lines into a queue for the UI thread to drain."""

    def __init__(self, q: "queue.Queue[tuple[str, object]]"):
        super().__init__()
        self._q = q
        self.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._q.put(("log", self.format(record)))
        except Exception:  # pragma: no cover - logging must never raise
            pass


class LienImportApp:
    """Tkinter is not thread-safe: a worker thread must never touch a widget
    or call ``root.after`` directly. Every background method in this class
    only ever puts an ``(event_name, payload)`` tuple on ``self.events`` -
    ``_poll_events`` (scheduled on the main thread via ``root.after``) is the
    single place that drains the queue and updates the UI."""

    def __init__(self, root: tk.Tk, config_path: Path):
        self.root = root
        self.config_path = config_path
        self.cfg: AppConfig = self._load_config_safely()

        self.events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.log_queue = self.events  # log handler target; same queue, kind="log"
        self.busy = False
        self._preview_passed_for: Optional[tuple[str, str]] = None
        # inbox contents (path, size, mtime) when "Check All" last passed;
        # "Import All" is refused if the inbox has changed since
        self._inbox_checked: Optional[list[tuple[str, int, float]]] = None

        root.title("Lien Import")
        root.geometry("760x780")
        root.minsize(680, 640)

        self._build_widgets()
        self._load_fields_from_config()
        self.root.after(150, self._poll_events)

    # ------------------------------------------------------------ config

    def _load_config_safely(self) -> AppConfig:
        try:
            if self.config_path.is_file():
                return load_config(self.config_path)
        except Exception:
            pass
        return AppConfig()

    def _load_fields_from_config(self) -> None:
        db = self.cfg.database

        def real(v: str) -> str:  # hide config.example.json placeholders
            return "" if v == "REPLACE_ME" else (v or "")

        self.var_host.set(real(db.host))
        self.var_port.set(str(db.port or 3306))
        self.var_user.set(real(db.user))
        self.var_password.set(real(db.password))
        name = db.name if db.name and db.name != "REPLACE_ME" else DEFAULT_SCHEMA
        self.var_schema.set(name)

    # ------------------------------------------------------------- build

    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # ---- 1. Connect to the database ---------------------------------
        conn_frame = ttk.LabelFrame(self.root, text="1) Connect to the database")
        conn_frame.pack(fill="x", **pad)
        conn_frame.columnconfigure(1, weight=1)

        ttk.Label(conn_frame, text="Connection string (optional):").grid(
            row=0, column=0, sticky="w", **pad
        )
        self.var_connstr = tk.StringVar()
        ttk.Entry(conn_frame, textvariable=self.var_connstr).grid(
            row=0, column=1, sticky="ew", **pad
        )
        ttk.Button(conn_frame, text="Fill fields below", command=self._on_fill_from_connstr).grid(
            row=0, column=2, **pad
        )
        ttk.Label(
            conn_frame,
            text="e.g. mysql://user:password@host:3306/database - or just paste what you were given",
            foreground="#666",
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=8)

        self.var_host = tk.StringVar()
        self.var_port = tk.StringVar(value="3306")
        self.var_user = tk.StringVar()
        self.var_password = tk.StringVar()
        self.var_schema = tk.StringVar()

        ttk.Label(conn_frame, text="Host:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(conn_frame, textvariable=self.var_host).grid(row=2, column=1, sticky="ew", **pad)

        row3 = ttk.Frame(conn_frame)
        row3.grid(row=3, column=0, columnspan=3, sticky="ew")
        row3.columnconfigure(1, weight=0)
        row3.columnconfigure(3, weight=1)
        ttk.Label(row3, text="Port:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(row3, textvariable=self.var_port, width=8).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(row3, text="Database / schema:").grid(row=0, column=2, sticky="w", **pad)
        ttk.Entry(row3, textvariable=self.var_schema).grid(row=0, column=3, sticky="ew", **pad)

        ttk.Label(conn_frame, text="Username:").grid(row=4, column=0, sticky="w", **pad)
        ttk.Entry(conn_frame, textvariable=self.var_user).grid(row=4, column=1, sticky="ew", **pad)
        ttk.Label(conn_frame, text="Password:").grid(row=5, column=0, sticky="w", **pad)
        ttk.Entry(conn_frame, textvariable=self.var_password, show="*").grid(
            row=5, column=1, sticky="ew", **pad
        )

        btn_row = ttk.Frame(conn_frame)
        btn_row.grid(row=6, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Button(btn_row, text="Test Connection", command=self._on_test_connection).pack(
            side="left"
        )
        ttk.Button(btn_row, text="Save", command=self._on_save_config).pack(side="left", padx=8)
        self.var_conn_status = tk.StringVar(value="Not tested")
        ttk.Label(btn_row, textvariable=self.var_conn_status, foreground="#666").pack(
            side="left", padx=8
        )

        # ---- 2. Automatic: everything in the inbox -------------------------
        inbox_frame = ttk.LabelFrame(
            self.root, text="2) Import EVERYTHING in the inbox folder (recommended)"
        )
        inbox_frame.pack(fill="x", **pad)
        self.var_inbox = tk.StringVar(value=str(Path(self.cfg.inbox_dir).resolve()))
        ttk.Label(
            inbox_frame,
            text="Drop files, whole folders or ZIPs into the inbox. The source of each file is "
                 "found automatically; a file or lien already imported is never imported again; "
                 "finished files move to 'processed', problem files to 'failed'.",
            foreground="#666", wraplength=700, justify="left",
        ).pack(fill="x", **pad)
        ttk.Label(inbox_frame, textvariable=self.var_inbox).pack(fill="x", padx=8)
        inbox_row = ttk.Frame(inbox_frame)
        inbox_row.pack(fill="x", **pad)
        ttk.Button(inbox_row, text="Open Inbox Folder", command=self._on_open_inbox).pack(
            side="left"
        )
        ttk.Button(inbox_row, text="Check All (Preview)", command=self._on_check_inbox).pack(
            side="left", padx=8
        )
        self.btn_import_all = ttk.Button(
            inbox_row, text="Import All", command=self._on_import_inbox, state="disabled"
        )
        self.btn_import_all.pack(side="left")

        # ---- 3. Choose the file ------------------------------------------
        file_frame = ttk.LabelFrame(self.root, text="3) Or: one file at a time")
        file_frame.pack(fill="x", **pad)
        file_frame.columnconfigure(0, weight=1)

        self.var_file = tk.StringVar()
        file_row = ttk.Frame(file_frame)
        file_row.grid(row=0, column=0, sticky="ew", **pad)
        file_row.columnconfigure(0, weight=1)
        ttk.Entry(file_row, textvariable=self.var_file).grid(row=0, column=0, sticky="ew")
        ttk.Button(file_row, text="Choose File / ZIP...", command=self._on_browse_file).grid(
            row=0, column=1, padx=4
        )
        ttk.Button(file_row, text="Choose Folder...", command=self._on_browse_folder).grid(
            row=0, column=2
        )

        source_row = ttk.Frame(file_frame)
        source_row.grid(row=1, column=0, sticky="w", **pad)
        ttk.Label(source_row, text="Source:").pack(side="left", padx=(0, 8))
        self.var_source = tk.StringVar(value="ES")
        for label, code in SOURCES:
            ttk.Radiobutton(
                source_row, text=label, variable=self.var_source, value=code,
            ).pack(side="left", padx=4)
        # a trace (not `command=`) so this fires whether the value changes by
        # a click or programmatically (e.g. from a test, or a future "load a
        # saved job" feature) - keeps file and source invalidation symmetric
        self.var_file.trace_add("write", lambda *_: self._invalidate_preview())
        self.var_source.trace_add("write", lambda *_: self._invalidate_preview())

        # ---- 4. Run --------------------------------------------------------
        run_frame = ttk.LabelFrame(self.root, text="4) Run for that one file")
        run_frame.pack(fill="x", **pad)
        run_row = ttk.Frame(run_frame)
        run_row.pack(fill="x", **pad)
        ttk.Button(run_row, text="Check File (Preview)", command=self._on_preview).pack(
            side="left"
        )
        self.btn_import = ttk.Button(
            run_row, text="Import", command=self._on_import, state="disabled"
        )
        self.btn_import.pack(side="left", padx=8)
        ttk.Button(run_row, text="Verify Counts", command=self._on_verify).pack(side="left", padx=8)

        # ---- Option shared by boxes 2 and 4 -------------------------------
        self.var_allow_dups = tk.BooleanVar(value=self.cfg.imports.allow_duplicates)
        ttk.Checkbutton(
            self.root, variable=self.var_allow_dups,
            text="Allow duplicates - keep a lien that repeats in several files as separate rows "
                 "(the same file is still never imported twice)",
        ).pack(fill="x", padx=12, pady=(0, 4))
        self.var_allow_dups.trace_add("write", lambda *_: self._on_allow_dups_changed())

        # ---- Results ---------------------------------------------------
        out_frame = ttk.LabelFrame(self.root, text="Results")
        out_frame.pack(fill="both", expand=True, **pad)
        self.log_text = scrolledtext.ScrolledText(out_frame, height=10, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.log_text.tag_config("ok", foreground="#116611")
        self.log_text.tag_config("err", foreground="#aa1111")
        self.log_text.tag_config("hdr", font=("TkDefaultFont", 10, "bold"))

        self.var_status = tk.StringVar(value="Idle")
        ttk.Label(self.root, textvariable=self.var_status, foreground="#666").pack(
            fill="x", padx=12, pady=(0, 8)
        )

    # ------------------------------------------------------------- helpers

    def _append(self, text: str, tag: Optional[str] = None) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n", (tag,) if tag else ())
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append(payload)
                elif kind == "test_connection_done":
                    self._test_connection_done(*payload)
                elif kind == "pipeline_done":
                    self._pipeline_done(*payload)
                elif kind == "pipeline_failed":
                    self._pipeline_failed(*payload)
                elif kind == "verify_done":
                    self._verify_done(*payload)
                elif kind == "status":
                    self.var_status.set(payload)
                elif kind == "batch_done":
                    self._batch_done(*payload)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_events)

    def _set_busy(self, busy: bool, status: str = "") -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for child in self.root.winfo_children():
            self._set_tree_state(child, state)
        if busy:
            self.var_status.set(status or "Working...")
        else:
            self.var_status.set(status or "Idle")
            self._refresh_import_button()
            self.btn_import_all.configure(
                state="normal" if self._inbox_checked else "disabled"
            )

    def _set_tree_state(self, widget, state: str) -> None:
        if isinstance(widget, (ttk.Button, ttk.Entry, ttk.Radiobutton, ttk.Checkbutton)):
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass
        for child in widget.winfo_children():
            self._set_tree_state(child, state)

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        if type(exc).__module__.startswith("pymysql"):
            return dbmod.friendly_connect_error(exc, where="the Database panel above")
        return str(exc)

    def _invalidate_preview(self) -> None:
        self._preview_passed_for = None
        self._refresh_import_button()

    def _dups_line(self) -> str:
        if self.var_allow_dups.get():
            return "\nDUPLICATES ALLOWED: a lien repeated in several files is inserted once per row.\n"
        return ""

    def _on_allow_dups_changed(self) -> None:
        # a preview's numbers depend on this option - both previews must be redone
        self._invalidate_preview()
        self._inbox_checked = None
        self.btn_import_all.configure(state="disabled")

    def _refresh_import_button(self) -> None:
        key = (self.var_file.get().strip(), self.var_source.get())
        ok = self._preview_passed_for == key and key[0]
        self.btn_import.configure(state="normal" if ok else "disabled")

    def _gather_config(self) -> AppConfig:
        imports = dataclasses.replace(
            self.cfg.imports, allow_duplicates=bool(self.var_allow_dups.get())
        )
        cfg = AppConfig(database=self.cfg.database, imports=imports,
                        fat=self.cfg.fat, output_dir=self.cfg.output_dir,
                        inbox_dir=self.cfg.inbox_dir, processed_dir=self.cfg.processed_dir,
                        failed_dir=self.cfg.failed_dir)
        try:
            port = int(self.var_port.get().strip() or 3306)
        except ValueError:
            port = 3306
        cfg.database = DbConfig(
            host=self.var_host.get().strip(),
            port=port,
            name=self.var_schema.get().strip(),
            user=self.var_user.get().strip(),
            password=self.var_password.get(),
            charset=self.cfg.database.charset or "utf8mb4",
            liens_table=self.cfg.database.liens_table or "liens",
        )
        self.cfg = cfg
        return cfg

    def _run_dir(self, tag: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return self._gather_config().output_dir / f"{stamp}_gui_{tag}"

    def _start_logging(self, run_dir: Optional[Path]) -> None:
        setup_logging(run_dir, logging.INFO)
        logging.getLogger("lien_import").addHandler(_QueueLogHandler(self.log_queue))

    # --------------------------------------------------------------- actions

    def _on_fill_from_connstr(self) -> None:
        parsed = parse_connection_string(self.var_connstr.get())
        if parsed.is_empty():
            messagebox.showinfo("Lien Import", "Could not find connection details in that text.")
            return
        if parsed.host:
            self.var_host.set(parsed.host)
        if parsed.port:
            self.var_port.set(str(parsed.port))
        if parsed.user:
            self.var_user.set(parsed.user)
        if parsed.password:
            self.var_password.set(parsed.password)
        if parsed.database:
            self.var_schema.set(parsed.database)
        self.var_conn_status.set("Fields updated - review, then Test Connection")

    def _on_save_config(self) -> None:
        cfg = self._gather_config()
        try:
            save_config(cfg, self.config_path)
        except OSError as exc:
            messagebox.showerror("Lien Import", f"Could not save settings:\n{exc}")
            return
        messagebox.showinfo("Lien Import", f"Settings saved to {self.config_path}")

    def _on_test_connection(self) -> None:
        cfg = self._gather_config()
        if not cfg.database.is_configured:
            messagebox.showwarning(
                "Lien Import", "Fill in at least Host, Database/schema, and Username first."
            )
            return
        self._set_busy(True, "Testing database connection...")
        self.var_conn_status.set("Testing...")
        threading.Thread(target=self._test_connection_worker, args=(cfg,), daemon=True).start()

    def _test_connection_worker(self, cfg: AppConfig) -> None:
        try:
            conn = dbmod.connect(cfg)
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT VERSION()")
                    version = cur.fetchone()[0]
                has_liens = dbmod.table_exists(conn, cfg.database.liens_table)
                row_count = dbmod.count_by_source(conn, cfg.database.liens_table, "LN") if has_liens else 0
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not re-raised
            msg = self._friendly_error(exc)
            self.events.put(("test_connection_done", (False, msg)))
            return
        detail = f"MySQL {version}"
        if has_liens:
            detail += f" - table '{cfg.database.liens_table}' found ({row_count:,} LN rows)"
        else:
            detail += f" - table '{cfg.database.liens_table}' NOT found"
        self.events.put(("test_connection_done", (True, detail)))

    def _test_connection_done(self, ok: bool, detail: str) -> None:
        self.var_conn_status.set(("Connected - " if ok else "Failed - ") + detail)
        self._append("")
        self._append(("CONNECTION OK" if ok else "CONNECTION FAILED"), "hdr")
        self._append(detail, "ok" if ok else "err")
        self._set_busy(False)

    def _on_browse_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a lien data file",
            filetypes=[("CSV or ZIP", "*.csv *.zip"), ("All files", "*.*")],
        )
        if path:
            self.var_file.set(path)

    def _on_browse_folder(self) -> None:
        path = filedialog.askdirectory(title="Choose a folder of lien data files")
        if path:
            self.var_file.set(path)

    def _on_preview(self) -> None:
        self._run_pipeline(mode="preview", commit=False)

    def _on_import(self) -> None:
        file_path = self.var_file.get().strip()
        source = self.var_source.get()
        if self._preview_passed_for != (file_path, source):
            messagebox.showwarning("Lien Import", "Run 'Check File (Preview)' on this file first.")
            return
        if not messagebox.askyesno(
            "Confirm Import",
            f"This will write records into the database.\n\n"
            f"File: {file_path}\nSource: {source}\n{self._dups_line()}\nContinue?",
        ):
            return
        self._run_pipeline(mode="import", commit=True)

    def _run_pipeline(self, *, mode: str, commit: bool) -> None:
        file_path = self.var_file.get().strip()
        source = self.var_source.get()
        if not file_path:
            messagebox.showwarning("Lien Import", "Choose a file or folder first.")
            return
        if not Path(file_path).exists():
            messagebox.showwarning("Lien Import", f"Not found: {file_path}")
            return
        cfg = self._gather_config()
        if mode == "import" and not cfg.database.is_configured:
            messagebox.showwarning("Lien Import", "Fill in and test the database connection first.")
            return

        run_dir = self._run_dir(mode)
        self._start_logging(run_dir)
        label = "Checking file" if mode == "preview" else "Importing"
        self._set_busy(True, f"{label}...")
        self._append("")
        self._append(f"{'PREVIEW' if mode == 'preview' else 'IMPORT'} - {file_path} ({source})", "hdr")
        threading.Thread(
            target=self._pipeline_worker, args=(cfg, run_dir, file_path, source, mode, commit),
            daemon=True,
        ).start()

    def _pipeline_worker(self, cfg, run_dir, file_path, source, mode, commit) -> None:
        from .pipeline import run as run_pipeline

        try:
            result = run_pipeline(
                source_code=source, input_path=file_path, cfg=cfg, run_dir=run_dir,
                mode=mode, commit=commit,
            )
        except Exception as exc:  # noqa: BLE001
            self.events.put(("pipeline_failed", (mode, self._friendly_error(exc))))
            return
        self.events.put(("pipeline_done", (mode, result, file_path, source, run_dir)))

    def _pipeline_failed(self, mode: str, msg: str) -> None:
        self._append(f"{mode.upper()} FAILED", "hdr")
        self._append(msg, "err")
        self._set_busy(False, f"{mode.title()} failed - see Results")

    def _pipeline_done(self, mode, result, file_path, source, run_dir) -> None:
        a = result.audit
        self._append(a.render_text())
        if mode == "preview":
            self._preview_passed_for = (file_path, source)
            self._append(
                f"OK - {a.would_insert:,} record(s) would be inserted "
                f"({a.rejected_missing + a.rejected_invalid:,} rejected, "
                f"{a.held_trust_estate + a.held_ambiguous:,} held). "
                f"Full report: {run_dir}", "ok",
            )
            self._set_busy(False, f"Preview done - {a.would_insert:,} would be inserted")
        else:
            if result.committed:
                self._append(f"IMPORTED - {result.inserted:,} record(s) written.", "ok")
                self._set_busy(False, f"Import complete - {result.inserted:,} written")
            elif result.stopped_early:
                self._append(
                    f"PARTIALLY IMPORTED - {result.inserted:,} written, then stopped "
                    f"(size limit). Re-run the same import to finish safely.", "err",
                )
                self._set_busy(False, "Import stopped partway - re-run to finish")
            else:
                self._append("IMPORT DID NOT WRITE ANYTHING - see the report above.", "err")
                self._set_busy(False, "Import failed")
            self._preview_passed_for = None

    # ------------------------------------------------------------ inbox

    def _inbox_snapshot(self) -> list[tuple[str, int, float]]:
        from .batch import scan_inbox

        snap = []
        for p in scan_inbox(Path(self.cfg.inbox_dir)):
            st = p.stat()
            snap.append((str(p), st.st_size, st.st_mtime))
        return snap

    def _on_open_inbox(self) -> None:
        inbox = Path(self.cfg.inbox_dir).resolve()
        inbox.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(inbox)  # Windows Explorer
        except (AttributeError, OSError) as exc:
            messagebox.showinfo("Lien Import", f"Inbox folder:\n{inbox}\n\n({exc})")

    def _on_check_inbox(self) -> None:
        self._run_batch(commit=False)

    def _on_import_inbox(self) -> None:
        if not self._inbox_checked:
            messagebox.showwarning("Lien Import", "Run 'Check All (Preview)' first.")
            return
        if self._inbox_snapshot() != self._inbox_checked:
            self._inbox_checked = None
            self.btn_import_all.configure(state="disabled")
            messagebox.showwarning(
                "Lien Import",
                "Files in the inbox changed since the check. Run 'Check All (Preview)' again.",
            )
            return
        if not messagebox.askyesno(
            "Confirm Import",
            f"This will import every file in the inbox ({len(self._inbox_checked)} file(s)) "
            f"into the database, then move each finished file to 'processed'.\n"
            f"{self._dups_line()}\nContinue?",
        ):
            return
        self._run_batch(commit=True)

    def _run_batch(self, *, commit: bool) -> None:
        cfg = self._gather_config()
        if commit and not cfg.database.is_configured:
            messagebox.showwarning("Lien Import", "Fill in and test the database connection first.")
            return
        inbox = Path(cfg.inbox_dir)
        inbox.mkdir(parents=True, exist_ok=True)
        snapshot = self._inbox_snapshot()
        if not snapshot:
            messagebox.showinfo(
                "Lien Import",
                f"The inbox is empty:\n{inbox.resolve()}\n\n"
                "Copy files, folders or ZIPs there (use 'Open Inbox Folder'), then try again.",
            )
            return
        run_dir = self._run_dir("import-all" if commit else "check-all")
        self._start_logging(run_dir)
        self._set_busy(True, "Importing all files..." if commit else "Checking all files...")
        self._append("")
        self._append(f"{'IMPORT ALL' if commit else 'CHECK ALL'} - {inbox.resolve()}", "hdr")
        threading.Thread(
            target=self._batch_worker, args=(cfg, run_dir, commit, snapshot), daemon=True
        ).start()

    def _batch_worker(self, cfg, run_dir, commit, snapshot) -> None:
        from .batch import run_batch

        def progress(i: int, n: int, msg: str) -> None:
            self.events.put(("status", f"[{i}/{n}] {msg}"))

        try:
            result = run_batch(cfg, commit=commit, run_dir=run_dir, progress=progress)
        except Exception as exc:  # noqa: BLE001
            self.events.put(("pipeline_failed", (
                "import all" if commit else "check all", self._friendly_error(exc)
            )))
            return
        self.events.put(("batch_done", (commit, result, snapshot)))

    def _batch_done(self, commit, result, snapshot) -> None:
        self._append(result.render())
        c = result.counts()
        if not commit:
            self._inbox_checked = snapshot
            would = sum(s["would_insert"] for s in result.source_totals.values())
            self._append(
                f"OK - {would:,} record(s) would be inserted. Review the list, then 'Import All'.",
                "ok",
            )
            self._set_busy(False, f"Check done - {would:,} would be inserted")
            return
        self._inbox_checked = None
        bad = c.get("failed", 0) + c.get("stopped", 0)
        done = c.get("imported", 0)
        if bad:
            self._append(
                f"{done} file(s) imported, {bad} failed - failed files are in "
                f"{Path(self.cfg.failed_dir).resolve()} with a .reason.txt each.", "err",
            )
            self._set_busy(False, f"Import All finished with {bad} failure(s)")
        else:
            self._append(f"IMPORTED - {done} file(s) imported and moved to 'processed'.", "ok")
            self._set_busy(False, f"Import All complete - {done} file(s)")

    def _on_verify(self) -> None:
        cfg = self._gather_config()
        if not cfg.database.is_configured:
            messagebox.showwarning("Lien Import", "Fill in and test the database connection first.")
            return
        source = self.var_source.get()
        self._set_busy(True, "Checking row counts...")
        self._append("")
        self._append(f"VERIFY - source {source}", "hdr")
        threading.Thread(target=self._verify_worker, args=(cfg, source), daemon=True).start()

    def _verify_worker(self, cfg: AppConfig, source: str) -> None:
        try:
            conn = dbmod.connect(cfg)
            try:
                n = dbmod.count_by_source(conn, cfg.database.liens_table, source)
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            self.events.put(("pipeline_failed", ("verify", self._friendly_error(exc))))
            return
        self.events.put(("verify_done", (cfg, source, n)))

    def _verify_done(self, cfg: AppConfig, source: str, n: int) -> None:
        self._append(f"{cfg.database.liens_table}: source {source} -> {n:,} rows", "ok")
        self._set_busy(False, f"{n:,} rows for source {source}")


def main() -> int:
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - environment dependent
        print(f"Could not start the graphical window: {exc}\n"
              "On Windows, reinstall Python from python.org with 'tcl/tk' included.")
        return 1
    app = LienImportApp(root, Path("config.json"))
    _ = app
    root.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
