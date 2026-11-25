"""Verification failure detection rate, by fault injection.

For each document we run Agents 1-3, then inject exactly one known fault and ask Agent 4
whether the document passes. Detection rate = share of faulty runs Agent 4 blocks. The
false-alarm rate = share of clean runs it blocks.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict

from privacy_review.schemas import Document, Strategy

FAULTS = ("skip_entity", "keep_direct", "tamper_mask", "reproduce_generalisation", "drop_decision")


def inject(fault, docs, agents, rng):
    a1, a2, a3, a4, _ = agents
    intel = a1.run(docs)
    ents, decs = intel.entities, a2.run(intel.entities).decisions
    direct = [e for e in ents if e.identifier_class.value == "direct_identifier"]
    if fault == "skip_entity":
        if not direct:
            return None
        victim = rng.choice(direct)
        ents = [e for e in ents if e.entity_id != victim.entity_id]          # Agent 1 "missed" it
        decs = a2.run(ents).decisions
    elif fault == "keep_direct":
        if not direct:
            return None
        victim = rng.choice(direct).entity_id
        decs = [d.model_copy(update={"strategy": Strategy.KEEP}) if d.entity_id == victim else d for d in decs]
    elif fault == "drop_decision":
        if not decs:
            return None
        decs = decs[1:]
    red = a3.run(docs, ents, decs, "fault")
    if fault == "tamper_mask":
        masks = [a for a in red[0].redactions if a.strategy == Strategy.MASK]
        if not masks:
            return None
        bad = rng.choice(masks)
        red[0].redactions = [a.model_copy(update={"replacement": "[X]"}) if a is bad else a for a in red[0].redactions]
    elif fault == "reproduce_generalisation":
        gens = [a for a in red[0].redactions if a.strategy == Strategy.GENERALIZE]
        if not gens:
            return None
        bad = rng.choice(gens)
        val = next(e.raw() for e in ents if e.entity_id == bad.entity_id)
        red[0].redactions = [a.model_copy(update={"replacement": val}) if a is bad else a for a in red[0].redactions]
    reports = a4.run(docs, red, intel.entities if fault == "skip_entity" else ents, decs) if fault != "skip_entity" \
        else a4.run(docs, red, ents, decs)
    return not reports[0].passed


def evaluate_verification(texts: list[tuple[str, str]], agents, seed: int) -> dict:
    rng = random.Random(seed)
    caught, tried = Counter(), Counter()
    false_alarms = clean = 0
    for doc_id, text in texts:
        docs = [Document(doc_id=doc_id, text=text)]
        a1, a2, a3, a4, _ = agents
        intel = a1.run(docs)
        decs = a2.run(intel.entities).decisions
        rep = a4.run(docs, a3.run(docs, intel.entities, decs, "clean"), intel.entities, decs)[0]
        clean += 1
        false_alarms += not rep.passed
        for f in FAULTS:
            r = inject(f, docs, agents, rng)
            if r is None:
                continue
            tried[f] += 1
            caught[f] += r
    return {
        "documents": clean,
        "clean_false_alarm_rate": round(false_alarms / clean, 4) if clean else None,
        "detection_rate_by_fault": {f: {"caught": caught[f], "injected": tried[f],
                                        "rate": round(caught[f] / tried[f], 4) if tried[f] else None} for f in FAULTS},
        "overall_detection_rate": round(sum(caught.values()) / sum(tried.values()), 4) if tried else None,
    }
