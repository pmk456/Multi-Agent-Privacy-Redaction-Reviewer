"""Consistent pseudonyms, with the mapping kept in the backend only.

What is stored: HMAC-SHA256(secret, scope | type | identity) -> pseudonym. No plaintext value
is ever persisted - consistency needs only the keyed digest, and without the secret the
digest cannot be reversed by guessing names. The scope decides linkability:

  batch    - the same person is PERSON_01 in every document of the batch (readable, linkable)
  document - a fresh numbering per document (unlinkable)
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from pathlib import Path

from privacy_review.schemas.entities import EntityType
from privacy_review.schemas.policy import PseudonymScope


class PseudonymRegistry:
    def __init__(self, key: bytes, prefixes: dict[str, str] | None = None, fmt: str = "{prefix}_{index:02d}",
                 store_path: Path | None = None):
        self._key = key
        self.prefixes = prefixes or {}
        self.fmt = fmt
        self._map: dict[str, str] = {}
        self._counters: dict[tuple[str, str], int] = {}
        self._db = None
        if store_path is not None:
            store_path.parent.mkdir(parents=True, exist_ok=True)
            new = not store_path.exists()
            self._db = sqlite3.connect(str(store_path))
            if new:
                os.chmod(store_path, 0o600)
            self._db.execute("CREATE TABLE IF NOT EXISTS pseudonyms (digest TEXT PRIMARY KEY, scope TEXT NOT NULL, "
                             "entity_type TEXT NOT NULL, pseudonym TEXT NOT NULL)")
            for d, s, t, p in self._db.execute("SELECT digest, scope, entity_type, pseudonym FROM pseudonyms"):
                self._map[d] = p
                idx = int(p.rsplit("_", 1)[-1]) if p.rsplit("_", 1)[-1].isdigit() else 0
                self._counters[(s, t)] = max(self._counters.get((s, t), 0), idx)

    def __repr__(self) -> str:
        return f"PseudonymRegistry(entries={len(self._map)})"

    def _digest(self, scope_key: str, et: EntityType, identity: str) -> str:
        msg = f"{scope_key}|{et.value}|{identity}".encode()
        return hmac.new(self._key, msg, hashlib.sha256).hexdigest()

    def pseudonym(self, et: EntityType, identity: str, scope: PseudonymScope, batch_id: str, doc_id: str) -> str:
        """`identity` is the cluster id (preferred) or a normalised value - whatever makes two
        mentions 'the same entity'. It is hashed, never stored."""
        scope_key = batch_id if scope == PseudonymScope.BATCH else f"{batch_id}/{doc_id}"
        d = self._digest(scope_key, et, identity)
        if d not in self._map:
            k = (scope_key, et.value)
            self._counters[k] = self._counters.get(k, 0) + 1
            p = self.fmt.format(prefix=self.prefixes.get(et.value, et.value), index=self._counters[k])
            self._map[d] = p
            if self._db is not None:
                self._db.execute("INSERT OR IGNORE INTO pseudonyms VALUES (?,?,?,?)", (d, scope_key, et.value, p))
                self._db.commit()
        return self._map[d]
