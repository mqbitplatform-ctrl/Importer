# Lien Import - Quick Start

A short guide for running the lien import tool. No technical knowledge needed.

---

## What you need first (ask the developer / DBA for these)

- The **database details**: server address (host), database name, username, password.
- The location of the **data files** to import (the ZIP archives or CSV files).

---

## Were you given `LienImport-Setup-1.0.0.exe`? Use this instead of Step 1

1. Double-click **`LienImport-Setup-1.0.0.exe`**. No administrator rights and no
   Python are needed. If Windows shows "Windows protected your PC", click
   **More info** → **Run anyway** (the installer is not code-signed).
2. Click **Next** / **Install**, then **Finish**. The **Lien Import** window
   opens, and a **Lien Import** icon is now on your desktop.
3. From now on, just double-click that desktop icon. Follow **Step 2A** below
   (connect to the database, then the inbox).

Your own files are in **`Documents\Lien Import`**: `lien-data\inbox` (drop
files here), `lien-data\processed`, `lien-data\failed`, the reports in
`output`, and your saved settings in `config.json`. Uninstalling (Windows
Settings → Apps → Lien Import) removes the program but **keeps** this folder.

---

## Step 1 - One-time setup (do this once)

1. Open the `lien-import` folder.
2. Double-click **`setup.bat`**.
3. It checks a few things and installs what it needs (needs internet the first time).
4. **Notepad opens `config.json`.** You can close it straight away if you plan
   to use the window (Step 2A) - you'll type the details in there instead.
   Otherwise, in the `"database"` section, replace each `REPLACE_ME`:

   ```
   "host":     "REPLACE_ME",     <- the database server address
   "name":     "zm_dba",         <- the database (already filled in)
   "user":     "REPLACE_ME",     <- the login name
   "password": "REPLACE_ME",     <- the login password
   ```

   Keep the quotation marks. Save the file (Ctrl+S) and close Notepad.

   **`name` and `user` are different.** `user` is who logs in (may be `root`).
   `name` is the database that holds the `liens` table - for this project that
   is **`zm_dba`** (on the MySQL 5.6 server).
5. Setup is finished.

If `setup.bat` says Python is missing, install it from
<https://www.python.org/downloads/> - **tick "Add python.exe to PATH"** on the
first screen - then run `setup.bat` again.

---

## The easiest way for many files: the INBOX folder

You do **not** need to import files one by one, or say which source each file is.

1. Copy the files into the **inbox** folder: `lien-import\lien-data\inbox`.
   You can drop **whole folders** (e.g. `ATT-ESS-May-2024-to-July-2025-no-Dec-2024`,
   `TNU-Starter-Full-List`, `Combined-TNU_2024-02-29`), loose CSV files, or `.zip` files,
   all mixed together. (The window's **Open Inbox Folder** button, or menu **F**,
   opens it for you.)
2. **Check All (Preview)** in the window, or menu **A**. The tool:
   - works out the source of every file by itself (ATT/ESS or TNU),
   - shows how many liens *would* be added per source - nothing is written yet,
   - lists any file it can't recognise.
3. If the numbers look right: **Import All** (window), or type `IMPORT` (menu **A**).

What happens to each file:

| Result | Where the file goes |
|---|---|
| imported | `lien-data\processed\<date>\...` (same sub-folders as in the inbox) |
| not recognised, or failed | `lien-data\failed\<date>\...` with a `.reason.txt` next to it saying why |
| exact same file imported before (even if renamed) | skipped, moved to `processed` |

**Nothing is ever imported twice.** The tool remembers every imported file by
its content, and every lien by its own ID, so the same lien in two different
files is added only once.

**Allow duplicates (only if you were asked to):** tick **Allow duplicates** in the
window (or answer `Y` in menu **A**). Then a lien that appears in several files is
added once per file instead of once in total. The same file is still never imported
twice. Pick one way per source and keep it - switching later adds those liens again.

A file that failed: read its `.reason.txt`, fix the problem, copy the file
back into the inbox, and run it again.

---

## Step 2A - The easy way: the window

Double-click **`lien-import-gui.bat`**. A window opens with four boxes
(box **2** is the inbox - see the section above):

**1) Connect to the database**
- If you were given a single line like `mysql://user:password@host:3306/zm_dba`,
  paste it into **Connection string** and click **Fill fields below**.
- Or just type **Host**, **Port** (usually 3306), **Username**, **Password**.
- **Database / schema** is already set to **`zm_dba`** - leave it unless told otherwise.
- Click **Test Connection**. You want to see
  `Connected - MySQL ... - table 'liens' found`.
- Click **Save** so you don't have to type it again next time.

**2) Import EVERYTHING in the inbox folder** - see the inbox section above.

