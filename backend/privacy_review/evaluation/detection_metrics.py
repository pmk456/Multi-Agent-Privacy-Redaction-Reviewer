"""Detection and annotation-validation metrics. Counts only - no text ever enters a report.

Three matching modes, because each answers a different question:
  strict   - exact span and same type        ("did we label it exactly as the annotator did?")
  relaxed  - overlapping span, same type      ("did we find it and call it the right thing?")
  coverage - a gold span is covered if >= 50% of its characters fall inside any prediction,
             whatever the type ("would this identifier have been redacted?")  <- the privacy number
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from privacy_review.datasets.ground_truth import Corruption, CorruptedAnnotation
from privacy_review.datasets.prepare_dataset import GoldSpan, LabeledExample
from privacy_review.schemas.entities import AnnotationStatus, DetectedEntity, EntityType, Span


@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def as_dict(self) -> dict:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn, "precision": round(self.precision, 4),
                "recall": round(self.recall, 4), "f1": round(self.f1, 4), "support": self.tp + self.fn}


def _gspan(g: GoldSpan) -> Span:
    return Span(start=g.start, end=g.end)


def _match(preds: list[DetectedEntity], gold: list[GoldSpan], same_type: bool, exact: bool) -> tuple[set, set]:
    """Greedy one-to-one matching by IoU. Returns (matched pred ids, matched gold indices)."""
    pairs = []
    for gi, g in enumerate(gold):
        gs = _gspan(g)
        for p in preds:
            if same_type and p.entity_type != g.entity_type:
                continue
            if exact and (p.span.start, p.span.end) != (g.start, g.end):
                continue
            if p.span.overlaps(gs):
                pairs.append((p.span.iou(gs), p.entity_id, gi))
    used_p, used_g = set(), set()
    for _, pid, gi in sorted(pairs, reverse=True):
        if pid not in used_p and gi not in used_g:
            used_p.add(pid)
            used_g.add(gi)
    return used_p, used_g


def evaluate_detection(examples: list[LabeledExample], predictions: dict[str, list[DetectedEntity]]) -> dict:
    gold_types = {g.entity_type for ex in examples for g in ex.gold}
    modes = {"strict": (True, True), "relaxed": (True, False)}
    per_type = {m: defaultdict(PRF) for m in modes}
    micro = {m: PRF() for m in modes}
    out_of_scope = Counter()
    cov_hit = cov_total = 0
    cov_by_type: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    cov_by_label: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    agnostic = PRF()

    for ex in examples:
        preds_all = predictions.get(ex.example_id, [])
        preds = [p for p in preds_all if p.entity_type in gold_types]
        out_of_scope.update(p.entity_type.value for p in preds_all if p.entity_type not in gold_types)

        for m, (st, exact) in modes.items():
            mp, mg = _match(preds, ex.gold, st, exact)
            for p in preds:
                (per_type[m][p.entity_type.value]).__setattr__("fp", per_type[m][p.entity_type.value].fp + (p.entity_id not in mp))
            for gi, g in enumerate(ex.gold):
                t = per_type[m][g.entity_type.value]
                if gi in mg:
                    t.tp += 1
                else:
                    t.fn += 1
            micro[m].tp += len(mg)
            micro[m].fp += len(preds) - len(mp)
            micro[m].fn += len(ex.gold) - len(mg)

        # coverage: character overlap with ANY prediction, any type
        for g in ex.gold:
            covered = set()
            for p in preds_all:
                lo, hi = max(g.start, p.span.start), min(g.end, p.span.end)
                covered.update(range(lo, hi))
            hit = len(covered) >= 0.5 * (g.end - g.start)
            cov_total += 1
            cov_hit += hit
            cov_by_type[g.entity_type.value][0] += hit
            cov_by_type[g.entity_type.value][1] += 1
            for lab in g.labels:
                cov_by_label[lab][0] += hit
                cov_by_label[lab][1] += 1
        # type-agnostic precision: does the prediction touch any gold span?
        for p in preds_all:
            if any(p.span.overlaps(_gspan(g)) for g in ex.gold):
                agnostic.tp += 1
            else:
                agnostic.fp += 1
    agnostic.fn = cov_total - cov_hit

    def macro(m):
        vals = [per_type[m][t].f1 for t in per_type[m] if per_type[m][t].tp + per_type[m][t].fn > 0]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    return {
        "examples": len(examples),
        "gold_spans": cov_total,
        "micro": {m: micro[m].as_dict() for m in modes},
        "macro_f1": {m: macro(m) for m in modes},
        "per_type": {m: {t: v.as_dict() for t, v in sorted(per_type[m].items())} for m in modes},
        "privacy_coverage": {
            "recall": round(cov_hit / cov_total, 4) if cov_total else 0.0,
            "covered": cov_hit, "total": cov_total,
            "precision_any_type": round(agnostic.precision, 4),
            "by_type": {t: {"covered": h, "total": n, "recall": round(h / n, 4)} for t, (h, n) in sorted(cov_by_type.items())},
            "by_original_label": {l: {"covered": h, "total": n, "recall": round(h / n, 4)}
                                  for l, (h, n) in sorted(cov_by_label.items(), key=lambda kv: kv[1][0] / kv[1][1])},
        },
        "predictions_of_types_not_annotated_in_dataset": dict(out_of_scope.most_common()),
    }


# ------------------------------------------------------------------ annotation validation

EXPECTED_STATUS = {
    Corruption.NONE: {AnnotationStatus.CONFIRMED},
    Corruption.SHIFTED: {AnnotationStatus.SPAN_MISMATCH},
    Corruption.WRONG_TYPE: {AnnotationStatus.TYPE_MISMATCH},
    Corruption.SPURIOUS: {AnnotationStatus.UNCONFIRMED},
    Corruption.OUT_OF_BOUNDS: {AnnotationStatus.INVALID},
}


def evaluate_annotation_validation(cases: list[tuple[LabeledExample, list[CorruptedAnnotation], "object"]]) -> dict:
    """cases: (example, corruption key, IntelligenceResult for that one document)."""
    exact = Counter()
    flagged = Counter()
    total = Counter()
    span_repaired = [0, 0]
    final_exact, final_total, final_covered = 0, 0, 0

    for ex, key, result in cases:
        reports = [r for r in result.annotation_reports if r.annotation_index is not None]
        by_idx = {r.annotation_index: r for r in reports}
        not_annot = [e for e in result.entities if e.annotation_status == AnnotationStatus.NOT_ANNOTATED]
        supplied_idx = 0
        for k in key:
            total[k.corruption.value] += 1
            if k.corruption == Corruption.DROPPED:
                g = ex.gold[k.gold_index]
                hit = any(e.span.overlaps(Span(start=g.start, end=g.end)) for e in not_annot)
                exact[k.corruption.value] += hit
                flagged[k.corruption.value] += hit
                continue
            r = by_idx.get(supplied_idx)
            supplied_idx += 1
            if r is None:
                continue
            exact[k.corruption.value] += r.status in EXPECTED_STATUS[k.corruption]
            if k.corruption == Corruption.NONE:
                flagged[k.corruption.value] += r.status != AnnotationStatus.CONFIRMED   # false alarm
            else:
                flagged[k.corruption.value] += r.status != AnnotationStatus.CONFIRMED
            if k.corruption == Corruption.SHIFTED and r.entity_id:
                g = ex.gold[k.gold_index]
                ent = next(e for e in result.entities if e.entity_id == r.entity_id or e.span.contains(Span(start=g.start + 2, end=g.end)))
                span_repaired[1] += 1
                span_repaired[0] += ent.span.contains(Span(start=g.start, end=g.end))

        for g in ex.gold:
            final_total += 1
            gs = Span(start=g.start, end=g.end)
            final_exact += any((e.span.start, e.span.end) == (g.start, g.end) for e in result.entities)
            final_covered += any(e.span.contains(gs) for e in result.entities)

    rows = {}
    for c in total:
        rows[c] = {"cases": total[c], "expected_status_rate": round(exact[c] / total[c], 4),
                   ("false_alarm_rate" if c == "none" else "flagged_rate"): round(flagged[c] / total[c], 4)}
    return {
        "by_corruption": rows,
        "shifted_spans_repaired_to_cover_gold": round(span_repaired[0] / span_repaired[1], 4) if span_repaired[1] else None,
        "span_level_accuracy_after_validation": {
            "exact_match": round(final_exact / final_total, 4) if final_total else 0.0,
            "gold_fully_covered": round(final_covered / final_total, 4) if final_total else 0.0,
            "gold_spans": final_total,
        },
    }
