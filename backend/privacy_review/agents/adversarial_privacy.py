"""Agent 5 - Adversarial Privacy.

Reads the redacted output the way an attacker would and asks: can these documents, alone or
together, still single someone out?

  1. Visible attributes per document: what was kept, what was generalised (weighted lower),
     quasi-identifiers that every earlier stage missed (its own scan of the redacted text),
     and uniqueness phrases ("the only ...", "the first ...").
  2. Linkage: documents are joined (NetworkX) when they share a batch-scoped pseudonym or at
     least N identical specific attribute values.
  3. Each linked component's combined fingerprint is scored: 1 - prod(1 - w) over specificity
     weights from the knowledge base, plus explicit high-risk combinations. A fingerprint
     shared by several components in the batch (a crowd) is downgraded.
  4. High risk -> blocking finding with the cheapest fix: generalise the most identifying
     attributes until the score drops, or switch pseudonyms to document scope to cut a link.

  in : original documents, redacted documents, entities, decisions
  out: AdversarialReport
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import networkx as nx
from pydantic import BaseModel, Field

from privacy_review.config import Settings, get_settings
from privacy_review.detection import EntityExtractor
from privacy_review.knowledge_base import PolicyEngine
from privacy_review.llm import Reasoner
from privacy_review.schemas.documents import Document
from privacy_review.schemas.entities import DetectedEntity, EntityType, Span
from privacy_review.schemas.policy import PseudonymScope, RedactionDecision, RiskLevel, Strategy
from privacy_review.schemas.redaction import RedactedDocument
from privacy_review.schemas.verification import AdversarialReport, Finding, FindingType, LinkageComponent, Severity

_SENIOR = re.compile(r"\b(?:principal|chief|head|lead|senior|director|vice|deputy|assistant warden|warden|dean)\b", re.I)


@dataclass
class Attribute:
    doc_id: str
    entity_type: EntityType
    value: str                            # normalised visible text - stays inside this agent
    specific: bool
    weight: float
    entity_ids: list[str] = field(default_factory=list)
    original_span: Optional[Span] = None  # for attributes no earlier agent detected
    level: int = 0                        # current generalisation level (0 = kept)

    @property
    def key(self) -> tuple:
        return (self.entity_type, self.value)


class LLMAttackerProbe(BaseModel):
    risk: RiskLevel = Field(description="How identifying the combined details are")
    reason: str = Field(description="Which details narrow it down. Do not repeat them verbatim.")


class AdversarialPrivacyAgent:
    name = "adversarial_privacy"

    def __init__(self, policy: PolicyEngine, settings: Settings | None = None, extractor: EntityExtractor | None = None,
                 reasoner: Reasoner | None = None):
        self.policy = policy
        self.settings = settings or get_settings()
        self.extractor = extractor or EntityExtractor(policy, self.settings, threshold=self.settings.verification_score_threshold)
        self.reasoner = reasoner
        self.rules = policy.linkage
        self.quasi = set(self.rules.specificity_weights)
        ref = policy.reference
        self.common_jobs = {j.lower() for j in ref.get("common_occupations", [])}

    # ================================================================ run
    def run(self, documents: list[Document], redacted: list[RedactedDocument], entities: list[DetectedEntity],
            decisions: list[RedactionDecision], revision: int = 0) -> AdversarialReport:
        """Person-centric: each pseudonymised person gets a fingerprint built only from details
        attached to their own mentions, so a newsletter naming ten people does not merge them
        into one 'subject'. Documents that name nobody are scored as document groups."""
        dec = {d.entity_id: d for d in decisions}
        ents = {e.entity_id: e for e in entities}
        by_doc_ents = defaultdict(list)
        for e in entities:
            by_doc_ents[e.doc_id].append(e)

        attrs: dict[str, list[Attribute]] = {}
        sent_of: dict[int, int | None] = {}
        cue_sents: dict[str, set] = {}
        persons: dict[str, list[tuple[str, str]]] = defaultdict(list)   # person key -> [(doc_id, entity_id)]
        for red in redacted:
            attrs[red.doc_id] = self._visible(red, by_doc_ents[red.doc_id], dec, sent_of, ents)
            cue_sents[red.doc_id] = self._cue_sentences(red, ents)
            for a in red.redactions:
                d = dec.get(a.entity_id)
                if a.strategy == Strategy.PSEUDONYMIZE and a.entity_type == EntityType.PERSON and d:
                    key = a.replacement if d.scope == PseudonymScope.BATCH else f"{red.doc_id}/{a.replacement}"
                    persons[key].append((red.doc_id, a.entity_id))

        subjects: list[dict] = []
        docs_with_people = set()
        for key, mentions in persons.items():
            docs = sorted({d for d, _ in mentions})
            docs_with_people.update(docs)
            own: list[Attribute] = []
            n_cues = 0
            for doc in docs:
                people_here = {k for k, ms in persons.items() if any(d == doc for d, _ in ms)}
                my_sents = {ents[eid].sentence_index for d, eid in mentions if d == doc and eid in ents}
                if len(people_here) == 1:
                    own += attrs[doc]
                    n_cues += len(cue_sents[doc])
                else:
                    own += [a for a in attrs[doc] if sent_of.get(id(a)) in my_sents]
                    n_cues += len(cue_sents[doc] & my_sents)
            subjects.append({"docs": docs, "fp": self._fingerprint(own), "cues": n_cues,
                             "linked_by": ["shared_pseudonym"] if len(docs) > 1 and "/" not in key else [],
                             "pseudonym": key, "subject": [eid for _, eid in mentions], "multi_link": len(docs) > 1})

        # documents that name nobody: group by shared specific values, as an attacker would
        g = nx.Graph()
        lonely = sorted(d for d in attrs if d not in docs_with_people)
        g.add_nodes_from(lonely)
        why: dict[frozenset, set] = defaultdict(set)
        for i, a in enumerate(lonely):
            ka = {x.key for x in attrs[a] if x.specific}
            for b in lonely[i + 1:]:
                shared = ka & {x.key for x in attrs[b] if x.specific}
                if len(shared) >= self.rules.link_on_shared_specific_values:
                    g.add_edge(a, b)
                    why[frozenset((a, b))].update(f"shared_{t.value}" for t, _ in shared)
        for comp in nx.connected_components(g):
            comp = sorted(comp)
            subjects.append({"docs": comp, "fp": self._fingerprint([x for d in comp for x in attrs[d]]),
                             "cues": sum(len(cue_sents[d]) for d in comp),
                             "linked_by": sorted({w for k, ws in why.items() if k <= set(comp) for w in ws}),
                             "pseudonym": None, "subject": [], "multi_link": False})

        all_fps = [s_["fp"] for s_ in subjects]
        findings: list[Finding] = []
        components: list[LinkageComponent] = []
        llm_probed = False
        for ci, sub in enumerate(subjects):
            fp, n_cues, comp = sub["fp"], sub["cues"], sub["docs"]
            score = self._score(fp.values(), n_cues)
            combo = self._combo_hit(fp.values())
            k = self._anonymity_set(fp, all_fps)
            risk = self._risk(score, combo, n_cues)
            if risk == RiskLevel.HIGH and k >= self.rules.min_anonymity_set and not n_cues:
                risk = RiskLevel.MEDIUM                    # a crowd shares this fingerprint
            if self.reasoner and self.reasoner.available and risk != RiskLevel.HIGH and len(fp) >= 2:
                probe = self._llm_probe([r for r in redacted if r.doc_id in comp])
                if probe is not None:
                    llm_probed = True
                    if probe.risk.rank > risk.rank:
                        risk = risk.llm_raise(probe.risk)        # one level at most
            components.append(LinkageComponent(
                component_id=f"L{ci + 1:03d}", doc_ids=comp, linked_by=sub["linked_by"],
                visible_quasi_types=sorted({t.value for t, _ in fp}), anonymity_set_size=k, risk=risk.value,
                subject_entity_ids=sub["subject"]))
            if risk == RiskLevel.HIGH:
                pl = {sub["pseudonym"]: set(comp)} if sub["multi_link"] else {}
                pe = {sub["pseudonym"]: sub["subject"]} if sub["multi_link"] else {}
                findings += self._remediate(comp, fp, score, n_cues, sub["multi_link"], pe, pl, k)
            elif risk == RiskLevel.MEDIUM:
                findings.append(Finding(
                    finding_type=FindingType.QUASI_IDENTIFIER_COMBINATION, severity=Severity.WARNING, doc_id=comp[0],
                    related_doc_ids=comp[1:], rule_id=self.rules.rule_id, entity_ids=sub["subject"],
                    description=f"visible quasi-identifiers ({', '.join(sorted({t.value for t, _ in fp}))}) give a "
                                f"moderate re-identification score ({score:.2f}); anonymity set within batch = {k}"))

        return AdversarialReport(revision=revision, safe_to_release=not any(f.severity == Severity.BLOCKING for f in findings),
                                 findings=findings, components=components, llm_probed=llm_probed)

    def _cue_sentences(self, red: RedactedDocument, ents: dict) -> set:
        """Sentence indices (original-text frame, via the segment map) holding a uniqueness phrase."""
        out = set()
        low = red.text.lower()
        for c in self.rules.uniqueness_cues:
            for m in re.finditer(rf"\b{re.escape(c)}\b", low):
                orig = red.to_original_span(Span(start=m.start(), end=m.end()))
                out.add(self._sentence_at(red, orig.start if orig else None, ents))
        return out

    @staticmethod
    def _sentence_at(red: RedactedDocument, orig_start, ents: dict):
        if orig_start is None:
            return None
        best = None
        for e in ents.values():
            if e.doc_id == red.doc_id and e.span.start <= orig_start and e.sentence_index is not None:
                if best is None or e.span.start > best.span.start:
                    best = e
        return best.sentence_index if best else 0

    # ================================================================ visible attributes
    def _visible(self, red: RedactedDocument, ents: list[DetectedEntity], dec: dict,
                 sent_of: dict | None = None, all_ents: dict | None = None) -> list[Attribute]:
        out: list[Attribute] = []
        w = self.rules.specificity_weights
        for a in red.redactions:                                         # generalised = partly visible
            if a.strategy == Strategy.GENERALIZE and a.entity_type in self.quasi:
                level = dec[a.entity_id].generalization_level if a.entity_id in dec else 1
                out.append(Attribute(red.doc_id, a.entity_type, a.replacement.strip().lower(), False,
                                     w[a.entity_type].generalized, [a.entity_id], level=level))
                if sent_of is not None and all_ents and a.entity_id in all_ents:
                    sent_of[id(out[-1])] = all_ents[a.entity_id].sentence_index
        scan = self.extractor.detect(red.doc_id, red.text, id_prefix="adv:").entities    # attacker's own read
        for r in scan:
            if r.entity_type not in self.quasi or red.in_replacement(r.span):
                continue
            orig = red.to_original_span(r.span)
            known = [e.entity_id for e in ents if orig and e.span.overlaps(orig)]
            value = re.sub(r"\s+", " ", r.raw().strip().lower())
            out.append(Attribute(red.doc_id, r.entity_type, value, True, self._weight(r.entity_type, value),
                                 known, None if known else orig))
            if sent_of is not None:
                sent_of[id(out[-1])] = (all_ents[known[0]].sentence_index if known and all_ents and known[0] in all_ents
                                        else self._sentence_at(red, orig.start if orig else None, all_ents or {}))
        return out

    def _weight(self, et: EntityType, value: str) -> float:
        w = self.rules.specificity_weights[et]
        if et == EntityType.OCCUPATION:
            if value in self.common_jobs:
                return w.generalized * 2                                 # "nurse" narrows far less
            if _SENIOR.search(value):
                return min(0.9, w.specific + 0.15)                       # "principal data scientist"
        return w.specific

    def _uniqueness_cues(self, text: str) -> int:
        low = text.lower()
        return sum(len(re.findall(rf"\b{re.escape(c)}\b", low)) for c in self.rules.uniqueness_cues)

    # ================================================================ scoring
    @staticmethod
    def _fingerprint(attrs: list[Attribute]) -> dict[tuple, Attribute]:
        fp: dict[tuple, Attribute] = {}
        for a in attrs:
            cur = fp.get(a.key)
            if cur is None or a.weight > cur.weight:
                fp[a.key] = Attribute(a.doc_id, a.entity_type, a.value, a.specific, a.weight,
                                      list(a.entity_ids), a.original_span, a.level)
            else:
                cur.entity_ids += [i for i in a.entity_ids if i not in cur.entity_ids]
        return fp

    def _score(self, attrs, n_cues: int) -> float:
        p = 1.0
        for a in attrs:
            p *= 1.0 - a.weight
        for _ in range(n_cues):
            p *= 1.0 - self.rules.uniqueness_cue_weight
        return 1.0 - p

    def _combo_hit(self, attrs) -> Optional[list[EntityType]]:
        specific = {a.entity_type for a in attrs if a.specific}
        return next((c for c in self.rules.high_risk_combinations if set(c) <= specific), None)

    def _risk(self, score: float, combo, n_cues: int) -> RiskLevel:
        if score >= self.rules.high_risk_threshold or combo or (n_cues and score >= self.rules.medium_risk_threshold):
            return RiskLevel.HIGH
        if score >= self.rules.medium_risk_threshold:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    @staticmethod
    def _anonymity_set(fp: dict, all_fps: list[dict]) -> int:
        """How many components in the batch look identical on this component's specific values."""
        mine = {k for k, a in fp.items() if a.specific}
        if not mine:
            return len(all_fps)
        return sum(1 for other in all_fps if mine <= {k for k, a in other.items() if a.specific})

    # ================================================================ remediation plan
    def _remediate(self, comp, fp, score, n_cues, pseudonym_linked, pseudonym_entities, pseudonym_links, k) -> list[Finding]:
        """Cheapest fix first: coarsen the most identifying attributes until the component is
        no longer high risk. Cutting a pseudonym link is recommended alongside, not instead."""
        out: list[Finding] = []
        multi = len(comp) > 1
        ftype = FindingType.CROSS_DOCUMENT_LINKAGE if multi else FindingType.QUASI_IDENTIFIER_COMBINATION
        sim = {key: Attribute(a.doc_id, a.entity_type, a.value, a.specific, a.weight, a.entity_ids, a.original_span, a.level)
               for key, a in fp.items()}
        chosen: list[tuple[Attribute, Strategy]] = []
        for key in sorted(sim, key=lambda k_: sim[k_].weight, reverse=True):
            if self._risk(self._score(sim.values(), n_cues), self._combo_hit(sim.values()), n_cues) != RiskLevel.HIGH:
                break
            a = sim[key]
            if a.specific:
                target = Strategy.GENERALIZE if self.policy.is_compliant(a.entity_type, Strategy.GENERALIZE) \
                    else self.policy.escalate(a.entity_type, Strategy.KEEP)
                a.specific, a.weight = False, self.rules.specificity_weights[a.entity_type].generalized
            else:
                target = Strategy.GENERALIZE if a.level < 2 else self.policy.escalate(a.entity_type, Strategy.GENERALIZE)
                a.weight = self.rules.specificity_weights[a.entity_type].generalized / 2 if a.level < 2 else 0.0
            chosen.append((a, target))

        types = ", ".join(sorted({t.value for t, _ in fp}))
        for a, target in chosen:
            out.append(Finding(
                finding_type=ftype, severity=Severity.BLOCKING, doc_id=a.doc_id, related_doc_ids=[d for d in comp if d != a.doc_id],
                rule_id=self.rules.rule_id, entity_ids=a.entity_ids, entity_type=a.entity_type,
                original_span=a.original_span, recommended_strategy=target,
                description=f"combined visible details ({types}) across {len(comp)} document(s) score {score:.2f}"
                            f"{' with a uniqueness phrase' if n_cues else ''}; anonymity set within batch = {k}. "
                            f"Recommend {target.value} for this {a.entity_type.value}."))
        if pseudonym_linked and multi:
            eids = [e for p, docs in pseudonym_links.items() if set(docs) <= set(comp) and len(docs) > 1
                    for e in pseudonym_entities[p]]
            if eids:
                out.append(Finding(
                    finding_type=FindingType.CROSS_DOCUMENT_LINKAGE, severity=Severity.BLOCKING, doc_id=comp[0],
                    related_doc_ids=comp[1:], rule_id=f"{self.rules.rule_id}:pseudonym", entity_ids=eids,
                    entity_type=EntityType.PERSON,
                    description="a batch-scoped pseudonym links these documents; switch to document-scoped "
                                "pseudonyms so they cannot be joined"))
        if not chosen and not out:                                       # nothing left to coarsen
            out.append(Finding(finding_type=ftype, severity=Severity.BLOCKING, doc_id=comp[0], related_doc_ids=comp[1:],
                               rule_id=self.rules.rule_id,
                               description=f"re-identification risk remains high ({score:.2f}) and no attribute can be "
                                           f"coarsened further; withhold"))
        return out

    # ================================================================ optional LLM probe (redacted text only)
    def _llm_probe(self, reds: list[RedactedDocument]) -> Optional[LLMAttackerProbe]:
        body = "\n\n".join(f"<document id='{r.doc_id}'>\n{r.text}\n</document>" for r in reds)
        system = ("Act as an attacker with general knowledge. These documents are already redacted. Assess how "
                  "easily the details that remain, combined, could single out one real person.")
        return self.reasoner.structured(purpose="agent5_probe", system=system, prompt=body, output_format=LLMAttackerProbe)
