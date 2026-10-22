"""Iterate source rows from a CSV file, a directory of CSVs, or a ZIP archive.

Yields ``SourceRow(file, row_num, data)`` where *data* is the raw
``csv.DictReader`` dict (original header names, string values).

Streaming: files and ZIP members are read incrementally, never loaded whole.
Encoding is detected from a 64 KiB probe (utf-8-sig -> cp1252 -> latin-1) and
then the rest of the stream is decoded on the fly.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator

log = logging.getLogger("lien_import.sourcereader")

_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")
_PROBE = 64 * 1024
csv.field_size_limit(16 * 1024 * 1024)  # long free-text Note blobs


@dataclass
class SourceRow:
    file: str
    row_num: int  # 1-based data row number (header excluded)
    data: dict[str, str]


def _detect_encoding(probe: bytes, label: str) -> str:
    for enc in _ENCODINGS:
        try:
            probe.decode(enc)
            if enc != _ENCODINGS[0]:
                log.warning("decoding %s as %s (not utf-8)", label, enc)
            return enc
        except UnicodeDecodeError:
            continue
    log.warning("decoding %s as latin-1 (lossy)", label)
    return "latin-1"


class _Prepended(io.RawIOBase):
    """A read-only binary stream: *head* bytes first, then *rest* (an open
    binary stream). Lets us sniff a non-seekable ZIP member without buffering
    the whole thing."""

    def __init__(self, head: bytes, rest: BinaryIO):
        self._head = memoryview(head)
        self._pos = 0
        self._rest = rest

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        if self._pos < len(self._head):
            n = min(len(b), len(self._head) - self._pos)
            b[:n] = self._head[self._pos : self._pos + n]
            self._pos += n
            return n
        return self._rest.readinto(b) if hasattr(self._rest, "readinto") else _fallback_read(self._rest, b)

    def close(self) -> None:
        try:
            self._rest.close()
        finally:
            super().close()


def _fallback_read(stream: BinaryIO, b) -> int:  # pragma: no cover - zip streams have readinto
    chunk = stream.read(len(b))
    if not chunk:
        return 0
    b[: len(chunk)] = chunk
    return len(chunk)


def _iter_csv(text_stream: io.TextIOBase, label: str) -> Iterator[SourceRow]:
    reader = csv.DictReader(text_stream)
    if reader.fieldnames is None:
        log.warning("no header row in %s - skipped", label)
        return
    for i, row in enumerate(reader, start=1):
        row.pop(None, None)  # type: ignore[arg-type]  # overflow columns
        # DictReader yields a fresh dict per row; downstream tolerates None values
        yield SourceRow(file=label, row_num=i, data=row)


def _stream_file(path: Path) -> Iterator[SourceRow]:
    with path.open("rb") as fh:
        enc = _detect_encoding(fh.read(_PROBE), path.name)
    with path.open("r", encoding=enc, newline="") as fh:
        yield from _iter_csv(fh, path.name)


def _stream_zip_member(zf: zipfile.ZipFile, member: str, label: str) -> Iterator[SourceRow]:
    # ZIP member streams are single-pass / not seekable: read the probe from the
    # one stream, then keep reading from that same (now advanced) stream.
    raw = zf.open(member, "r")
    head = raw.read(_PROBE)
    enc = _detect_encoding(head, label)
    text = io.TextIOWrapper(io.BufferedReader(_Prepended(head, raw)), encoding=enc, newline="")
    try:
        yield from _iter_csv(text, label)
    finally:
        text.close()


def iter_source_rows(input_path) -> Iterator[SourceRow]:
    """*input_path*: a CSV, a ZIP, a directory - or a list/tuple of those
    (read one after another, e.g. every file of one source in an inbox)."""
    if isinstance(input_path, (list, tuple)):
        for one in input_path:
            yield from iter_source_rows(one)
        return
    p = Path(input_path)
    if not p.exists():
        raise FileNotFoundError(f"Input path not found: {p}")

    if p.is_dir():
        files = sorted(p.rglob("*.csv"))
        if not files:
            log.warning("no *.csv files under %s", p)
        for f in files:
            yield from _stream_file(f)
        return

    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as zf:
            members = sorted(
                m for m in zf.namelist()
                if m.lower().endswith(".csv") and not m.endswith("/")
            )
            if not members:
                log.warning("no *.csv members in %s", p.name)
            for m in members:
                yield from _stream_zip_member(zf, m, f"{p.name}!{m}")
        return

    if p.suffix.lower() in {".csv", ".txt"}:
        yield from _stream_file(p)
        return

    raise ValueError(f"Unsupported input type: {p.suffix} ({p})")
