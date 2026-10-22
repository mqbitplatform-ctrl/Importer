"""Parse a database connection string into its parts.

Pure logic, no UI and no network - used by the GUI's "Connect" panel so a
non-technical user can paste one string (host, port, user, password - often
supplied as a single line by a hosting control panel) instead of typing each
field. The database/schema name can come from the same string or be entered
separately; the GUI always shows both and lets either win.

Accepted shapes (``mysql://`` is optional and assumed if missing):

    mysql://user:password@host:3306/database
    user:password@host:3306/database
    host:3306/database
    host
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urlsplit


@dataclass
class ParsedConnection:
    host: Optional[str] = None
    port: Optional[int] = None
    user: Optional[str] = None
    password: Optional[str] = None
    database: Optional[str] = None

    def is_empty(self) -> bool:
        return not any((self.host, self.port, self.user, self.password, self.database))


def parse_connection_string(raw: Optional[str]) -> ParsedConnection:
    """Best-effort parse. Never raises - an unparseable string just yields
    an empty result (the caller falls back to whatever fields are already
    filled in)."""
    s = (raw or "").strip()
    if not s:
        return ParsedConnection()
    if "://" not in s:
        s = "mysql://" + s
    try:
        parts = urlsplit(s)
    except ValueError:
        return ParsedConnection()

    host = parts.hostname or None
    try:
        port = parts.port
    except ValueError:
        port = None
    user = unquote(parts.username) if parts.username else None
    password = unquote(parts.password) if parts.password else None
    database = unquote(parts.path.lstrip("/")) if parts.path.lstrip("/") else None

    return ParsedConnection(host=host, port=port, user=user, password=password, database=database)
