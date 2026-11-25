"""The protected document store.

Original and redacted documents live here, on the backend filesystem, keyed by
document id. Nothing in this module is reachable from an API route - routes return
redacted text from the workflow result, not files from this store.

Owner: Diddekunta Jagan Mohan Reddy
"""

from __future__ import annotations

from pathlib import Path

from app.config import settings


def store_root() -> Path:
    root = Path(settings.protected_store_path)
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_original(document_id: str, content: bytes) -> Path:
    """Write the uploaded document. Never served back out."""
    raise NotImplementedError("Protected store - planned for Review 2")


def save_redacted(document_id: str, revision: int, text: str) -> Path:
    raise NotImplementedError("Protected store - planned for Review 2")


def load_original(document_id: str) -> bytes:
    """Backend use only. Do not call this from a route."""
    raise NotImplementedError("Protected store - planned for Review 2")
