"""Generate frontend/mock/batch_result.json from the real Pydantic models.

    python scripts/make_frontend_mock.py          (from backend/)

FICTIONAL data only: invented names, emails @example.com, phones 555-01xx. The fictional
"original" text is built here only so that spans are consistent; it is never written out.
tests/test_frontend_mock.py checks the file validates against BatchResult and matches
this generator, so the mock cannot drift from the schema.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from privacy_review.schemas import (  # noqa: E402
    AdversarialReport,
    AggregateStatistics,
    BatchResult,
    EntityType,
    Finding,
    FindingType,
    IdentifierClass,
    LinkageComponent,
    PseudonymScope,
    PublicEntity,
    RedactionDecision,
    ReleaseDecision,
    ReleaseStatus,
    RiskAssessment,
    RiskLevel,
    SanitizedDocument,
    Severity,
    Span,
    Strategy,
    VerificationReport,
)

OUT = Path(__file__).resolve().parents[2] / "frontend" / "mock" / "batch_result.json"
BATCH_ID = "demo-batch-0001"
CHECKS = ["residual_pii", "original_value_present", "span_validity", "transformation", "policy"]

D, Q, S = IdentifierClass.DIRECT, IdentifierClass.INDIRECT, IdentifierClass.SENSITIVE_ATTRIBUTE


@dataclass
class E:
    """One fictional entity: original value, what replaces it, and how it was judged."""
    original: str
    replacement: str
    entity_type: EntityType
    strategy: Strategy
    risk: RiskLevel
    identifier_class: IdentifierClass
    policy_id: str
    rationale: str
    cluster_id: str | None = None
    rules: tuple[str, ...] = ()
    base_risk: RiskLevel | None = None
    scope: PseudonymScope = PseudonymScope.DOCUMENT


def build_doc(doc_id: str, parts: list):
    """Return (redacted_text, entities, risks, decisions) for a list of str | E parts."""
    original, redacted = "", ""
    entities, risks, decisions = [], [], []
    for part in parts:
        if isinstance(part, str):
            original += part
            redacted += part
            continue
        n = len(entities) + 1
        eid = f"{doc_id}:e{n:02d}"
        start = len(original)
        original += part.original
        redacted += part.replacement
        entities.append(PublicEntity(
            entity_id=eid, doc_id=doc_id, entity_type=part.entity_type,
            span=Span(start=start, end=len(original)),
            confidence=0.97 if part.identifier_class is D else 0.86,
            identifier_class=part.identifier_class, cluster_id=part.cluster_id,
        ))
        risks.append(RiskAssessment(
            entity_id=eid, entity_type=part.entity_type,
            base_risk=part.base_risk or part.risk, risk=part.risk,
            fired_rules=list(part.rules), rationale=part.rationale,
        ))
        decisions.append(RedactionDecision(
            entity_id=eid, entity_type=part.entity_type, strategy=part.strategy,
            risk=part.risk, policy_id=part.policy_id, scope=part.scope,
            rationale=f"{part.strategy.value} per {part.policy_id} at {part.risk.value} risk",
        ))
    return redacted, entities, risks, decisions


def person(original: str, token: str, cluster: str) -> E:
    return E(original, token, EntityType.PERSON, Strategy.PSEUDONYMIZE, RiskLevel.HIGH, D,
             "POL-PERSON", "Full name is a direct identifier.", cluster_id=cluster,
             scope=PseudonymScope.BATCH)


def build_mock() -> BatchResult:
    docs: list[SanitizedDocument] = []

    # --- 1. HR record: released --------------------------------------------------------
    text, ents, risks, decs = build_doc("hr-record-01", [
        "HR record. Employee ", person("Meera Fictiona", "PERSON_01", "c-person-01"),
        " (age ", E("34", "30-39", EntityType.AGE, Strategy.GENERALIZE, RiskLevel.MEDIUM, Q,
                    "POL-AGE", "Exact age narrows the population.", rules=("QI-AGE-OCC",),
                    base_risk=RiskLevel.LOW),
        ") joined as a ", E("staff nurse", "staff nurse", EntityType.OCCUPATION, Strategy.KEEP,
                            RiskLevel.LOW, Q, "POL-OCCUPATION", "Common occupation; kept for utility."),
        " at ", E("Lakeview Demo Hospital", "[ORGANIZATION]", EntityType.ORGANIZATION, Strategy.MASK,
                  RiskLevel.MEDIUM, Q, "POL-ORG", "Employer combined with occupation is quasi-identifying.",
                  cluster_id="c-org-01", rules=("QI-ORG-OCC",), base_risk=RiskLevel.LOW),
        " in ", E("Bengaluru", "Karnataka", EntityType.LOCATION, Strategy.GENERALIZE, RiskLevel.MEDIUM,
                  Q, "POL-LOCATION", "City generalised to state."),
        ". Contact: ", E("meera.fictiona@example.com", "[EMAIL_ADDRESS]", EntityType.EMAIL_ADDRESS,
                         Strategy.MASK, RiskLevel.HIGH, D, "POL-EMAIL", "Email is a direct identifier."),
        ", ", E("555-0142", "[PHONE_NUMBER]", EntityType.PHONE_NUMBER, Strategy.MASK, RiskLevel.HIGH, D,
                "POL-PHONE", "Phone number is a direct identifier."),
        ". Employee ID ", E("EMP-55-0199", "[REDACTED]", EntityType.RECORD_IDENTIFIER, Strategy.SUPPRESS,
                            RiskLevel.CRITICAL, D, "POL-RECORD-ID", "Record numbers link back to source systems."),
        ".",
    ])
    docs.append(SanitizedDocument(
        doc_id="hr-record-01", released=True, redacted_text=text,
        entities=ents, risks=risks, decisions=decs,
        verification=VerificationReport(
            doc_id="hr-record-01", revision=1, passed=True, checks_run=CHECKS, utility_retained=0.71,
            findings=[Finding(
                finding_type=FindingType.RESIDUAL_PII, severity=Severity.WARNING, doc_id="hr-record-01",
                description="Possible residual age reference found in round 0; generalised in round 1.",
                entity_type=EntityType.AGE, entity_ids=["hr-record-01:e02"],
                recommended_strategy=Strategy.GENERALIZE, rule_id="V-RESIDUAL",
            )],
        ),
        release=ReleaseDecision(doc_id="hr-record-01", status=ReleaseStatus.RELEASED,
                                reason="All verification checks passed after 1 remediation round.",
                                remediation_rounds=1),
    ))

    # --- 2. Award news item: released ---------------------------------------------------
    text, ents, risks, decs = build_doc("award-news-02", [
        person("Meera Fictiona", "PERSON_01", "c-person-01"),
        " received the ", E("Golden Lamp Award 2026", "[EVENT]", EntityType.EVENT, Strategy.MASK,
                            RiskLevel.MEDIUM, Q, "POL-EVENT", "Named award narrows to few recipients."),
        " for outstanding patient care. The ceremony was held in ",
        E("Bengaluru", "Karnataka", EntityType.LOCATION, Strategy.GENERALIZE, RiskLevel.LOW, Q,
          "POL-LOCATION", "City generalised to state."),
        " on ", E("14 March 2026", "March 2026", EntityType.DATE, Strategy.GENERALIZE, RiskLevel.LOW, Q,
                  "POL-DATE", "Day removed; month kept for context."),
        ".",
    ])
    docs.append(SanitizedDocument(
        doc_id="award-news-02", released=True, redacted_text=text,
        entities=ents, risks=risks, decisions=decs,
        verification=VerificationReport(
            doc_id="award-news-02", revision=0, passed=True, checks_run=CHECKS, utility_retained=0.84,
            findings=[Finding(
                finding_type=FindingType.OVER_REDACTION, severity=Severity.INFO, doc_id="award-news-02",
                description="Event name masked; a generalised category would retain more utility.",
                entity_type=EntityType.EVENT, entity_ids=["award-news-02:e02"],
                recommended_strategy=Strategy.GENERALIZE, rule_id="V-UTILITY",
            )],
        ),
        release=ReleaseDecision(doc_id="award-news-02", status=ReleaseStatus.RELEASED,
                                reason="All verification checks passed.", remediation_rounds=0),
    ))

    # --- 3. Support ticket: blocked -----------------------------------------------------
    _, ents, risks, decs = build_doc("support-ticket-03", [
        "Ticket from the only ", E("night-shift charge nurse", "[OCCUPATION]", EntityType.OCCUPATION,
                                   Strategy.MASK, RiskLevel.HIGH, Q, "POL-OCCUPATION",
                                   "Rare role combined with employer and age is unique.",
                                   rules=("QI-AGE-OCC", "QI-ORG-OCC"), base_risk=RiskLevel.LOW),
        " at ", E("Lakeview Demo Hospital", "[ORGANIZATION]", EntityType.ORGANIZATION, Strategy.MASK,
                  RiskLevel.HIGH, Q, "POL-ORG", "Employer links this ticket to the HR record.",
                  cluster_id="c-org-01", rules=("QI-ORG-OCC",), base_risk=RiskLevel.LOW),
        ", aged ", E("34", "30-39", EntityType.AGE, Strategy.GENERALIZE, RiskLevel.HIGH, Q, "POL-AGE",
                     "Age band still narrows to one person here.", rules=("QI-AGE-OCC",),
                     base_risk=RiskLevel.LOW),
        ", reporting a ", E("migraine condition", "[MEDICAL_CONDITION]", EntityType.MEDICAL_CONDITION,
                            Strategy.MASK, RiskLevel.CRITICAL, S, "POL-MEDICAL",
                            "Health information is a sensitive attribute."),
        ". Reply to ", E("charge.nurse@example.com", "[EMAIL_ADDRESS]", EntityType.EMAIL_ADDRESS,
                         Strategy.MASK, RiskLevel.HIGH, D, "POL-EMAIL", "Email is a direct identifier."),
        ".",
    ])
    qi = Finding(
        finding_type=FindingType.QUASI_IDENTIFIER_COMBINATION, severity=Severity.BLOCKING,
        doc_id="support-ticket-03",
        description="Occupation, employer and age band together match a single person (k=1).",
        entity_ids=["support-ticket-03:e01", "support-ticket-03:e02", "support-ticket-03:e03"],
        recommended_strategy=Strategy.SUPPRESS, rule_id="V-QI-K",
    )
    docs.append(SanitizedDocument(
        doc_id="support-ticket-03", released=False, redacted_text=None,
        entities=ents, risks=risks, decisions=decs,
        verification=VerificationReport(
            doc_id="support-ticket-03", revision=2, passed=False, checks_run=CHECKS,
            utility_retained=0.52, findings=[qi],
        ),
        release=ReleaseDecision(
            doc_id="support-ticket-03", status=ReleaseStatus.BLOCKED,
            reason="Blocked: a quasi-identifier combination stayed unique after 2 remediation rounds.",
            remediation_rounds=2,
        ),
    ))

    adversarial = AdversarialReport(
        revision=2, safe_to_release=False,
        findings=[Finding(
            finding_type=FindingType.CROSS_DOCUMENT_LINKAGE, severity=Severity.BLOCKING,
            doc_id="support-ticket-03", related_doc_ids=["hr-record-01"],
            description="The same employer and occupation link this ticket to the HR record.",
            entity_type=EntityType.ORGANIZATION, rule_id="A-LINKAGE",
        )],
        components=[LinkageComponent(
            component_id="lc-01", doc_ids=["hr-record-01", "support-ticket-03"],
            linked_by=["ORGANIZATION", "OCCUPATION"],
            visible_quasi_types=["AGE", "LOCATION"], anonymity_set_size=1, risk="high",
        )],
    )

    return BatchResult(batch_id=BATCH_ID, documents=docs, adversarial=adversarial,
                       aggregate=_aggregate(docs, adversarial))


def _aggregate(docs: list[SanitizedDocument], adversarial: AdversarialReport) -> AggregateStatistics:
    findings = [f for d in docs if d.verification for f in d.verification.findings]
    findings += adversarial.findings
    released = sum(d.released for d in docs)
    return AggregateStatistics(
        document_count=len(docs), documents_released=released, documents_blocked=len(docs) - released,
        entities_by_type=dict(Counter(e.entity_type.value for d in docs for e in d.entities)),
        risks_by_level=dict(Counter(r.risk.value for d in docs for r in d.risks)),
        strategies=dict(Counter(x.strategy.value for d in docs for x in d.decisions)),
        findings_by_type=dict(Counter(f.finding_type.value for f in findings)),
        remediation_rounds=max(d.release.remediation_rounds for d in docs),
        llm_used=False,
    )


def render() -> str:
    return json.dumps(build_mock().model_dump(mode="json"), indent=2) + "\n"


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
