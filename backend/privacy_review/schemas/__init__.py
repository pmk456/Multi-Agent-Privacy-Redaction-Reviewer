"""Pydantic contracts between agents. Shared by every slice of the team."""

from privacy_review.schemas.documents import Annotation, Document
from privacy_review.schemas.entities import (
    AnnotationStatus,
    DetectedEntity,
    DetectionSource,
    EntityCluster,
    EntityLink,
    EntityType,
    IdentifierClass,
    PublicEntity,
    Span,
)
from privacy_review.schemas.outputs import AggregateStatistics, BatchResult, SanitizedDocument
from privacy_review.schemas.policy import (
    PseudonymScope,
    RedactionDecision,
    RiskAssessment,
    RiskLevel,
    Strategy,
)
from privacy_review.schemas.redaction import AppliedRedaction, RedactedDocument, Segment
from privacy_review.schemas.verification import (
    AdversarialReport,
    Finding,
    FindingType,
    LinkageComponent,
    ReleaseDecision,
    ReleaseStatus,
    Severity,
    VerificationReport,
)
