"""Redaction completeness, data utility and end-to-end outcomes, from real pipeline runs.

Completeness is measured against dataset ground truth, not against what our own agents
detected: a gold span counts as protected if its original text no longer appears in the
released output (a blocked document releases nothing, so it is protected - and costs utility).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from privacy_review.datasets.prepare_dataset import LabeledExample
from privacy_review.orchestration.state import PipelineState
from privacy_review.schemas.entities import Span
from privacy_review.schemas.policy import Strategy
from privacy_review.schemas.verification import ReleaseStatus

# Types the knowledge base never allows to be kept (policy constraints PC-01 / PC-02).
NEVER_KEEP = {"PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "STREET_ADDRESS", "RECORD_IDENTIFIER", "ONLINE_IDENTIFIER",
              "DEVICE_IDENTIFIER", "GPS_COORDINATE", "DATE_OF_BIRTH", "MEDICAL_CONDITION", "GOVERNMENT_ID",
              "FINANCIAL_ACCOUNT", "CREDENTIAL"}


def _leaked(value: str, released: str) -> bool:
    v = value.strip()
    if len(v) < 2:
        return False
    return re.search(rf"(?<!\w){re.escape(v)}(?!\w)", released, re.I) is not None


def evaluate_runs(examples: list[LabeledExample], states: dict[str, PipelineState]) -> dict:
    gold_total = protected = 0
    nk_total = nk_protected = 0
    causes: Counter = Counter()
    cause_by_type: dict[str, Counter] = defaultdict(Counter)
    leaked_by_type: Counter = Counter()
    total_by_type: Counter = Counter()
    released = blocked = rounds = stalled = 0
    utilities = []
    for ex in examples:
        s = states[ex.example_id]
        rel = s.release[0]
        red = s.redacted[0]
        is_released = rel.status == ReleaseStatus.RELEASED
        released += is_released
        blocked += not is_released
        rounds += s.round
        stalled += s.stalled
        if s.verification:
            utilities.append(s.verification[0].utility_retained if is_released else 0.0)
        out = red.text if is_released else ""
        dec = {d.entity_id: d for d in (s.risk.decisions if s.risk else [])}
        for g in ex.gold:
            gold_total += 1
            t = g.entity_type.value
            total_by_type[t] += 1
            nk = t in NEVER_KEEP
            nk_total += nk
            if _leaked(ex.text[g.start:g.end], out):
                leaked_by_type[t] += 1
                gs = Span(start=g.start, end=g.end)
                hits = [e for e in s.entities if e.span.overlaps(gs)]
                if not hits:
                    cause = "undetected"
                elif all(dec.get(e.entity_id) and dec[e.entity_id].strategy == Strategy.KEEP for e in hits):
                    cause = "kept_by_policy"
                else:
                    cause = "partially_covered_or_repeated"
                causes[cause] += 1
                cause_by_type[t][cause] += 1
            else:
                protected += 1
                nk_protected += nk
    n = len(examples) or 1
    return {
        "documents": len(examples),
        "end_to_end": {"released": released, "blocked": blocked, "release_rate": round(released / n, 4),
                       "mean_remediation_rounds": round(rounds / n, 3), "stalled": stalled},
        "redaction_completeness": {
            "gold_spans": gold_total, "protected": protected,
            "completeness": round(protected / gold_total, 4) if gold_total else None,
            "never_keep_types": {"gold_spans": nk_total, "protected": nk_protected,
                                 "completeness": round(nk_protected / nk_total, 4) if nk_total else None},
            "leak_causes": dict(causes),
            "leak_causes_by_type": {t: dict(c) for t, c in sorted(cause_by_type.items())},
            "leaked_by_type": {t: {"leaked": leaked_by_type[t], "total": total_by_type[t],
                                   "leak_rate": round(leaked_by_type[t] / total_by_type[t], 4)}
                               for t in sorted(total_by_type) if leaked_by_type[t]},
        },
        "data_utility": {"mean_utility_retained_including_blocked": round(sum(utilities) / len(utilities), 4) if utilities else None,
                         "note": "unchanged text counts 1.0, generalised text 0.5, blocked documents 0"},
    }
