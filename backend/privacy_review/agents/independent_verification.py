"""Agent 4 - Independent Verification.

Does not trust Agents 1-3. Specifically:
  * runs its OWN detection over the REDACTED text, with a lower threshold than Agent 1
    (0.30 vs 0.40), so a miss by Agent 1 is not inherited;
  * re-derives the policy decision for every entity from the knowledge base and compares it
    with what was applied, instead of reading Agent 2's verdict;
  * checks that original values are gone from the output, by looking for them.

Rules VR-01..VR-08 come from the knowledge base. A blocking finding fails the document.

  in : original documents, redacted documents, entities, decisions
  out: VerificationReport per document
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from pydantic import BaseModel, Field

from privacy_review.config import Settings, get_settings
from privacy_review.detection import EntityExtractor
from privacy_review.knowledge_base import PolicyEngine
from privacy_review.llm import Reasoner
from privacy_review.schemas.documents import Document
from privacy_review.schemas.entities import DetectedEntity, EntityType, IdentifierClass, Span
from privacy_review.schemas.policy import RedactionDecision, Strategy
from privacy_review.schemas.redaction import RedactedDocument
from privacy_review.schemas.verification import Finding, FindingType, Severity, VerificationReport

_PSEUDONYM = re.compile(r"^[A-Z]+_\d{2,}$")
_INDIRECT = {IdentifierClass.INDIRECT, IdentifierClass.NON_IDENTIFYING}


class LLMResidualReview(BaseModel):
    class Item(BaseModel):
        text: str = Field(description="Exact substring of the redacted document that still identifies someone")
        entity_type: EntityType
    items: list[Item] = Field(default_factory=list)


class IndependentVerificationAgent:
    name = "independent_verification"

    def __init__(self, policy: PolicyEngine, settings: Settings | None = None, extractor: EntityExtractor | None = None,
                 reasoner: Reasoner | None = None):
        self.policy = policy
        self.settings = settings or get_settings()
        # Its own extractor instance and threshold. (The underlying Presidio engine object is
        # cached and shared for memory; what it is run on, and the cut-off, are not.)
        self.extractor = extractor or EntityExtractor(policy, self.settings, threshold=self.settings.verification_score_threshold)
        self.reasoner = reasoner
        self._rules = {r.check: r for r in policy.kb.verification_rules}

    def run(self, documents: list[Document], redacted: list[RedactedDocument], entities: list[DetectedEntity],
            decisions: list[RedactionDecision]) -> list[VerificationReport]:
        dec = {d.entity_id: d for d in decisions}
        originals = {d.doc_id: d for d in documents}
        reports = [self._verify(originals[r.doc_id], r, [e for e in entities if e.doc_id == r.doc_id], dec)
                   for r in redacted]
        self._pseudonym_consistency(redacted, entities, dec, reports)
        self._cross_document_values(redacted, entities, dec, reports)
        for rep in reports:
            rep.passed = not rep.blocking
        return reports

    # ============================================================== per document
    def _verify(self, doc: Document, red: RedactedDocument, ents: list[DetectedEntity],
                dec: dict[str, RedactionDecision]) -> VerificationReport:
        f: list[Finding] = []
        checks = []
        applied = {a.entity_id: a for a in red.redactions}

        checks.append("VR-08")
        for e in ents:
            if e.entity_id not in dec:
                f.append(self._finding(FindingType.POLICY_VIOLATION, Severity.BLOCKING, doc.doc_id, "VR-08",
                                       f"{e.entity_type.value} entity has no redaction decision", e))

        checks.append("VR-05")
        f += self._policy_compliance(doc, ents, dec, applied)
        checks.append("VR-03")
        f += self._span_integrity(red)
        checks.append("VR-04")
        f += self._format(red, {e.entity_id: e for e in ents})
        checks.append("VR-02")
        f += self._original_values_absent(red, ents, dec)
        checks.append("VR-01")
        f += self._residual(red, ents, dec)
        checks.append("VR-07")
        utility, over = self._utility(doc, red, ents, dec)
        f += over

        llm_reviewed = False
        if self.reasoner and self.reasoner.available:
            extra = self._llm_review(red)
            if extra is not None:
                llm_reviewed = True
                f += extra
                checks.append("LLM")
        return VerificationReport(doc_id=doc.doc_id, revision=red.revision, passed=False, findings=f,
                                  checks_run=checks, utility_retained=round(utility, 4), llm_reviewed=llm_reviewed)

    # -------------------------------------------------------------- VR-05
    def _policy_compliance(self, doc, ents, dec, applied) -> list[Finding]:
        """Re-derive the required strategy from the KB and compare with what was applied."""
        out = []
        esc = self.policy.context_escalations(ents)
        for e in ents:
            d = dec.get(e.entity_id)
            if d is None:
                continue
            _, risk, _ = self.policy.assess(e, ents, esc)
            required = self.policy.strategy_for(e.entity_type, risk)
            actual = applied[e.entity_id].strategy if e.entity_id in applied else Strategy.KEEP
            if not self.policy.is_compliant(e.entity_type, actual):
                out.append(self._finding(FindingType.POLICY_VIOLATION, Severity.BLOCKING, doc.doc_id, "VR-05",
                                         f"'{actual.value}' is not permitted for {e.entity_type.value}", e,
                                         recommended=self.policy.strategy_for(e.entity_type, risk)))
            elif actual.strength < required.strength:
                out.append(self._finding(FindingType.POLICY_VIOLATION, Severity.BLOCKING, doc.doc_id, "VR-05",
                                         f"{e.entity_type.value} at {risk.value} risk requires at least "
                                         f"'{required.value}', got '{actual.value}'", e, recommended=required))
            elif actual != d.strategy and not (d.strategy == Strategy.GENERALIZE and actual == Strategy.MASK):
                out.append(self._finding(FindingType.WRONG_TRANSFORMATION, Severity.BLOCKING, doc.doc_id, "VR-05",
                                         f"decided '{d.strategy.value}' but applied '{actual.value}'", e,
                                         recommended=d.strategy))
        return out

    # -------------------------------------------------------------- VR-03
    def _span_integrity(self, red: RedactedDocument) -> list[Finding]:
        out, prev_end = [], -1
        for a in sorted(red.redactions, key=lambda a: a.output_span.start if a.output_span else -1):
            s = a.output_span
            if s is None:
                continue
            if s.end > len(red.text) or red.text[s.start:s.end] != a.replacement:
                out.append(Finding(finding_type=FindingType.INVALID_SPAN, severity=Severity.BLOCKING, doc_id=red.doc_id,
                                   rule_id="VR-03", entity_ids=[a.entity_id], entity_type=a.entity_type,
                                   description="replacement is not at its recorded output span"))
            if s.start < prev_end:
                out.append(Finding(finding_type=FindingType.INVALID_SPAN, severity=Severity.BLOCKING, doc_id=red.doc_id,
                                   rule_id="VR-03", entity_ids=[a.entity_id], entity_type=a.entity_type,
                                   description="redaction spans overlap"))
            prev_end = max(prev_end, s.end)
        return out

    # -------------------------------------------------------------- VR-04
    def _format(self, red: RedactedDocument, ents: dict[str, DetectedEntity]) -> list[Finding]:
        tr = self.policy.transformation
        out = []
        for a in red.redactions:
            e = ents.get(a.entity_id)
            bad = None
            if a.strategy == Strategy.MASK and a.replacement != tr.mask_format.format(entity_type=a.entity_type.value):
                bad = "mask placeholder has the wrong format"
            elif a.strategy == Strategy.SUPPRESS and a.replacement != tr.suppress_token:
                bad = "suppression left something other than the suppress token"
            elif a.strategy == Strategy.PSEUDONYMIZE and not _PSEUDONYM.match(a.replacement):
                bad = "pseudonym does not match the pseudonym pattern"
            elif a.strategy == Strategy.GENERALIZE and e is not None and \
                    (a.replacement.strip().lower() == e.raw().strip().lower() or e.raw().strip().lower() in a.replacement.lower()):
                bad = "generalisation reproduces the original value"
            if bad:
                out.append(Finding(finding_type=FindingType.WRONG_TRANSFORMATION, severity=Severity.BLOCKING,
                                   doc_id=red.doc_id, rule_id="VR-04", entity_ids=[a.entity_id],
                                   entity_type=a.entity_type, description=bad, recommended_strategy=Strategy.MASK))
        return out

    # -------------------------------------------------------------- VR-02
    def _original_values_absent(self, red, ents, dec) -> list[Finding]:
        """Look for every original value (not kept by policy) anywhere in the unchanged text."""
        out = []
        kept_text = " ".join(red.text[s.out_start:s.out_end] for s in red.segments if not s.replaced).lower()
        for e in ents:
            d = dec.get(e.entity_id)
            v = e.raw().strip()
            if d is None or d.strategy == Strategy.KEEP or len(v) < 3:
                continue
            if re.search(rf"(?<!\w){re.escape(v.lower())}(?!\w)", kept_text):
                out.append(self._finding(FindingType.ORIGINAL_VALUE_PRESENT, Severity.BLOCKING, red.doc_id, "VR-02",
                                         f"an original {e.entity_type.value} value still appears elsewhere in the text", e,
                                         recommended=d.strategy))
        return out

    # -------------------------------------------------------------- VR-01
    def _residual(self, red: RedactedDocument, ents, dec) -> list[Finding]:
        det = self.extractor.detect(red.doc_id, red.text, id_prefix="verify:")
        kept = [e for e in ents if dec.get(e.entity_id) and dec[e.entity_id].strategy == Strategy.KEEP]
        rule = self._rules.get("residual_pii")
        out = []
        for r in det.entities:
            if red.in_replacement(r.span):
                continue                                    # inside a placeholder / generalised text
            orig = red.to_original_span(r.span)
            if orig and any(k.span.overlaps(orig) for k in kept):
                continue                                    # kept on purpose; VR-05 judged that
            cls = self.policy.identifier_class(r.entity_type)
            direct = cls not in _INDIRECT or self.policy.verification_required(r.entity_type)
            sev = (rule.severity_direct if direct else rule.severity_indirect) if rule else ("blocking" if direct else "warning")
            out.append(Finding(finding_type=FindingType.RESIDUAL_PII, severity=Severity(sev), doc_id=red.doc_id,
                               rule_id="VR-01", entity_type=r.entity_type, span=r.span, original_span=orig,
                               recommended_strategy=self.policy.strategy_for(r.entity_type, self.policy.sensitivity(r.entity_type)),
                               description=f"independent pass found an unredacted {r.entity_type.value} "
                                           f"(confidence {r.confidence:.2f})"))
        return out

    # -------------------------------------------------------------- VR-07
    def _utility(self, doc, red, ents, dec) -> tuple[float, list[Finding]]:
        """Share of the original text still readable: unchanged text counts fully,
        generalised text counts half (the reader keeps the gist)."""
        n = len(doc.text) or 1
        kept = sum(s.orig_end - s.orig_start for s in red.segments if not s.replaced)
        gen = sum(a.original_span.length for a in red.redactions if a.strategy == Strategy.GENERALIZE)
        utility = min(1.0, (kept + 0.5 * gen) / n)
        out = []
        floor = self.policy.defaults.min_utility_retained
        if utility < floor:
            out.append(Finding(finding_type=FindingType.OVER_REDACTION, severity=Severity.WARNING, doc_id=doc.doc_id,
                               rule_id="VR-07", description=f"only {utility:.0%} of the document remains readable "
                                                            f"(policy minimum {floor:.0%})"))
        esc = self.policy.context_escalations(ents)
        for e in ents:
            d = dec.get(e.entity_id)
            if d is None or d.strategy == Strategy.KEEP or d.remediation_round > 0 or e.ambiguous_person:
                continue
            _, risk, _ = self.policy.assess(e, ents, esc)
            if self.policy.strategy_for(e.entity_type, risk) == Strategy.KEEP:
                out.append(self._finding(FindingType.OVER_REDACTION, Severity.WARNING, doc.doc_id, "VR-07",
                                         f"{e.entity_type.value} at {risk.value} risk is 'keep' by policy but was "
                                         f"'{d.strategy.value}'", e))
        return utility, out

    # -------------------------------------------------------------- VR-06 (cross-document)
    def _pseudonym_consistency(self, redacted, entities, dec, reports) -> None:
        by_entity = {e.entity_id: e for e in entities}
        rep_of = {r.doc_id: r for r in reports}
        seen: dict[tuple, set[str]] = defaultdict(set)           # (scope key, cluster) -> pseudonyms
        owners: dict[tuple, set[str]] = defaultdict(set)         # (scope key, pseudonym) -> clusters
        where: dict[tuple, list] = defaultdict(list)
        for red in redacted:
            for a in red.redactions:
                if a.strategy != Strategy.PSEUDONYMIZE:
                    continue
                e = by_entity.get(a.entity_id)
                d = dec.get(a.entity_id)
                if e is None or d is None:
                    continue
                scope_key = "batch" if d.scope.value == "batch" else red.doc_id
                cluster = e.cluster_id or e.entity_id
                seen[(scope_key, cluster)].add(a.replacement)
                owners[(scope_key, a.replacement)].add(cluster)
                where[(scope_key, cluster)].append((red.doc_id, a.entity_id))
        for key, ps in seen.items():
            if len(ps) > 1:
                for doc_id, eid in where[key]:
                    rep_of[doc_id].findings.append(Finding(
                        finding_type=FindingType.INCONSISTENT_PSEUDONYM, severity=Severity.BLOCKING, doc_id=doc_id,
                        rule_id="VR-06", entity_ids=[eid], description=f"the same entity received {len(ps)} different pseudonyms"))
        for (scope_key, p), clusters in owners.items():
            if len(clusters) > 1:
                for c in clusters:
                    for doc_id, eid in where[(scope_key, c)]:
                        rep_of[doc_id].findings.append(Finding(
                            finding_type=FindingType.PSEUDONYM_COLLISION, severity=Severity.BLOCKING, doc_id=doc_id,
                            rule_id="VR-06", entity_ids=[eid], description="two different entities share one pseudonym"))
        for r in reports:
            if "VR-06" not in r.checks_run:
                r.checks_run.append("VR-06")

    # -------------------------------------------------------------- VR-02 across the batch
    def _cross_document_values(self, redacted, entities, dec, reports) -> None:
        """A value judged personal data and redacted in one document, appearing *undetected*
        in another, is a miss in that other document - if it was PII there, it is PII here.

        Only undetected occurrences are flagged: once the mention is an entity, Agent 2 decides
        its strategy by its own context and this check is satisfied."""
        rep_of = {r.doc_id: r for r in reports}
        known: dict[str, EntityType] = {}
        for e in entities:
            d = dec.get(e.entity_id)
            v = e.raw().strip()
            if d and d.strategy != Strategy.KEEP and len(v) >= 4 and any(ch.isalpha() or ch.isdigit() for ch in v):
                known.setdefault(v.lower(), e.entity_type)
        for red in redacted:
            mine = [e for e in entities if e.doc_id == red.doc_id]
            for seg in red.segments:
                if seg.replaced:
                    continue
                chunk = red.text[seg.out_start:seg.out_end].lower()
                for value, et in known.items():
                    for m in re.finditer(rf"(?<!\w){re.escape(value)}(?!\w)", chunk):
                        out_span = Span(start=seg.out_start + m.start(), end=seg.out_start + m.end())
                        orig = red.to_original_span(out_span)
                        if orig is None or any(e.span.overlaps(orig) for e in mine):
                            continue
                        rep_of[red.doc_id].findings.append(Finding(
                            finding_type=FindingType.ORIGINAL_VALUE_PRESENT, severity=Severity.BLOCKING,
                            doc_id=red.doc_id, rule_id="VR-02", entity_type=et, span=out_span, original_span=orig,
                            description=f"a {et.value} value redacted in another document appears here undetected"))
        for r in reports:
            if "VR-02x" not in r.checks_run:
                r.checks_run.append("VR-02x")

    # -------------------------------------------------------------- optional LLM review (redacted text only)
    def _llm_review(self, red: RedactedDocument) -> Optional[list[Finding]]:
        system = ("You review a document that has ALREADY been redacted. Placeholders like [EMAIL_ADDRESS], "
                  "[REDACTED] and PERSON_01 are fine. List any remaining text that still identifies a specific "
                  "person, copied verbatim.")
        out = self.reasoner.structured(purpose="agent4_review", system=system,
                                       prompt=f"<redacted>\n{red.text}\n</redacted>", output_format=LLMResidualReview)
        if out is None:
            return None
        findings = []
        for item in out.items:
            for m in re.finditer(re.escape(item.text), red.text) if item.text.strip() else []:
                span = Span(start=m.start(), end=m.end())
                if red.in_replacement(span):
                    continue
                direct = self.policy.identifier_class(item.entity_type) not in _INDIRECT
                findings.append(Finding(finding_type=FindingType.LLM_REVIEW,
                                        severity=Severity.BLOCKING if direct else Severity.WARNING, doc_id=red.doc_id,
                                        rule_id="LLM", entity_type=item.entity_type, span=span,
                                        original_span=red.to_original_span(span),
                                        description=f"LLM review flagged remaining {item.entity_type.value}"))
        return findings

    # -------------------------------------------------------------- helper
    @staticmethod
    def _finding(ft, sev, doc_id, rule, desc, e: DetectedEntity | None = None, recommended: Strategy | None = None) -> Finding:
        return Finding(finding_type=ft, severity=sev, doc_id=doc_id, rule_id=rule, description=desc,
                       entity_ids=[e.entity_id] if e else [], entity_type=e.entity_type if e else None,
                       original_span=e.span if e else None, recommended_strategy=recommended)
