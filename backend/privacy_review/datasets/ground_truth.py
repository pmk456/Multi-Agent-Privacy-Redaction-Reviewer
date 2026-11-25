"""Turning labelled examples into agent inputs, and corrupting annotations on purpose.

Raw-text mode hides ground truth from the agent completely. Annotated mode hands over the
gold spans as annotations - optionally corrupted, so annotation validation can be scored
against corruptions we know we introduced.
"""

from __future__ import annotations

import random
from enum import Enum

from pydantic import BaseModel

from privacy_review.datasets.prepare_dataset import LabeledExample
from privacy_review.schemas.documents import Annotation, Document


def as_document(ex: LabeledExample, mode: str = "raw") -> Document:
    if mode == "raw":
        return Document(doc_id=ex.example_id, text=ex.text, source=ex.source)
    if mode == "annotated":
        anns = [Annotation(start=g.start, end=g.end, label=g.entity_type.value) for g in ex.gold]
        return Document(doc_id=ex.example_id, text=ex.text, annotations=anns, source=ex.source)
    raise ValueError(mode)


class Corruption(str, Enum):
    NONE = "none"
    SHIFTED = "shifted"            # boundaries moved
    WRONG_TYPE = "wrong_type"      # label swapped
    DROPPED = "dropped"            # real PII left unannotated
    SPURIOUS = "spurious"          # annotation on text that is not PII
    OUT_OF_BOUNDS = "out_of_bounds"


class CorruptedAnnotation(BaseModel):
    annotation: Annotation | None  # None for DROPPED - nothing was supplied
    corruption: Corruption
    gold_index: int | None


_SWAP = {"PERSON": "LOCATION", "LOCATION": "ORGANIZATION", "EMAIL_ADDRESS": "URL",
         "PHONE_NUMBER": "FINANCIAL_ACCOUNT", "DATE": "AGE"}


def corrupt_annotations(ex: LabeledExample, rate: float, rng: random.Random) -> tuple[Document, list[CorruptedAnnotation]]:
    """Return a Document with corrupted annotations, plus the key of what was done."""
    key: list[CorruptedAnnotation] = []
    anns: list[Annotation] = []
    for i, g in enumerate(ex.gold):
        if rng.random() >= rate:
            a = Annotation(start=g.start, end=g.end, label=g.entity_type.value)
            anns.append(a)
            key.append(CorruptedAnnotation(annotation=a, corruption=Corruption.NONE, gold_index=i))
            continue
        kind = rng.choice([Corruption.SHIFTED, Corruption.WRONG_TYPE, Corruption.DROPPED])
        if kind == Corruption.SHIFTED and g.end - g.start > 3:
            a = Annotation(start=g.start + 2, end=g.end, label=g.entity_type.value)
        elif kind == Corruption.WRONG_TYPE and g.entity_type.value in _SWAP:
            a = Annotation(start=g.start, end=g.end, label=_SWAP[g.entity_type.value])
        elif kind == Corruption.DROPPED:
            key.append(CorruptedAnnotation(annotation=None, corruption=kind, gold_index=i))
            continue
        else:
            a, kind = Annotation(start=g.start, end=g.end, label=g.entity_type.value), Corruption.NONE
        anns.append(a)
        key.append(CorruptedAnnotation(annotation=a, corruption=kind, gold_index=i))

    # one spurious annotation on a non-PII word, and one out-of-bounds, per corrupted doc
    if rate > 0:
        covered = [(g.start, g.end) for g in ex.gold]
        words = [(m.start(), m.end()) for m in __import__("re").finditer(r"\b[a-z]{5,}\b", ex.text)
                 if not any(s < m.end() and m.start() < e for s, e in covered)]
        if words:
            s, e = rng.choice(words)
            a = Annotation(start=s, end=e, label="PERSON")
            anns.append(a)
            key.append(CorruptedAnnotation(annotation=a, corruption=Corruption.SPURIOUS, gold_index=None))
        a = Annotation(start=len(ex.text) + 5, end=len(ex.text) + 12, label="EMAIL_ADDRESS")
        anns.append(a)
        key.append(CorruptedAnnotation(annotation=a, corruption=Corruption.OUT_OF_BOUNDS, gold_index=None))

    return Document(doc_id=ex.example_id, text=ex.text, annotations=anns, source=ex.source), key
