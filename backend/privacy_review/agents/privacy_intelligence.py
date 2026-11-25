"""Agent 1 - Privacy Intelligence.

Everything downstream depends on what this agent finds, so it is deliberately the most
conservative: when detection and a supplied annotation disagree, it keeps the union of the
two rather than picking one, and an annotation it cannot confirm is kept (flagged), not
dropped.

  in : documents (raw, or with supplied annotations)
  out: IntelligenceResult - entities, annotation validation reports, cross-document
       clusters and an entity relationship graph (NetworkX)
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from itertools import combinations
from typing import Optional

import networkx as nx
from pydantic import BaseModel, Field, SecretStr

from privacy_review.config import Settings, get_settings
from privacy_review.datasets.label_maps import AI4PRIVACY, PIIMB_PRESIDIO_STYLE, PIIMB_SNAKE
from privacy_review.detection import EntityExtractor
from privacy_review.detection.presidio_detector import PRESIDIO_TO_CANONICAL
from privacy_review.detection.spacy_processor import SpacyProcessor
from privacy_review.knowledge_base import PolicyEngine
from privacy_review.llm import Reasoner
from privacy_review.schemas.documents import Annotation, Document
from privacy_review.schemas.entities import (
    AnnotationStatus, DetectedEntity, DetectionSource, EntityCluster, EntityLink, EntityType, Span,
)

log = logging.getLogger(__name__)

CONFIRM_IOU = 0.8
UNCONFIRMED_CONFIDENCE = 0.5

# Types detectors routinely confuse with each other. A mismatch inside a group is a span
# question, not a type disagreement.
_COMPATIBLE = [
    {EntityType.DATE, EntityType.DATE_OF_BIRTH},
    {EntityType.LOCATION, EntityType.STREET_ADDRESS, EntityType.POSTAL_CODE},
    {EntityType.FINANCIAL_ACCOUNT, EntityType.GOVERNMENT_ID, EntityType.RECORD_IDENTIFIER,
     EntityType.CREDENTIAL, EntityType.DEVICE_IDENTIFIER},
    {EntityType.ONLINE_IDENTIFIER, EntityType.URL},
]

_HONORIFICS = {"mr", "mrs", "ms", "miss", "mx", "dr", "prof", "sir", "madam", "shri", "smt"}


def splits_a_word(text: str, span: Span) -> bool:
    """True if a boundary falls inside a word - a strong sign the annotation was misplaced."""
    left = span.start > 0 and text[span.start - 1].isalnum() and text[span.start].isalnum()
    right = span.end < len(text) and text[span.end - 1].isalnum() and text[span.end].isalnum()
    return left or right


def expand_to_words(text: str, span: Span) -> Span:
    s, e = span.start, span.end
    while s > 0 and text[s - 1].isalnum():
        s -= 1
    while e < len(text) and text[e].isalnum():
        e += 1
    return Span(start=s, end=e)


def compatible(a: EntityType, b: EntityType) -> bool:
    return a == b or any(a in g and b in g for g in _COMPATIBLE)


def map_annotation_label(label: str) -> EntityType:
    """Accept canonical, Presidio, ai4privacy and PIIMB labels. Unknown -> UNKNOWN (fails closed)."""
    if label in EntityType.__members__:
        return EntityType(label)
    for table in (PRESIDIO_TO_CANONICAL, AI4PRIVACY, PIIMB_PRESIDIO_STYLE, PIIMB_SNAKE):
        if label in table and table[label] is not None:
            return table[label]
    return EntityType.UNKNOWN


class AnnotationReport(BaseModel):
    doc_id: str
    annotation_index: Optional[int]          # None for NOT_ANNOTATED findings
    supplied_label: Optional[str]
    mapped_type: Optional[EntityType]
    status: AnnotationStatus
    entity_id: Optional[str] = None
    detector_type: Optional[EntityType] = None
    iou: Optional[float] = None
    note: str = ""


class LLMDetection(BaseModel):
    """Structured output for the optional LLM detection pass."""

    class Item(BaseModel):
        text: str = Field(description="Exact substring of the document, copied verbatim")
        entity_type: EntityType
        reason: str = Field(description="Why this is identifying. Do not repeat the value.")

    items: list[Item] = Field(default_factory=list)


class IntelligenceResult(BaseModel):
    entities: list[DetectedEntity]
    annotation_reports: list[AnnotationReport] = Field(default_factory=list)
    clusters: list[EntityCluster] = Field(default_factory=list)
    links: list[EntityLink] = Field(default_factory=list)
    sentence_starts: dict[str, list[int]] = Field(default_factory=dict)
    llm_used: bool = False
    warnings: list[str] = Field(default_factory=list)

    def for_doc(self, doc_id: str) -> list[DetectedEntity]:
        return [e for e in self.entities if e.doc_id == doc_id]


class PrivacyIntelligenceAgent:
    name = "privacy_intelligence"

    def __init__(self, policy: PolicyEngine, extractor: EntityExtractor | None = None,
                 reasoner: Reasoner | None = None, settings: Settings | None = None):
        self.policy = policy
        self.settings = settings or get_settings()
        self.extractor = extractor or EntityExtractor(policy, self.settings)
        self.reasoner = reasoner

    # ================================================================== run
    def run(self, documents: list[Document]) -> IntelligenceResult:
        all_entities: list[DetectedEntity] = []
        reports: list[AnnotationReport] = []
        starts: dict[str, list[int]] = {}
        warnings: list[str] = []
        llm_used = False

        for doc in documents:
            det = self.extractor.detect(doc.doc_id, doc.text)
            starts[doc.doc_id] = det.sentence_starts
            detected = det.entities

            if self._llm_detection_enabled():
                extra = self._llm_detect(doc, detected)
                if extra is not None:
                    llm_used = True
                    detected = self._merge_llm(doc, detected, extra, det.sentence_starts)

            if doc.is_annotated:
                ents, reps = self.validate_annotations(doc, detected, det.sentence_starts)
                reports += reps
                bad = sum(r.status == AnnotationStatus.INVALID for r in reps)
                if bad:
                    warnings.append(f"{doc.doc_id}: {bad} supplied annotation(s) rejected as invalid")
            else:
                ents = detected
            all_entities += ents

        clusters = self.cluster(all_entities)
        links = self.link(all_entities)
        return IntelligenceResult(entities=all_entities, annotation_reports=reports, clusters=clusters,
                                  links=links, sentence_starts=starts, llm_used=llm_used, warnings=warnings)

    # ================================================================== annotations
    def validate_annotations(self, doc: Document, detected: list[DetectedEntity],
                             starts: list[int]) -> tuple[list[DetectedEntity], list[AnnotationReport]]:
        text = doc.text
        out: list[DetectedEntity] = []
        reports: list[AnnotationReport] = []
        used_detected: set[str] = set()

        for idx, a in enumerate(doc.annotations or []):
            mapped = map_annotation_label(a.label)
            if not (0 <= a.start < a.end <= len(text)) or not text[a.start:a.end].strip():
                reports.append(AnnotationReport(doc_id=doc.doc_id, annotation_index=idx, supplied_label=a.label,
                                                mapped_type=mapped, status=AnnotationStatus.INVALID,
                                                note="span out of bounds or empty - rejected"))
                continue
            aspan = Span(start=a.start, end=a.end)
            broken_boundary = splits_a_word(text, aspan)
            if broken_boundary:
                aspan = expand_to_words(text, aspan)              # repair before comparing
            overlapping = [d for d in detected if d.span.overlaps(aspan)]
            same = [d for d in overlapping if compatible(d.entity_type, mapped)]

            if same:
                best = max(same, key=lambda d: d.span.iou(aspan))
                iou = best.span.iou(aspan)
                # Containment on word boundaries is agreement about the entity ("Analyst" inside
                # "Account Analyst"); a boundary through the middle of a word is not.
                agrees = iou >= CONFIRM_IOU or best.span.contains(aspan) or aspan.contains(best.span)
                status = AnnotationStatus.CONFIRMED if agrees and not broken_boundary else AnnotationStatus.SPAN_MISMATCH
                for d in same:
                    used_detected.add(d.entity_id)
                span = self._union([aspan, *[d.span for d in same]])
                ent = self._entity(doc, span, mapped, max(d.confidence for d in same), starts,
                                   f"{doc.doc_id}:a{idx}", [DetectionSource.ANNOTATION, *best.sources], a.label, status)
                reports.append(AnnotationReport(doc_id=doc.doc_id, annotation_index=idx, supplied_label=a.label,
                                                mapped_type=mapped, status=status, entity_id=ent.entity_id,
                                                detector_type=best.entity_type, iou=round(iou, 3),
                                                note="" if status == AnnotationStatus.CONFIRMED
                                                else "boundaries differ - kept the union of both spans"))
            elif overlapping:
                best = max(overlapping, key=lambda d: d.span.iou(aspan))
                for d in overlapping:
                    used_detected.add(d.entity_id)
                # Keep whichever reading the policy treats as more sensitive.
                keep = max([mapped, best.entity_type], key=lambda t: self.policy.sensitivity(t).rank)
                span = self._union([aspan, best.span])
                ent = self._entity(doc, span, keep, best.confidence, starts, f"{doc.doc_id}:a{idx}",
                                   [DetectionSource.ANNOTATION, *best.sources], a.label, AnnotationStatus.TYPE_MISMATCH)
                reports.append(AnnotationReport(doc_id=doc.doc_id, annotation_index=idx, supplied_label=a.label,
                                                mapped_type=mapped, status=AnnotationStatus.TYPE_MISMATCH,
                                                entity_id=ent.entity_id, detector_type=best.entity_type,
                                                iou=round(best.span.iou(aspan), 3),
                                                note=f"kept the more sensitive type ({keep.value})"))
            else:
                status = AnnotationStatus.SPAN_MISMATCH if broken_boundary else AnnotationStatus.UNCONFIRMED
                ent = self._entity(doc, aspan, mapped, UNCONFIRMED_CONFIDENCE, starts, f"{doc.doc_id}:a{idx}",
                                   [DetectionSource.ANNOTATION], a.label, status)
                note = ("boundary split a word - widened to whole words" if broken_boundary
                        else "no detector support - kept and flagged")
                if mapped == EntityType.UNKNOWN:
                    note = "unrecognised label - treated as UNKNOWN (suppressed by policy)"
                reports.append(AnnotationReport(doc_id=doc.doc_id, annotation_index=idx, supplied_label=a.label,
                                                mapped_type=mapped, status=status, entity_id=ent.entity_id, note=note))
            out.append(ent)

        for d in detected:
            if d.entity_id in used_detected or any(d.span.overlaps(e.span) for e in out):
                continue
            d = d.model_copy(update={"annotation_status": AnnotationStatus.NOT_ANNOTATED})
            out.append(d)
            reports.append(AnnotationReport(doc_id=doc.doc_id, annotation_index=None, supplied_label=None,
                                            mapped_type=None, status=AnnotationStatus.NOT_ANNOTATED,
                                            entity_id=d.entity_id, detector_type=d.entity_type,
                                            note="detected but missing from the supplied annotations"))

        # union spans can overlap each other - collapse, keeping the more sensitive type
        return self._dedupe(out), reports

    def _dedupe(self, ents: list[DetectedEntity]) -> list[DetectedEntity]:
        ents = sorted(ents, key=lambda e: (e.span.start, -e.span.length))
        out: list[DetectedEntity] = []
        for e in ents:
            if out and e.span.overlaps(out[-1].span):
                prev = out[-1]
                keep = prev if self.policy.sensitivity(prev.entity_type).rank >= self.policy.sensitivity(e.entity_type).rank else e
                span = self._union([prev.span, e.span])
                out[-1] = keep.model_copy(update={"span": span})
                continue
            out.append(e)
        return out

    @staticmethod
    def _union(spans: list[Span]) -> Span:
        return Span(start=min(s.start for s in spans), end=max(s.end for s in spans))

    def _entity(self, doc, span, et, conf, starts, eid, sources, label, status) -> DetectedEntity:
        return DetectedEntity(
            entity_id=eid, doc_id=doc.doc_id, entity_type=et, span=span,
            value=SecretStr(doc.text[span.start:span.end]), confidence=round(conf, 3),
            sources=sorted(set(sources), key=lambda s: s.value),
            identifier_class=self.policy.identifier_class(et), original_label=label,
            annotation_status=status, sentence_index=SpacyProcessor.sentence_index(starts, span.start))

    # ================================================================== optional LLM pass
    def _llm_detection_enabled(self) -> bool:
        return bool(self.reasoner and self.reasoner.available and self.settings.llm_raw_text_detection)

    def _llm_detect(self, doc: Document, detected: list[DetectedEntity]) -> Optional[LLMDetection]:
        system = ("You are a privacy reviewer. Find personal information that the listed detector output "
                  "MISSED, especially indirect identifiers (job titles, employers, events, dates tied to a "
                  "person). Copy each finding verbatim from the document. Return nothing already listed.")
        found = ", ".join(sorted({e.entity_type.value for e in detected})) or "none"
        prompt = f"Already detected types: {found}\n\n<document>\n{doc.text}\n</document>"
        return self.reasoner.structured(purpose="agent1_detection", system=system, prompt=prompt,
                                        output_format=LLMDetection)

    def _merge_llm(self, doc, detected, extra: LLMDetection, starts) -> list[DetectedEntity]:
        out = list(detected)
        n = 0
        for item in extra.items:
            if not item.text.strip():
                continue
            for m in re.finditer(re.escape(item.text), doc.text):
                span = Span(start=m.start(), end=m.end())
                if any(span.overlaps(e.span) for e in out):
                    continue
                out.append(self._entity(doc, span, item.entity_type, 0.7, starts, f"{doc.doc_id}:l{n}",
                                        [DetectionSource.LLM], "llm", None))
                n += 1
        return sorted(out, key=lambda e: e.span.start)

    # ================================================================== cross-document
    @staticmethod
    def normalise(e: DetectedEntity) -> str:
        v = e.raw().strip()
        if e.entity_type == EntityType.PHONE_NUMBER:
            return re.sub(r"\D", "", v)[-10:]
        if e.entity_type == EntityType.PERSON:
            toks = [t for t in re.findall(r"[a-z]+", v.lower()) if t not in _HONORIFICS]
            return " ".join(toks)
        return re.sub(r"\s+", " ", v.lower())

    def cluster(self, entities: list[DetectedEntity]) -> list[EntityCluster]:
        """Group mentions of the same real-world entity. Sets cluster_id on each entity in place.

        Cluster ids are sequential, never derived from the value - a hash of a name is
        reversible by guessing names.
        """
        groups: list[tuple[EntityType, set[str], list[DetectedEntity]]] = []
        for e in entities:
            key = self.normalise(e)
            if not key:
                continue
            toks = set(key.split())
            home = None
            for et, gtoks, members in groups:
                if et != e.entity_type:
                    continue
                if e.entity_type == EntityType.PERSON:
                    small, big = sorted([toks, gtoks], key=len)
                    same_doc = any(m.doc_id == e.doc_id for m in members)
                    # A lone surname joins a full name only inside the same document - across
                    # documents a single shared surname is far too weak to merge two people.
                    if toks == gtoks or (len(small) >= 2 and small <= big) or \
                            (same_doc and len(small) == 1 and small <= big):
                        home = (et, gtoks, members)
                        break
                elif self.normalise(members[0]) == key:
                    home = (et, gtoks, members)
                    break
            if home:
                home[2].append(e)
                home[1].update(toks)
            else:
                groups.append((e.entity_type, set(toks), [e]))

        groups = self._merge_name_variants(groups)
        clusters = []
        for i, (et, _, members) in enumerate(groups):
            cid = f"C{i + 1:04d}"
            for m in members:
                m.cluster_id = cid
            clusters.append(EntityCluster(cluster_id=cid, entity_type=et,
                                          entity_ids=[m.entity_id for m in members],
                                          doc_ids=sorted({m.doc_id for m in members})))
        return clusters

    def _merge_name_variants(self, groups):
        """Second pass for people. 'A. Rao' joins 'Ananya Rao', and a bare 'Rao' joins a full name,
        only when exactly one full name in the batch fits - two Raos means the short form stays
        ambiguous and unmerged, because a wrong merge links two people's documents."""
        def toks(members):
            return [t for t in re.findall(r"[a-z]+", members[0].raw().lower()) if t not in _HONORIFICS]
        people = [g for g in groups if g[0] == EntityType.PERSON]
        full = [g for g in people if len([t for t in toks(g[2]) if len(t) > 1]) >= 2]
        merged_into: dict[int, tuple] = {}
        for g in people:
            if g in full:
                continue
            t = toks(g[2])
            if not t:
                continue
            surname = t[-1]
            initial = t[0] if len(t) == 2 and len(t[0]) == 1 else None
            if len(t) > 2 or (len(t) == 2 and initial is None):
                continue
            fits = [f for f in full if toks(f[2])[-1] == surname and (initial is None or toks(f[2])[0].startswith(initial))]
            if len(fits) == 1:
                merged_into[id(g)] = fits[0]
        out = []
        for g in groups:
            target = merged_into.get(id(g))
            if target is not None:
                target[2].extend(g[2])
            else:
                out.append(g)
        return out

    @staticmethod
    def link(entities: list[DetectedEntity], max_doc_entities: int = 60) -> list[EntityLink]:
        """Co-occurrence graph over clusters (NetworkX). Edges carry the documents they came from."""
        g = nx.Graph()
        by_doc: dict[str, list[DetectedEntity]] = defaultdict(list)
        for e in entities:
            if e.cluster_id:
                g.add_node(e.cluster_id, entity_type=e.entity_type.value)
                by_doc[e.doc_id].append(e)

        def bump(a, b, relation, doc_id):
            if a == b:
                return
            if g.has_edge(a, b):
                d = g[a][b]
                d["weight"] += 1
                d["docs"].add(doc_id)
                if relation == "co_occurs_sentence":
                    d["relation"] = relation
            else:
                g.add_edge(a, b, weight=1, docs={doc_id}, relation=relation)

        for doc_id, ents in by_doc.items():
            by_sent: dict[int | None, set[str]] = defaultdict(set)
            for e in ents:
                by_sent[e.sentence_index].add(e.cluster_id)
            for members in by_sent.values():
                for a, b in combinations(sorted(members), 2):
                    bump(a, b, "co_occurs_sentence", doc_id)
            if len(ents) <= max_doc_entities:
                for a, b in combinations(sorted({e.cluster_id for e in ents}), 2):
                    if not g.has_edge(a, b) or doc_id not in g[a][b]["docs"]:
                        bump(a, b, "co_occurs_document", doc_id)

        return [EntityLink(source_cluster=a, target_cluster=b, relation=d["relation"],
                           doc_ids=sorted(d["docs"]), weight=float(d["weight"]))
                for a, b, d in g.edges(data=True)]
