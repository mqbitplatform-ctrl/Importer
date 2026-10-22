# Lien Import - Complete Guide: Build, Install, Use, Release

Who does what:

| Part | Who | How often |
|---|---|---|
| A. Prepare the build PC | Developer | Once |
| B. Build the installer | Developer | Every release |
| C. Test and deliver | Developer | Every release |
| D. Install on the user's PC | End user | Once (and for each update) |
| E. First-time connection | End user | Once |
| F. Daily use | End user | Every time there are new files |
| G. Release a new version | Developer | After any code change |
| H. Troubleshooting | Both | When needed |

---

## A. Prepare the build PC (developer, one time)

The build PC is the computer where the code lives
(`D:\clients\MT\AmericanTax\lien-import`). The end user's PC needs **none** of this.

1. **Python 3.11 or newer**
   - Check: open a command window and type `python --version`.
   - If missing: download it from https://www.python.org/downloads/ and, on the first
     install screen, tick **"Add python.exe to PATH"**.
2. **Inno Setup 6** (makes the Setup.exe)
   - Open PowerShell and run:
     ```
     winget install --id JRSoftware.InnoSetup -e
     ```
   - Or download it from https://jrsoftware.org/isdl.php and install it with the defaults.
3. **Internet connection** for the first build (it downloads PyInstaller once).

---

## B. Build the installer (developer, every release)

1. Open the folder `D:\clients\MT\AmericanTax\lien-import`.
2. **Run the tests first** (open a command window in that folder):
   ```
   cd /d D:\clients\MT\AmericanTax\lien-import
   python -m pytest
   ```
   Everything must pass. If something fails, fix it before building.
3. **Build:**
   - First release: double-click **`build-installer.bat`** (version 1.0.0), or
   - Any later release: in the command window type
     ```
     build-installer.bat 1.0.1
     ```
     (always a higher number than the last release - see section G).
4. Wait 1-2 minutes. The window shows:
   ```
   [1/3] Preparing the build environment ...
   [2/3] Bundling the app (Python + Lien Import) ...
   [3/3] Building the installer ...
   DONE:  dist\LienImport-Setup-1.0.1.exe
   ```
5. The installer is in:
   ```
   D:\clients\MT\AmericanTax\lien-import\dist\LienImport-Setup-<version>.exe
   ```

---

## C. Test and deliver (developer, every release)

1. **Install it on your own PC**: double-click the new Setup.exe.
   If Windows says *"Windows protected your PC"*, click **More info -> Run anyway**
   (the installer is not code-signed).
2. Check:
   - [ ] It installs without asking for an administrator password
   - [ ] The **Lien Import** window opens at the end
   - [ ] A **Lien Import** icon is on the desktop and opens the window
   - [ ] **Test Connection** works with your database details
   - [ ] **Check All (Preview)** works on a sample file in the inbox
   - [ ] For an update: your saved settings and files are still there
3. **Keep a copy** of every Setup.exe you send (e.g. a `releases` folder), so you can
   go back to an older version if needed.
4. **Write one line** in `CHANGELOG.md` saying what changed, e.g.
   `1.0.1 - 2026-10-25 - fixed date format for XYZ files`.
5. **Send the Setup.exe** to the user (email, Google Drive, USB stick, shared folder).
   Tell them about the *More info -> Run anyway* step.

---

## D. Install on the user's PC (end user)

No Python, no administrator rights, nothing else needed.

1. Double-click **`LienImport-Setup-<version>.exe`**.
2. If Windows says *"Windows protected your PC"*: click **More info**, then **Run anyway**.
3. Leave **"Put a Lien Import icon on the desktop"** ticked and click **Next / Install**.
4. Click **Finish**. The **Lien Import** window opens.
5. From now on, open it with the **Lien Import icon on the desktop** (or from the Start menu).

Where things are on the user's PC:

| What | Where |
|---|---|
| The program | `C:\Users\<name>\AppData\Local\Programs\Lien Import` (never needs opening) |
| **Your files** | **`Documents\Lien Import`** |
| - drop files to import here | `Documents\Lien Import\lien-data\inbox` |
| - imported files are moved to | `Documents\Lien Import\lien-data\processed` |
| - problem files are moved to | `Documents\Lien Import\lien-data\failed` (with a `.reason.txt`) |
| - reports of every run | `Documents\Lien Import\output` |
| - saved database settings | `Documents\Lien Import\config.json` |

---

## E. First-time connection (end user, once)

In box **1) Connect to the database**:

1. If you were given one line like `mysql://user:password@server:3306/zm_dba`,
   paste it into **Connection string** and click **Fill fields below**.
   Otherwise type **Host**, **Username** and **Password**. Leave **Port** at `3306`
   and **Database / schema** at `zm_dba` unless told otherwise.
