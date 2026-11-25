"""Agent 5 and Agent 2 against the synthetic cross-document dataset (tests/fixtures).

Ground truth comes from the dataset's hidden registry, not from any agent:
  * planted risk that is reidentifiable and survives the first pass -> Agent 5 must flag it
  * control (k >= 3, or no longer identifying after the first pass) -> must NOT be flagged
  * expected_strategies -> Agent 2's first-pass decisions, matched by span
"""

from __future__ import annotations

from collections import Counter

from privacy_review.schemas import Document, Severity, Span


def evaluate_synthetic(data: dict, agents, batch_id: str = "synthetic") -> dict:
    a1, a2, a3, a4, a5 = agents
    docs = [Document(doc_id=d["doc_id"], text=d["text"]) for d in data["documents"]]
    intel = a1.run(docs)
    risk = a2.run(intel.entities, {d.doc_id: d.text for d in docs})
    red = a3.run(docs, intel.entities, risk.decisions, batch_id)
    adv = a5.run(docs, red, intel.entities, risk.decisions)
    # which person each target is: their PERSON entities, via the dataset's mentions
    person_ents: dict[str, set] = {}
    for m in data["mentions"]:
        if m["entity_type"] == "PERSON" and m["person_id"]:
            span = Span(start=m["start"], end=m["end"])
            person_ents.setdefault(m["person_id"], set()).update(
                e.entity_id for e in intel.entities if e.doc_id == m["doc_id"] and e.span.overlaps(span))
    high = [c for c in adv.components if c.risk == "high"]

    cm = Counter()
    rows = []
    for r in data["planted_risks"]:
        should = r["reidentifiable"] and r["survives_first_pass"]
        mine = person_ents.get(r["person_id"], set())
        did = any(set(c.subject_entity_ids) & mine for c in high)
        cm[("tp" if did else "fn") if should else ("fp" if did else "tn")] += 1
        rows.append({"risk_id": r["risk_id"], "expected_flag": should, "flagged": did,
                     "k": r["anonymity_set_size"], "k_after_first_pass": r["anonymity_set_size_after_first_pass"]})

    # Agent 2 strategy agreement with expected_strategies
    dec = {d.entity_id: d for d in risk.decisions}
    agree = total = missed = 0
    by_type = Counter(); by_type_ok = Counter()
    for x in data["expected_strategies"]:
        total += 1
        span = Span(start=x["start"], end=x["end"])
        hit = [e for e in intel.entities if e.doc_id == x["doc_id"] and e.span.overlaps(span)]
        by_type[x["entity_type"]] += 1
        if not hit:
            missed += 1
            continue
        best = max(hit, key=lambda e: e.span.iou(span))
        ok = dec[best.entity_id].strategy.value == x["expected_strategy"]
        agree += ok; by_type_ok[x["entity_type"]] += ok

    # name variants: all PERSON mentions of a target in one cluster?
    person_clusters: dict[str, set] = {}
    for m in data["mentions"]:
        if m["entity_type"] != "PERSON" or not m["person_id"]:
            continue
        span = Span(start=m["start"], end=m["end"])
        hit = [e for e in intel.entities if e.doc_id == m["doc_id"] and e.span.overlaps(span)]
        person_clusters.setdefault(m["person_id"], set()).update(e.cluster_id for e in hit)
    unified = sum(len(c) == 1 for c in person_clusters.values())

    n_pos = cm["tp"] + cm["fn"]; n_neg = cm["fp"] + cm["tn"]
    return {
        "documents": len(docs), "planted_risks": len(rows),
        "agent5": {"confusion": dict(cm),
                   "reidentification_detection_rate": round(cm["tp"] / n_pos, 4) if n_pos else None,
                   "false_positive_rate_on_controls": round(cm["fp"] / n_neg, 4) if n_neg else None,
                   "per_risk": rows},
        "agent2_strategy_agreement": {"agree": agree, "total": total, "rate": round(agree / total, 4),
                                      "mentions_not_detected": missed,
                                      "by_type": {t: f"{by_type_ok[t]}/{by_type[t]}" for t in sorted(by_type)}},
        "agent1_name_variants": {"targets_with_person_mentions": len(person_clusters),
                                 "all_mentions_in_one_cluster": unified},
    }
