"""SQLite metadata, decisions and audit records.

Holds what happened - entity ids, categories, risk levels, strategies, findings,
timestamps. It does not hold raw identifier values. If you find yourself adding a
`value` column, stop and ask why.

Owner: Diddekunta Jagan Mohan Reddy
"""

from __future__ import annotations

from app.config import settings


def init_db() -> None:
    """Create tables if they do not exist."""
    raise NotImplementedError("Database layer - planned for Review 2")


def record_decision(batch_id: str, document_id: str, entity_id: str, strategy: str) -> None:
    raise NotImplementedError("Audit log - planned for Review 2")
