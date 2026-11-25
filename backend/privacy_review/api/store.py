"""Protected storage: original documents on disk, audit rows and sanitized results in SQLite.

Layout under ``settings.protected_store_dir`` (git-ignored):

    <batch_id>/<doc_id>.<ext>     originals, mode 0600, directory 0700
    api.sqlite                    audit + results, mode 0600

The audit table holds ids, statuses and counts only - never values, never filenames.
The results table holds `BatchResult` JSON, which is already sanitized.
"""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from privacy_review.schemas import BatchResult

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SAFE_EXT = re.compile(r"^[a-z0-9]{1,8}$")
FILE_MODE = 0o600
DIR_MODE = 0o700

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    batch_id      TEXT    NOT NULL,
    doc_id        TEXT    NOT NULL,
    status        TEXT    NOT NULL,
    entity_count  INTEGER NOT NULL,
    finding_count INTEGER NOT NULL,
    created_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_batch ON audit(batch_id);
CREATE TABLE IF NOT EXISTS results (
    batch_id TEXT PRIMARY KEY,
    json     TEXT NOT NULL
);
"""


class ProtectedStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        _mkdir_private(self.root)
        self.db_path = self.root / "api.sqlite"
        if not self.db_path.exists():
            _create_private(self.db_path)
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)

    # ---------------------------------------------------------------- originals

    def save_original(self, batch_id: str, doc_id: str, ext: str, data: bytes) -> Path:
        _check_id(batch_id, "batch_id")
        _check_id(doc_id, "doc_id")
        if not SAFE_EXT.fullmatch(ext):
            raise ValueError("unsafe file extension")
        batch_dir = self.root / batch_id
        _mkdir_private(batch_dir)
        path = batch_dir / f"{doc_id}.{ext}"
        if path.resolve().parent != batch_dir.resolve():
            raise ValueError("path escapes the protected store")
        _create_private(path, data)
        return path

    # ---------------------------------------------------------------- results

    def record_batch(self, result: BatchResult) -> None:
        now = _now()
        adversarial = result.adversarial
        rows = []
        for doc in result.documents:
            findings = len(doc.verification.findings) if doc.verification else 0
            if adversarial is not None:
                findings += len(adversarial.for_doc(doc.doc_id))
            rows.append(
                (result.batch_id, doc.doc_id, doc.release.status.value,
                 len(doc.entities), findings, now)
            )
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO results (batch_id, json) VALUES (?, ?)",
                (result.batch_id, result.model_dump_json()),
            )
            conn.executemany(
                "INSERT INTO audit (batch_id, doc_id, status, entity_count, finding_count, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )

    def record_failure(self, batch_id: str, doc_ids: list[str]) -> None:
        now = _now()
        with closing(self._connect()) as conn, conn:
            conn.executemany(
                "INSERT INTO audit (batch_id, doc_id, status, entity_count, finding_count, created_at)"
                " VALUES (?, ?, 'error', 0, 0, ?)",
                [(batch_id, d, now) for d in doc_ids],
            )

    def get_result(self, batch_id: str) -> BatchResult | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT json FROM results WHERE batch_id = ?", (batch_id,)
            ).fetchone()
        return BatchResult.model_validate_json(row[0]) if row else None

    def audit_rows(self, batch_id: str | None = None) -> list[dict]:
        sql = "SELECT batch_id, doc_id, status, entity_count, finding_count, created_at FROM audit"
        args: tuple = ()
        if batch_id is not None:
            sql += " WHERE batch_id = ?"
            args = (batch_id,)
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, args)]

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)


def _check_id(value: str, name: str) -> None:
    if not SAFE_ID.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"unsafe {name}")


def _mkdir_private(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    try:
        os.chmod(path, DIR_MODE)
    except OSError:
        pass


def _create_private(path: Path, data: bytes = b"") -> None:
    """Create a new file readable only by the owner. Refuses to overwrite."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, FILE_MODE)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.chmod(path, FILE_MODE)   # in case the umask was looser than expected


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
