"""Microsoft Presidio, configured once, sharing its spaCy pipeline with SpacyProcessor."""

from __future__ import annotations

import logging
from functools import lru_cache

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpArtifacts, NlpEngineProvider

from privacy_review.detection.candidates import Candidate
from privacy_review.schemas.entities import DetectionSource, EntityType as E

log = logging.getLogger(__name__)

PRESIDIO_TO_CANONICAL: dict[str, E] = {
    "PERSON": E.PERSON, "EMAIL_ADDRESS": E.EMAIL_ADDRESS, "EMAIL": E.EMAIL_ADDRESS,
    "PHONE_NUMBER": E.PHONE_NUMBER, "LOCATION": E.LOCATION, "DATE_TIME": E.DATE,
    "NRP": E.DEMOGRAPHIC, "ORGANIZATION": E.ORGANIZATION, "AGE": E.AGE,
    "CREDIT_CARD": E.FINANCIAL_ACCOUNT, "CRYPTO": E.FINANCIAL_ACCOUNT, "IBAN_CODE": E.FINANCIAL_ACCOUNT,
    "US_BANK_NUMBER": E.FINANCIAL_ACCOUNT,
    "US_SSN": E.GOVERNMENT_ID, "US_ITIN": E.GOVERNMENT_ID, "US_PASSPORT": E.GOVERNMENT_ID,
    "US_DRIVER_LICENSE": E.GOVERNMENT_ID, "UK_NHS": E.GOVERNMENT_ID, "MEDICAL_LICENSE": E.GOVERNMENT_ID,
    "IN_PAN": E.GOVERNMENT_ID, "IN_AADHAAR": E.GOVERNMENT_ID, "IN_PASSPORT": E.GOVERNMENT_ID,
    "IN_VOTER": E.GOVERNMENT_ID, "IN_VEHICLE_REGISTRATION": E.DEVICE_IDENTIFIER,
    "IP_ADDRESS": E.ONLINE_IDENTIFIER, "MAC_ADDRESS": E.ONLINE_IDENTIFIER,
    "URL": E.URL, "ID": E.RECORD_IDENTIFIER, "UUID": E.RECORD_IDENTIFIER,
}


@lru_cache(maxsize=2)
def build_analyzer(model_name: str) -> AnalyzerEngine:
    provider = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": model_name}],
    })
    engine = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])
    log.info("presidio analyzer ready (%d recognizers)", len(engine.registry.recognizers))
    return engine


class PresidioDetector:
    def __init__(self, model_name: str):
        self.engine = build_analyzer(model_name)

    @property
    def nlp(self):
        return self.engine.nlp_engine.nlp["en"]

    def process(self, text: str) -> NlpArtifacts:
        return self.engine.nlp_engine.process_text(text, "en")

    def candidates(self, text: str, artifacts: NlpArtifacts, threshold: float) -> list[Candidate]:
        out: list[Candidate] = []
        for r in self.engine.analyze(text=text, language="en", nlp_artifacts=artifacts, score_threshold=threshold):
            et = PRESIDIO_TO_CANONICAL.get(r.entity_type)
            if et is None:
                continue
            name = (r.recognition_metadata or {}).get("recognizer_name", r.entity_type)
            src = DetectionSource.SPACY if "Spacy" in name else DetectionSource.PRESIDIO
            out.append(Candidate(r.start, r.end, et, float(r.score), src, r.entity_type))
        return out
