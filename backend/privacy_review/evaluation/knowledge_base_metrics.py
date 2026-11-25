"""Knowledge base coverage and rule accuracy, measured against the independent expected file."""

from __future__ import annotations

import json
from pathlib import Path

from privacy_review.datasets.label_maps import AI4PRIVACY, PIIMB_PRESIDIO_STYLE, PIIMB_SNAKE
from privacy_review.knowledge_base import PolicyEngine, validate_knowledge_base
from privacy_review.schemas.entities import EntityType
from privacy_review.schemas.policy import RiskLevel, Strategy


def evaluate_kb(engine: PolicyEngine, expected_path: Path) -> dict:
    exp = json.loads(expected_path.read_text())
    types = [t for t in EntityType if t != EntityType.UNKNOWN]
    covered = [t for t in types if engine.is_supported(t)]
    mapped = {v for table in (AI4PRIVACY, PIIMB_SNAKE, PIIMB_PRESIDIO_STYLE) for v in table.values() if v}
    checks = []
    for et, s in exp["sensitivity"].items():
        checks.append(engine.sensitivity(EntityType(et)).value == s)
    for et, c in exp["identifier_class"].items():
        checks.append(engine.identifier_class(EntityType(et)).value == c)
    for case in exp["positive_decisions"]:
        checks.append(engine.strategy_for(EntityType(case["entity_type"]), RiskLevel(case["risk"])).value == case["expected"])
    for case in exp["never_allowed"]:
        checks.append(not engine.is_compliant(EntityType(case["entity_type"]), Strategy(case["strategy"])))
    return {
        "policy_coverage": round(len(covered) / len(types), 4),
        "types_without_policy": [t.value for t in types if t not in covered],
        "dataset_label_targets_with_policy": round(sum(engine.is_supported(t) for t in mapped) / len(mapped), 4),
        "validation_issues": len(validate_knowledge_base(engine.kb)),
        "rule_accuracy_vs_expected_file": {"correct": sum(checks), "total": len(checks),
                                           "accuracy": round(sum(checks) / len(checks), 4)},
    }
