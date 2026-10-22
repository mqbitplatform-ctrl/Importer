"""Start-up for the INSTALLED Lien Import app (built by build-installer.bat).

The program itself lives in the install folder, which the user should never
need to open. The user's own files live in  Documents\\Lien Import :

    config.json                  database settings (written by the Save button)
    lien-data\\inbox             drop files here
    lien-data\\processed|failed  where finished / problem files are moved
    output\\                     reports of every run

That folder becomes the working directory, so the app's normal relative
defaults (config.json, ./output, ./lien-data/...) resolve there - no other
code needs to know it is running installed. Set LIEN_IMPORT_HOME to use a
different folder.
"""

from __future__ import annotations

import ctypes
import multiprocessing
import os
import sys
from pathlib import Path

_CSIDL_PERSONAL = 5  # the user's real "Documents" folder (follows OneDrive redirection)


def _documents() -> Path:
    try:
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, _CSIDL_PERSONAL, None, 0, buf) == 0 \
                and buf.value:
            return Path(buf.value)
    except (AttributeError, OSError):  # not Windows
        pass
    return Path.home() / "Documents"


def data_dir() -> Path:
    override = os.environ.get("LIEN_IMPORT_HOME")
    return Path(override) if override else _documents() / "Lien Import"


def main() -> int:
    home = data_dir()
    for sub in ("lien-data/inbox", "lien-data/processed", "lien-data/failed", "output"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    os.chdir(home)

    from lien_import.gui import main as gui_main

    return gui_main()


if __name__ == "__main__":
    multiprocessing.freeze_support()  # lets import.workers > 1 run inside the .exe
    sys.exit(main())
