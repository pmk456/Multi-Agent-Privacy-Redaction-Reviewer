"""Combine Presidio, spaCy, gazetteer and pattern candidates into one set of entities.

Resolution order for overlapping candidates: longer span, then higher score, then the more
specific detector. Same-type overlaps are merged (union) rather than dropped, because for
redaction under-coverage is the expensive mistake.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import SecretStr

from privacy_review.config import Settings, get_settings
from privacy_review.detection.candidates import Candidate
from privacy_review.detection.patterns import find_patterns
from privacy_review.detection.presidio_detector import PresidioDetector
from privacy_review.detection.spacy_processor import SpacyProcessor
from privacy_review.knowledge_base import PolicyEngine
from privacy_review.schemas.entities import DetectedEntity, DetectionSource, EntityType

MERGE_ADJACENT = {EntityType.PERSON, EntityType.STREET_ADDRESS}
_MONTH = re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", re.I)
_EVENT_WORDS = re.compile(r"\b(?:summit|conference|hackathon|festival|marathon|expo|symposium|workshop|championship|olympiad|"
                          r"fair|meetup|convention|awards?|gala|congress|forum|tournament|cup|games|ceremony|seminar|webinar)\b", re.I)
# Identifier keywords spaCy likes to tag as ORG: "SSN", "PAN", "IBAN" ...
_KEYWORD_ACRONYMS = {"ssn", "pan", "mrn", "id", "dob", "vin", "imei", "iban", "pin", "cvv", "url", "ip", "api",
                     "otp", "upi", "ifsc", "swift", "bic", "itin", "tin", "nhs", "aadhaar", "aadhar", "uid"}
# Words NER tags as ORG/LOCATION/PERSON/NRP that are not personal data. Each group matches a
# label the datasets deliberately leave unannotated (card issuers, currencies, directions).
_NON_IDENTIFYING = {
    "north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest", "north-east",
    "north-west", "south-east", "south-west",
    "visa", "mastercard", "amex", "american express", "discover", "maestro", "rupay", "jcb", "diners club", "unionpay",
    "bitcoin", "litecoin", "ethereum", "btc", "ltc", "eth", "crypto", "litecoin address", "bitcoin address",
    "ethereum address", "vpn", "ssl", "tls", "otp", "sms", "pdf", "faq", "ceo", "hr", "it",
    "usd", "eur", "gbp", "inr", "jpy", "cny", "aud", "cad", "chf", "bgn", "pln", "sek", "nok", "dkk", "czk", "huf",
    "ron", "try", "zar", "brl", "mxn", "rub", "krw", "sgd", "hkd", "nzd", "aed", "sar", "thb", "idr", "myr", "php",
    "vnd", "egp", "ngn", "kes", "pkr", "bdt", "lkr", "npr", "uah", "ils", "clp", "cop", "pen", "ars",
}
_GREETING = re.compile(r"^(?:dear|hi|hello|hey|greetings|attn:?|attention:?)\s+", re.I)
_TIME_ONLY = re.compile(r"^(?:\d{1,2}(?::\d{2}){1,2}\s*(?:[ap]\.?m\.?)?|\d{1,2}\s*(?:[ap]\.?m\.?)|\d{1,2}\s*o'?clock|noon|midnight)$", re.I)
_AGE_EXPR = re.compile(r"^\d{1,3}(?:\s*|-)(?:years?|yrs?)(?:[\s-]+old)?(?:\s+of\s+age)?$", re.I)
# A one-word "PERSON" whose part of speech cannot be a name: "Reach her at..." (imperative verb).
_NOT_A_NAME_POS = {"VERB", "AUX", "ADV", "ADP", "DET", "PRON", "CCONJ", "SCONJ", "INTJ", "NUM", "PART"}
_DOB_CUE = re.compile(r"\b(?:born|birth ?day|birth ?date|date of birth|d\.?o\.?b\.?)\b", re.I)


@dataclass
class DetectionOutput:
    entities: list[DetectedEntity]
    sentence_starts: list[int]
    stats: dict = field(default_factory=dict)


class EntityExtractor:
    """Stateless per call - safe to share, and Agent 4 builds its own instance."""

    def __init__(self, policy: PolicyEngine, settings: Settings | None = None, *, threshold: float | None = None):
        self.settings = settings or get_settings()
        self.policy = policy
        self.threshold = self.settings.presidio_score_threshold if threshold is None else threshold
        self.presidio = PresidioDetector(self.settings.spacy_model)
        self.spacy = SpacyProcessor(self.presidio.nlp, policy.reference.get("job_titles", []))

    # ------------------------------------------------------------------ public
    def candidates(self, text: str) -> tuple[list[Candidate], list[int]]:
        artifacts = self.presidio.process(text)
        doc = artifacts.tokens
        cands = self.presidio.candidates(text, artifacts, min(self.threshold, 0.3))
        cands = [c for c in cands if not self._pos_rules_out_name(c, doc)]
        cands += self.spacy.candidates(doc)
        cands += find_patterns(text)
        return cands, SpacyProcessor.sentence_starts(doc)

    def detect(self, doc_id: str, text: str, id_prefix: str = "") -> DetectionOutput:
        if not text.strip():
            return DetectionOutput([], [0], {"candidates": 0})
        cands, starts = self.candidates(text)
        resolved = self.resolve(cands, text)
        entities = [self._to_entity(c, doc_id, text, starts, f"{id_prefix}{doc_id}:e{i}")
                    for i, c in enumerate(resolved)]
        return DetectionOutput(entities, starts, {"candidates": len(cands), "resolved": len(resolved)})

    # ------------------------------------------------------------------ resolution
    def resolve(self, cands: list[Candidate], text: str) -> list[Candidate]:
        cands = [self._trim(c, text) for c in cands]
        cands = [c for c in cands if c and c.score >= self.threshold and self._plausible(c, text)]

        # 1. merge overlapping candidates of the same type
        by_type: dict[EntityType, list[Candidate]] = {}
        for c in cands:
            by_type.setdefault(c.entity_type, []).append(c)
        merged: list[Candidate] = []
        for et, group in by_type.items():
            group.sort(key=lambda c: c.start)
            cur = group[0]
            for c in group[1:]:
                if c.start < cur.end:
                    cur = Candidate(cur.start, max(cur.end, c.end), et, max(cur.score, c.score),
                                    cur.source, cur.label, cur.sources | c.sources)
                else:
                    merged.append(cur)
                    cur = c
            merged.append(cur)

        # 2. across types: keep the best-ranked, drop what overlaps it
        chosen: list[Candidate] = []
        for c in sorted(merged, key=lambda c: c.rank(), reverse=True):
            if not any(c.overlaps(k) for k in chosen):
                chosen.append(c)
        chosen.sort(key=lambda c: c.start)

        # 3. adjacent mentions that form one entity ("Ananya" "Rao"; "42" "Park Street")
        out: list[Candidate] = []
        for c in chosen:
            prev = out[-1] if out else None
            if prev and prev.entity_type == c.entity_type and c.entity_type in MERGE_ADJACENT:
                gap = text[prev.end:c.start]
                if len(gap) <= 3 and gap.strip(" ,") == "":
                    out[-1] = Candidate(prev.start, c.end, c.entity_type, max(prev.score, c.score),
                                        prev.source, prev.label, prev.sources | c.sources)
                    continue
            out.append(c)
        return [self._promote_dob(c, text) for c in out]

    @staticmethod
    def _pos_rules_out_name(c: Candidate, doc) -> bool:
        if c.entity_type != EntityType.PERSON or c.sources != {DetectionSource.SPACY}:
            return False
        span = doc.char_span(c.start, c.end, alignment_mode="expand")
        return span is not None and len(span) == 1 and span[0].pos_ in _NOT_A_NAME_POS

    @staticmethod
    def _trim(c: Candidate, text: str) -> Candidate | None:
        s, e = c.start, c.end
        while s < e and (text[s] in " \t\n\"'" or (text[s] == "(" and ")" not in text[s:e])):
            s += 1
        m = re.match(r"(?:the|a|an)\s+", text[s:e], re.I)          # "the Global AI Summit"
        if m and c.entity_type in (EntityType.ORGANIZATION, EntityType.EVENT, EntityType.LOCATION, EntityType.OCCUPATION):
            s += m.end()
        m = _GREETING.match(text[s:e])                               # "Dear Danyka" -> "Danyka"
        if m and c.entity_type == EntityType.PERSON:
            s += m.end()
        while e > s and text[e - 1] in " \t\n,;:\"')" and c.entity_type != EntityType.GPS_COORDINATE:
            e -= 1
        if e > s and text[e - 1] == "." and c.entity_type != EntityType.STREET_ADDRESS \
                and not re.search(r"\b[A-Z][a-z]?\.$", text[s:e]):
            e -= 1
        if e <= s:
            return None
        et = c.entity_type
        if et == EntityType.ORGANIZATION and _EVENT_WORDS.search(text[s:e]):
            et = EntityType.EVENT
        if et == EntityType.DATE and _AGE_EXPR.match(text[s:e]):
            et = EntityType.AGE                # "92 years old" is an age, kept whole
        return Candidate(s, e, et, c.score, c.source, c.label, c.sources)

    @staticmethod
    def _plausible(c: Candidate, text: str) -> bool:
        span = text[c.start:c.end]
        low = span.strip().lower()
        if c.entity_type == EntityType.ORGANIZATION and low in _KEYWORD_ACRONYMS:
            return False
        if c.entity_type in (EntityType.ORGANIZATION, EntityType.LOCATION, EntityType.PERSON, EntityType.DEMOGRAPHIC) \
                and DetectionSource.PATTERN not in c.sources and low in _NON_IDENTIFYING:
            return False
        if c.entity_type == EntityType.ORGANIZATION and re.search(r"\baccount$", low):
            return False                       # "Auto Loan Account" - a product name
        if c.entity_type == EntityType.PERSON and not re.search(r"[A-Za-z]{2}", re.sub(r"\b(?:mr|mrs|ms|mx|dr|prof)\b", "", low)):
            return False                       # "Ms./Mr"
        if c.entity_type == EntityType.DATE:
            # spaCy tags "today", "last year", "three weeks", "9:13 PM" - not identifying.
            if _TIME_ONLY.match(span.strip()):
                return False
            return any(ch.isdigit() for ch in span) or bool(_MONTH.search(span))
        if c.entity_type in (EntityType.PERSON, EntityType.ORGANIZATION, EntityType.LOCATION):
            return any(ch.isalpha() for ch in span) and len(span.strip()) > 1
        return True

    @staticmethod
    def _promote_dob(c: Candidate, text: str) -> Candidate:
        if c.entity_type == EntityType.DATE and _DOB_CUE.search(text[max(0, c.start - 30):c.start]):
            return Candidate(c.start, c.end, EntityType.DATE_OF_BIRTH, c.score, c.source, "dob_context", c.sources)
        return c

    # ------------------------------------------------------------------ build entity
    def _to_entity(self, c: Candidate, doc_id: str, text: str, starts: list[int], entity_id: str) -> DetectedEntity:
        from privacy_review.schemas.entities import Span
        return DetectedEntity(
            entity_id=entity_id, doc_id=doc_id, entity_type=c.entity_type,
            span=Span(start=c.start, end=c.end), value=SecretStr(text[c.start:c.end]),
            confidence=round(min(1.0, c.score), 3), sources=sorted(c.sources, key=lambda s: s.value),
            identifier_class=self.policy.identifier_class(c.entity_type), original_label=c.label,
            sentence_index=SpacyProcessor.sentence_index(starts, c.start),
        )
