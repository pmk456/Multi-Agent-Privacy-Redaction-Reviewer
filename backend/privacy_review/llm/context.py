"""Build privacy-protected context for LLM calls.

`tokenize` replaces every detected entity with a typed placeholder, so the model can reason
about *what kind* of information co-occurs ("[PERSON_1] works as [OCCUPATION_1] at
[ORGANIZATION_1]") without seeing a single value.
"""

from __future__ import annotations

from privacy_review.schemas.entities import DetectedEntity


def tokenize(text: str, entities: list[DetectedEntity]) -> tuple[str, dict[str, str]]:
    """Returns (tokenized_text, placeholder -> entity_id)."""
    counters: dict[str, int] = {}
    keys: dict[str, str] = {}
    by_cluster: dict[str, str] = {}
    pieces, pos = [], 0
    for e in sorted(entities, key=lambda e: e.span.start):
        if e.span.start < pos:
            continue
        group = e.cluster_id or e.entity_id
        if group in by_cluster:
            ph = by_cluster[group]
        else:
            counters[e.entity_type.value] = counters.get(e.entity_type.value, 0) + 1
            ph = f"[{e.entity_type.value}_{counters[e.entity_type.value]}]"
            by_cluster[group] = ph
        keys.setdefault(ph, e.entity_id)
        pieces.append(text[pos:e.span.start])
        pieces.append(ph)
        pos = e.span.end
    pieces.append(text[pos:])
    return "".join(pieces), keys


def window(text: str, start: int, end: int, chars: int) -> tuple[int, int]:
    return max(0, start - chars), min(len(text), end + chars)