2. Click **Test Connection**. You should see
   **"Connected - MySQL ... - table 'liens' found"**.
   If not, the message says what is wrong - send a screenshot to the developer.
3. Click **Save**. You will not need to type it again.

---

## F. Daily use (end user)

1. Open **Lien Import** from the desktop icon.
2. Click **Open Inbox Folder** and **copy** the new files into it: whole folders, CSV
   files or ZIP files, mixed together. You do not need to sort them.
3. *(Only if you were told to)* tick **Allow duplicates**. Normally leave it **off** -
   then a lien that appears in several files is added only once.
4. Click **Check All (Preview)**. Nothing is written yet. Wait until the bottom line
   says **"Check done - ... would be inserted"**, then read the **Results** box:
   - **previewed** - ready to import
   - **already_imported** - this exact file was imported before, it will be skipped
   - **unrecognised** - the tool doesn't know this file; it will NOT be imported
5. If the numbers look right, click **Import All**, then **Yes**.
   Large files take several minutes - **do not close the window**.
6. When the bottom line says **"Import All complete"**, click **Verify Counts**.
7. Your inbox is empty again: finished files are in `processed`, problem files in
   `failed` (open the `.reason.txt` next to each to see why).

One file at a time instead: use box **3)** (choose the file and its source) and box
**4)** (**Check File**, then **Import**).

Safe to know:
- The same file is never imported twice, even renamed.
- If the power goes off during an import, open the app and run **Check All** +
  **Import All** again - it continues without creating duplicates.
- A file in `failed`: fix the problem (or ask the developer), copy it back into
  `inbox`, run again.

---

## G. Release a new version after a code change (developer)

```
 change code -> run tests -> build with a NEW version -> test install over the old one
             -> keep a copy + changelog line -> send the new Setup.exe
```

1. Make the change in `D:\clients\MT\AmericanTax\lien-import`.
2. `python -m pytest` - everything must pass.
3. Pick the next version number:

   | Change | Example |
   |---|---|
   | Small fix | 1.0.0 -> **1.0.1** |
   | New feature | 1.0.1 -> **1.1.0** |
   | Big change | 1.1.0 -> **2.0.0** |

4. `build-installer.bat 1.0.1`
5. Test as in section C - **install it over the old version** on your PC and check that
   the settings and files in `Documents\Lien Import` are still there.
6. Save the Setup.exe in your releases folder and add a line to `CHANGELOG.md`.
7. Send it to the user. They **just double-click it and click Install** - no uninstall
   needed. If the app is open, the installer asks to close it. Their settings, inbox,
   processed files and reports are kept.

**Going back to an older version:** the user uninstalls (Settings -> Apps ->
Lien Import -> Uninstall; their `Documents\Lien Import` folder is kept), then installs
the older Setup.exe.

**Careful with data-rule changes after the real import.** Changes to how names,
dates, Federal/State or duplicates are decided can change the `lien_id` of rows that
are already in the database, so a later import could add those liens a second time.
Changes to the window, messages, reports or speed are always safe. For rule changes,
check the impact with the developer before releasing.

---

## H. Troubleshooting

| Problem | Fix |
|---|---|
| Build: `Inno Setup 6 was not found` | Do section A step 2, then run the build again |
| Build: `'python' is not recognized` | Install Python on the **build PC** (section A step 1) |
| Build: `Could not install` / pip error | Check the internet connection (company proxy? ask IT) |
| Install: "Windows protected your PC" | **More info -> Run anyway** (normal for an unsigned installer) |
| Install: antivirus blocks it | Ask IT to allow `LienImport-Setup-*.exe` and the `Lien Import` program folder |
| App: **Test Connection** fails | Read the message: wrong password / server unreachable / wrong database name. Check with the DBA |
| App: **Import All** stays grey | Click **Check All (Preview)** first; if files were added since, check again |
| App: a file is **unrecognised** | Its columns don't match any known layout - send the file's first lines to the developer |
| App: the window doesn't open | Restart the PC and try again; if it still fails, reinstall the same Setup.exe |

When asking for help, send:
1. a screenshot of the window,
2. the newest sub-folder of `Documents\Lien Import\output` (zipped - it contains `run.log`),
3. the version number of the Setup.exe that was installed.

---

## I. Uninstall

Windows **Settings -> Apps -> Installed apps -> Lien Import -> Uninstall**.
This removes the program and the icons. The `Documents\Lien Import` folder (settings,
files, reports) is **kept** - delete it by hand only if you really want to remove all data.
