"""spaCy-side extraction that Presidio does not do: events, nationality/religious groups,
occupation gazetteer, sentence boundaries.

The spaCy model is loaded once and shared with Presidio (see presidio_detector.py).
"""

from __future__ import annotations

from bisect import bisect_right

from spacy.matcher import PhraseMatcher
from spacy.tokens import Doc

from privacy_review.detection.candidates import Candidate
from privacy_review.schemas.entities import DetectionSource, EntityType

# Labels Presidio's spaCy recognizer already maps (PERSON, GPE/LOC/FAC, ORG, DATE, NORP)
# are taken from Presidio. These are the ones it ignores.
EXTRA_NER = {"EVENT": EntityType.EVENT}


class SpacyProcessor:
    def __init__(self, nlp, job_titles: list[str]):
        self.nlp = nlp
        self.matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
        self.matcher.add("JOB_TITLE", [nlp.make_doc(t) for t in job_titles])

    def candidates(self, doc: Doc) -> list[Candidate]:
        out: list[Candidate] = []
        for ent in doc.ents:
            et = EXTRA_NER.get(ent.label_)
            if et is not None:
                out.append(Candidate(ent.start_char, ent.end_char, et, 0.6, DetectionSource.SPACY, ent.label_))
        for _, s, e in self.matcher(doc):
            span = doc[s:e]
            out.append(Candidate(span.start_char, span.end_char, EntityType.OCCUPATION, 0.65,
                                 DetectionSource.GAZETTEER, "job_title"))
        return out

    @staticmethod
    def sentence_starts(doc: Doc) -> list[int]:
        return [s.start_char for s in doc.sents]

    @staticmethod
    def sentence_index(starts: list[int], char_offset: int) -> int:
        return max(0, bisect_right(starts, char_offset) - 1)
