"""Normalise raw dataset rows into one internal format and split them.

LabeledExample is the only shape the rest of the system sees. Ground truth lives in `gold`
and is never handed to an agent in raw-text mode - see ground_truth.as_document().
"""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from privacy_review.datasets.label_maps import MERGE_ADJACENT, map_label
from privacy_review.schemas.entities import EntityType

Split = Literal["dev", "validation", "test", "external_test"]


class GoldSpan(BaseModel):
    start: int
    end: int
    entity_type: EntityType
    labels: list[str]                     # original label(s), after merging


class LabeledExample(BaseModel):
    example_id: str
    source: str                           # ai4privacy | piimb
    task: str
    split: Split
    text: str
    gold: list[GoldSpan]
    masked_target: Optional[str] = None
    stats: dict[str, int] = Field(default_factory=dict)

    def __repr__(self) -> str:
        return f"LabeledExample({self.example_id}, {len(self.gold)} gold spans)"


def _normalise(text: str, spans: list[tuple[int, int, str]], scheme: str, counts: Counter) -> list[GoldSpan]:
    mapped: list[GoldSpan] = []
    for start, end, label in sorted(spans):
        et = map_label(label, scheme)
        if et is None:
            counts["excluded"] += 1
            continue
        if not (0 <= start < end <= len(text)) or not text[start:end].strip():
            counts["invalid_span"] += 1
            continue
        mapped.append(GoldSpan(start=start, end=end, entity_type=et, labels=[label]))

    merged: list[GoldSpan] = []
    for g in mapped:
        prev = merged[-1] if merged else None
        gap = text[prev.end:g.start] if prev else None
        if prev and prev.entity_type == g.entity_type and g.entity_type in MERGE_ADJACENT \
                and gap is not None and len(gap) <= 3 and gap.strip(" ,") == "":
            merged[-1] = GoldSpan(start=prev.start, end=g.end, entity_type=g.entity_type, labels=prev.labels + g.labels)
            counts["merged"] += 1
        elif prev and g.start < prev.end:
            counts["overlapping_dropped"] += 1           # keep the first, dataset overlap is rare
        else:
            merged.append(g)
    return merged


def normalise_ai4privacy(rows: list[dict]) -> list[LabeledExample]:
    out = []
    for r in rows:
        counts: Counter = Counter()
        spans = [(m["start"], m["end"], m["label"]) for m in r["privacy_mask"]]
        gold = _normalise(r["source_text"], spans, "ai4privacy", counts)
        out.append(LabeledExample(
            example_id=f"ai4p-{r['id']}", source="ai4privacy", task="ai4privacy-en", split="dev",
            text=r["source_text"], gold=gold, masked_target=r.get("target_text"), stats=dict(counts)))
    return out


def normalise_piimb(rows: list[dict]) -> list[LabeledExample]:
    out = []
    for r in rows:
        counts: Counter = Counter()
        scheme = "piimb_presidio" if r["task_name"] == "privy" else "piimb_snake"
        spans = [(e["start"], e["end"], e["label"]) for e in r["entities"]]
        gold = _normalise(r["text"], spans, scheme, counts)
        out.append(LabeledExample(
            example_id=f"piimb-{r['task_name']}-{r['uid']}", source="piimb", task=r["task_name"],
            split="external_test", text=r["text"], gold=gold, stats=dict(counts)))
    return out


def split_examples(examples: list[LabeledExample], seed: int,
                   fractions=(0.5, 0.25, 0.25)) -> list[LabeledExample]:
    """dev / validation / test. Deterministic for a given seed; no example in two splits."""
    ids = sorted(e.example_id for e in examples)
    random.Random(seed).shuffle(ids)
    n = len(ids)
    a, b = int(n * fractions[0]), int(n * (fractions[0] + fractions[1]))
    which = {i: ("dev" if k < a else "validation" if k < b else "test") for k, i in enumerate(ids)}
    return [e.model_copy(update={"split": which[e.example_id]}) for e in examples]


def save(examples: list[LabeledExample], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(e.model_dump_json() for e in examples))


def load(path: Path) -> list[LabeledExample]:
    return [LabeledExample.model_validate_json(line) for line in path.read_text().splitlines() if line]


def summarise(examples: list[LabeledExample]) -> dict:
    by_type = Counter(g.entity_type.value for e in examples for g in e.gold)
    return {
        "examples": len(examples),
        "by_split": dict(Counter(e.split for e in examples)),
        "by_task": dict(Counter(e.task for e in examples)),
        "gold_spans": sum(by_type.values()),
        "gold_by_type": dict(by_type.most_common()),
        "excluded_labels": sum(e.stats.get("excluded", 0) for e in examples),
        "invalid_spans": sum(e.stats.get("invalid_span", 0) for e in examples),
        "merged_spans": sum(e.stats.get("merged", 0) for e in examples),
    }
