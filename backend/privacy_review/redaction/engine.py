"""Apply redaction decisions to one document. Deterministic: same input, same output."""

from __future__ import annotations

from privacy_review.knowledge_base import PolicyEngine
from privacy_review.redaction.generalization import generalize
from privacy_review.redaction.masking import mask, suppress
from privacy_review.redaction.pseudonymization import PseudonymRegistry
from privacy_review.schemas.entities import DetectedEntity, Span
from privacy_review.schemas.policy import RedactionDecision, Strategy
from privacy_review.schemas.redaction import AppliedRedaction, RedactedDocument, Segment


def replacement_for(e: DetectedEntity, d: RedactionDecision, policy: PolicyEngine,
                    registry: PseudonymRegistry, batch_id: str) -> tuple[Strategy, str | None]:
    """(strategy actually applied, replacement text). None replacement means keep as is."""
    tr = policy.transformation
    s = d.strategy
    if s == Strategy.KEEP:
        return s, None
    if s == Strategy.GENERALIZE:
        out = generalize(e.raw(), e.entity_type, d.generalization_level, tr.generalization, policy.reference)
        if out is not None:
            return s, out
        s = Strategy.MASK                    # cannot generalise safely -> mask, never leave it
    if s == Strategy.PSEUDONYMIZE:
        return s, registry.pseudonym(e.entity_type, e.cluster_id or e.raw().strip().lower(), d.scope, batch_id, e.doc_id)
    if s == Strategy.SUPPRESS:
        return s, suppress(tr.suppress_token)
    return Strategy.MASK, mask(e.entity_type, tr.mask_format)


def _fit_article(before: str, rep: str) -> str:
    """'is a' + 'a professional' -> 'is a professional'."""
    import re
    if re.search(r"\b(?:a|an|the)\s+$", before, re.I):
        return re.sub(r"^(?:a|an|the)\s+", "", rep, flags=re.I) or rep
    return rep


def apply_redactions(doc_id: str, text: str, entities: list[DetectedEntity], decisions: dict[str, RedactionDecision],
                     policy: PolicyEngine, registry: PseudonymRegistry, batch_id: str, revision: int) -> RedactedDocument:
    # Overlaps should not reach here (Agent 1 resolves them) - but if they do, merge into
    # one span and apply the stronger of the two decisions rather than leaking the gap.
    ents = sorted((e for e in entities if e.entity_id in decisions), key=lambda e: (e.span.start, -e.span.length))
    merged: list[tuple[DetectedEntity, RedactionDecision]] = []
    for e in ents:
        d = decisions[e.entity_id]
        if merged and e.span.start < merged[-1][0].span.end:
            pe, pd = merged[-1]
            span = Span(start=pe.span.start, end=max(pe.span.end, e.span.end))
            stronger = pd if pd.strategy.strength >= d.strategy.strength else d
            base = pe if stronger is pd else e
            merged[-1] = (base.model_copy(update={"span": span}), stronger)
            continue
        merged.append((e, d))

    out, segments, applied = [], [], []
    pos = opos = 0
    for e, d in merged:
        if e.span.start > pos:
            chunk = text[pos:e.span.start]
            segments.append(Segment(out_start=opos, out_end=opos + len(chunk), orig_start=pos, orig_end=e.span.start, replaced=False))
            out.append(chunk)
            opos += len(chunk)
        strategy, rep = replacement_for(e, d, policy, registry, batch_id)
        if rep and strategy == Strategy.GENERALIZE:
            rep = _fit_article(text[:e.span.start], rep)
        piece = text[e.span.start:e.span.end] if rep is None else rep
        segments.append(Segment(out_start=opos, out_end=opos + len(piece), orig_start=e.span.start,
                                orig_end=e.span.end, replaced=rep is not None))
        if rep is not None:
            applied.append(AppliedRedaction(entity_id=e.entity_id, entity_type=e.entity_type, strategy=strategy,
                                            original_span=e.span, replacement=rep,
                                            output_span=Span(start=opos, end=opos + len(rep)) if rep else None))
        out.append(piece)
        opos += len(piece)
        pos = e.span.end
    if pos < len(text):
        segments.append(Segment(out_start=opos, out_end=opos + len(text) - pos, orig_start=pos, orig_end=len(text), replaced=False))
        out.append(text[pos:])
    return RedactedDocument(doc_id=doc_id, text="".join(out), redactions=applied, segments=segments, revision=revision)