**3) Or: one file at a time**
- **Choose File / ZIP...** for one file or a zip, or **Choose Folder...** for a folder.
- Pick the **Source**: **ATT / ESS**, or **TNU** (TNU covers Combined-Federal,
  Combined-State, *and* TNU Starter).

**4) Run for that one file**
- **Check File (Preview)** - reads the file, shows counts, changes nothing.
- **Import** - only becomes clickable after a preview of *that same file*.
  It asks you to confirm before writing anything.
- **Verify Counts** - shows how many rows are now in the database for that source.

Everything that happens is shown in the **Results** box. If something fails,
the message there says what to fix.

---

## Step 2B - The text menu (all tools, including FAT)

Double-click **`lien-import.bat`**. A menu appears:

```
  F  Open the INBOX folder   (drop files / whole folders / zips there)
  A  Import EVERYTHING in the inbox

  1  Look at a data file            (list its columns)
  2  Check a file BEFORE importing  (counts + report, no changes)
  3  Import a file into the database
  4  Verify import counts
  5  Full statistics report
  6  See how many liens match the FAT rules
  7  Create a FAT pull
  8  Show FAT pull history
  0  Exit
```

```
  9  Test the database connection   (run this first if the DB settings are new)
  L  Create a LOCAL practice database (only on your own PC, for trying things)
```

Type a number (or `L`), press Enter, and follow the prompts.

**First time, or after changing `config.json`:** run **9**. It says either
`OK - connected ... table 'liens' found` or exactly what to fix.

**Just want to practise without the real server?** Run **L**. It builds a
practice database on your own PC (127.0.0.1) using the `name` from `config.json`,
with empty copies of all the tables. Then options 2 / 3 / 4 all work against it.

When it asks for a file, you can **drag the file (or folder, or .zip) onto the
window** instead of typing the path.

When it asks which source, choose **1 for ATT/ESS** or **2 for TNU**.

> **"Source" is the provider, not Federal vs State.** There are only two:
> ATT/ESS (1) and TNU (2). `Combined-Federal`, `Combined-State`, and
> `TNU Starter Full List` are **all TNU → all use option 2**. The tool marks
> each lien Federal or State by itself. You can also point it at a whole folder
> or `.zip` and it handles every file inside in one go.

---

## The normal order for importing a new file

1. **Menu 2 - Check the file.** It reads the file, works out every value, and
   writes a report. Nothing is changed in the database.
2. **Open the report.** In the `lien-import` folder, open `output`, then the
   newest sub-folder. Read `audit_ES.txt` (or `audit_TN.txt`):
   - `records that WOULD be inserted` - how many will be added
   - `missing required values` / `rejected for other reasons` - rows that will
     be skipped (details in `rejects_ES.csv`)
   - `Trust/Estate` / `Ambiguous` - rows held back on purpose (in `held_ES.csv`)
   - If something looks wrong, **stop and tell the developer.**
3. **Menu 3 - Import.** It checks the file once more, shows the numbers, and asks
   you to type `IMPORT` to confirm. Only then does it write to the database.
4. **Menu 4 - Verify.** Confirms the row count in the database matches the report.
5. Running the same import again is safe - it will add `0` rows the second time.

If an import is interrupted (power cut, closed window), just run **Menu 3**
again with the same file - it carries on from where it stopped.

---

## Free America Tax (FAT)

- **Menu 6** - shows how many liens currently match the FAT rules (Federal,
  Individual, $5,000 or more, not already pulled), and the **highest Case ID**
  used so far. Nothing is changed.
- **Menu 8** - lists every past pull: date, how many liens, and the Case ID range.
- **Menu 7** - creates a pull:
  1. Give it a name (e.g. `FAT-2026-10`).
  2. Type **how many liens** to pull (past pulls were 10,000 to 14,000).
  3. Review the preview - nothing has been written yet.
  4. Type the **first Case ID that Logics gave you** for this pull. Each lien gets
     the next number in order.
  5. Type `PULL` to confirm.

  It records the pull in the same place the old manual process did, so those liens
  will never be pulled for Free America Tax again, and writes a CSV (with the Case
  IDs) in the newest `output` sub-folder for the mail job.

  The tool **refuses** a Case ID that isn't higher than every Case ID already used -
  that's almost always a typo. Nothing is written if it refuses.

---

## Where things are saved

Everything a run produces goes in the **`output`** folder, in a sub-folder named
with the date and time. Nothing is ever deleted from there - old runs stay for
reference. An inbox run also writes `auto_import_files.csv` (one line per file:
what happened, how many liens, where it was moved).

Data files themselves live under **`lien-data`**: `inbox` (waiting),
`processed` (done), `failed` (needs attention).

---

## If something goes wrong

- Take a screenshot of the window.
- Note which menu option you used and which file.
- Zip the newest sub-folder inside `output` (it contains `run.log`).
- Send all of that to the developer.
