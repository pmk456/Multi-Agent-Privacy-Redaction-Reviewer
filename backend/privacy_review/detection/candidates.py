"""A raw detection before overlap resolution. Holds offsets only - never the text."""

from __future__ import annotations

from dataclasses import dataclass, field

from privacy_review.schemas.entities import DetectionSource, EntityType

# When two different types overlap with equal length, the more specific detector wins.
SPECIFICITY = {
    EntityType.EMAIL_ADDRESS: 10, EntityType.URL: 9, EntityType.CREDENTIAL: 9,
    EntityType.FINANCIAL_ACCOUNT: 9, EntityType.GOVERNMENT_ID: 9, EntityType.RECORD_IDENTIFIER: 8,
    EntityType.DEVICE_IDENTIFIER: 8, EntityType.ONLINE_IDENTIFIER: 8, EntityType.GPS_COORDINATE: 8,
    EntityType.PHONE_NUMBER: 7, EntityType.STREET_ADDRESS: 7, EntityType.POSTAL_CODE: 6,
    EntityType.DATE_OF_BIRTH: 6, EntityType.MEDICAL_CONDITION: 6, EntityType.AGE: 5,
    EntityType.PERSON: 5, EntityType.OCCUPATION: 4, EntityType.ORGANIZATION: 4,
    EntityType.DATE: 3, EntityType.LOCATION: 3, EntityType.EVENT: 3, EntityType.DEMOGRAPHIC: 3,
    EntityType.UNKNOWN: 1,
}


@dataclass
class Candidate:
    start: int
    end: int
    entity_type: EntityType
    score: float
    source: DetectionSource
    label: str
    sources: set = field(default_factory=set)

    def __post_init__(self):
        self.sources = set(self.sources) | {self.source}

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, o: "Candidate") -> bool:
        return self.start < o.end and o.start < self.end

    def rank(self) -> tuple:
        # A confident, format-specific match (card code, URL, ID) beats a broader NER span
        # that happens to contain it ("CVV 847" tagged ORG by spaCy).
        specific = SPECIFICITY.get(self.entity_type, 0) >= 6 and self.score >= 0.6 \
            and self.sources != {DetectionSource.SPACY}
        return (specific, self.length, self.score, SPECIFICITY.get(self.entity_type, 0))
