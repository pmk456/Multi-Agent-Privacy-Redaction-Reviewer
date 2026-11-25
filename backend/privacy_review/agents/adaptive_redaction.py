"""Agent 3 - Adaptive Redaction.

Carries out Agent 2's decisions with deterministic Python - never an LLM. The same input
always produces the same output, which is what lets Agent 4 tell a redaction bug apart from
noise. It always re-renders from the ORIGINAL text, so remediation rounds never compound
edits on already-redacted text.

  in : original documents, entities, decisions
  out: RedactedDocuments with segment maps back to the original
"""

from __future__ import annotations

from privacy_review.config import Settings, get_settings
from privacy_review.knowledge_base import PolicyEngine
from privacy_review.redaction import PseudonymRegistry, apply_redactions
from privacy_review.schemas.documents import Document
from privacy_review.schemas.entities import DetectedEntity
from privacy_review.schemas.policy import RedactionDecision
from privacy_review.schemas.redaction import RedactedDocument


class AdaptiveRedactionAgent:
    name = "adaptive_redaction"

    def __init__(self, policy: PolicyEngine, settings: Settings | None = None, registry: PseudonymRegistry | None = None):
        self.policy = policy
        self.settings = settings or get_settings()
        tr = policy.transformation
        store = None
        if self.settings.pseudonym_persist and self.settings.pseudonym_secret \
                and self.settings.pseudonym_secret.get_secret_value() not in ("", "change-me"):
            store = self.settings.protected_store_dir / "pseudonyms.sqlite"    # HMAC digests only, mode 0600
        self.registry = registry or PseudonymRegistry(self.settings.pseudonym_key(), tr.pseudonym_prefixes,
                                                      tr.pseudonym_format, store_path=store)

    def run(self, documents: list[Document], entities: list[DetectedEntity], decisions: list[RedactionDecision],
            batch_id: str, revision: int = 0) -> list[RedactedDocument]:
        by_id = {d.entity_id: d for d in decisions}
        out = []
        for doc in documents:
            ents = [e for e in entities if e.doc_id == doc.doc_id]
            out.append(apply_redactions(doc.doc_id, doc.text, ents, by_id, self.policy, self.registry, batch_id, revision))
        return out
