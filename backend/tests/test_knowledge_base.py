"""Knowledge base tests.

The KB is tested against tests/fixtures/kb_expected_decisions.json, which was written by
hand from the requirements - not derived from policies.json - so these tests can catch
the knowledge base being wrong, not merely being itself.

Case types: positive, negative, boundary, conflicting-rule.
"""

from __future__ import annotations

import copy

import pytest

from privacy_review.knowledge_base import (
    InvalidKnowledgeBase,
    IssueKind,
    KnowledgeBase,
    KnowledgeBaseDB,
    PolicyEngine,
    validate_knowledge_base,
)
from privacy_review.schemas import EntityType, IdentifierClass, RiskLevel, Strategy


def _mutated(kb_json: dict, fn) -> KnowledgeBase:
    data = copy.deepcopy(kb_json)
    fn(data)
    return KnowledgeBase.model_validate(data)


def _policy(data: dict, et: str) -> dict:
    return next(p for p in data["entity_policies"] if p["entity_type"] == et)


# =============================================================== schema & coverage

class TestSchemaAndCoverage:
    def test_shipped_kb_has_no_issues(self, kb):
        assert validate_knowledge_base(kb) == []

    def test_every_supported_type_has_a_policy(self, kb):
        missing = [et for et in EntityType if et != EntityType.UNKNOWN and kb.policy_for(et) is None]
        assert missing == []

    def test_every_policy_covers_all_risk_levels(self, kb):
        for p in kb.entity_policies:
            assert set(p.strategy_by_risk) == set(RiskLevel), p.entity_type

    def test_schema_rejects_unknown_strategy(self, kb_json):
        with pytest.raises(Exception):
            _mutated(kb_json, lambda d: _policy(d, "EMAIL_ADDRESS").update(default_strategy="obfuscate"))

    def test_schema_rejects_missing_risk_level(self, kb_json):
        with pytest.raises(Exception, match="missing levels"):
            _mutated(kb_json, lambda d: _policy(d, "AGE")["strategy_by_risk"].pop("critical"))

    def test_schema_rejects_unknown_entity_type(self, kb_json):
        with pytest.raises(Exception):
            _mutated(kb_json, lambda d: _policy(d, "AGE").update(entity_type="SHOE_SIZE"))


# =============================================================== expected values (independent file)

class TestAgainstExpectedFile:
    def test_sensitivity_levels(self, engine, kb_expected):
        wrong = {et: (engine.sensitivity(EntityType(et)).value, exp)
                 for et, exp in kb_expected["sensitivity"].items()
                 if engine.sensitivity(EntityType(et)).value != exp}
        assert wrong == {}, f"(actual, expected): {wrong}"

    def test_identifier_classes(self, engine, kb_expected):
        wrong = {et: (engine.identifier_class(EntityType(et)).value, exp)
                 for et, exp in kb_expected["identifier_class"].items()
                 if engine.identifier_class(EntityType(et)).value != exp}
        assert wrong == {}

    @pytest.mark.parametrize("idx", range(14))
    def test_positive_decisions(self, engine, kb_expected, idx):
        case = kb_expected["positive_decisions"][idx]
        got = engine.strategy_for(EntityType(case["entity_type"]), RiskLevel(case["risk"]))
        assert got.value == case["expected"], case["case"]

    def test_positive_case_count_matches(self, kb_expected):
        assert len(kb_expected["positive_decisions"]) == 14   # keep parametrize range honest

    def test_never_allowed_strategies_are_rejected(self, engine, kb_expected):
        leaks = [c for c in kb_expected["never_allowed"]
                 if engine.is_compliant(EntityType(c["entity_type"]), Strategy(c["strategy"]))]
        assert leaks == []


# =============================================================== negative & boundary

class TestBoundaries:
    def test_unsupported_type_fails_closed(self, engine):
        assert engine.is_supported(EntityType.UNKNOWN) is False
        for lvl in RiskLevel:
            assert engine.strategy_for(EntityType.UNKNOWN, lvl) == Strategy.SUPPRESS
        assert engine.identifier_class(EntityType.UNKNOWN) == IdentifierClass.DIRECT
        assert engine.verification_required(EntityType.UNKNOWN) is True

    def test_strategy_never_weakens_as_risk_rises(self, engine):
        order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        for et in engine.db.entity_types():
            strengths = [engine.strategy_for(et, r).strength for r in order]
            assert strengths == sorted(strengths), et

    def test_escalate_is_strictly_stronger_or_stays(self, engine):
        for et in engine.db.entity_types():
            for s in engine.allowed(et):
                nxt = engine.escalate(et, s)
                assert nxt.strength >= s.strength
                assert engine.is_compliant(et, nxt)

    def test_escalate_at_strongest_strategy_is_a_fixed_point(self, engine):
        assert engine.escalate(EntityType.GOVERNMENT_ID, Strategy.SUPPRESS) == Strategy.SUPPRESS

    def test_critical_always_removes_more_than_low_for_direct_identifiers(self, engine):
        for et in engine.db.entity_types():
            if engine.identifier_class(et) == IdentifierClass.DIRECT:
                assert engine.strategy_for(et, RiskLevel.CRITICAL) == Strategy.SUPPRESS, et


# =============================================================== conflicting-rule detection

class TestConflictDetection:
    """Each case breaks the KB in one specific way; the validator must name exactly that."""

    @pytest.mark.parametrize("mutation,expected_kind", [
        (lambda d: d["entity_policies"].append(copy.deepcopy(_policy(d, "EMAIL_ADDRESS"))), IssueKind.DUPLICATE_POLICY),
        (lambda d: d["entity_policies"].remove(_policy(d, "PHONE_NUMBER")), IssueKind.MISSING_POLICY),
        (lambda d: _policy(d, "PHONE_NUMBER").update(default_strategy="pseudonymize"), IssueKind.DEFAULT_NOT_ALLOWED),
        (lambda d: _policy(d, "PHONE_NUMBER")["strategy_by_risk"].update(high="generalize"), IssueKind.RISK_STRATEGY_NOT_ALLOWED),
        (lambda d: _policy(d, "AGE")["strategy_by_risk"].update(critical="keep"), IssueKind.NON_MONOTONIC),
        (lambda d: _policy(d, "GOVERNMENT_ID")["allowed_strategies"].append("keep"), IssueKind.CONSTRAINT_CONFLICT),
        (lambda d: (_policy(d, "EMAIL_ADDRESS")["allowed_strategies"].append("keep"),
                    _policy(d, "EMAIL_ADDRESS")["strategy_by_risk"].update(low="keep")), IssueKind.DIRECT_IDENTIFIER_KEPT),
        (lambda d: d["context_rules"].append({**copy.deepcopy(d["context_rules"][1]), "rule_id": "CTX-99", "escalate_to": "low"}),
         IssueKind.CONTRADICTORY_CONTEXT_RULES),
        (lambda d: d["context_rules"].append(copy.deepcopy(d["context_rules"][0])), IssueKind.DUPLICATE_RULE_ID),
        (lambda d: d["linkage_rules"].update(medium_risk_threshold=0.9), IssueKind.THRESHOLD_ORDER),
        (lambda d: d["transformation_rules"]["generalization"].pop("AGE"), IssueKind.MISSING_GENERALIZATION),
        (lambda d: d["exceptions"].append({**d["exceptions"][0], "exception_id": "EXC-99", "entity_type": "PHONE_NUMBER"}),
         IssueKind.EXCEPTION_ON_PROTECTED),
        (lambda d: d["exceptions"][1]["unless_rules"].append("CTX-404"), IssueKind.RULE_REFERENCE),
        (lambda d: d["reference_data"]["role_nouns"].append("Engineer"), IssueKind.DUPLICATE_REFERENCE),
    ], ids=lambda x: x.value if isinstance(x, IssueKind) else "")
    def test_validator_reports_the_conflict(self, kb_json, mutation, expected_kind):
        broken = _mutated(kb_json, mutation)
        kinds = {i.kind for i in validate_knowledge_base(broken)}
        assert expected_kind in kinds, f"got {sorted(k.value for k in kinds)}"

    def test_strict_engine_refuses_a_conflicting_kb(self, kb_json):
        broken = _mutated(kb_json, lambda d: _policy(d, "AGE")["strategy_by_risk"].update(critical="keep"))
        with pytest.raises(InvalidKnowledgeBase, match="non_monotonic"):
            PolicyEngine(broken)


# =============================================================== JSON <-> SQLite consistency

class TestSqliteStore:
    def test_sqlite_agrees_with_json_for_every_type_and_level(self, kb):
        db = KnowledgeBaseDB().build(kb)
        for p in kb.entity_policies:
            for lvl, strat in p.strategy_by_risk.items():
                assert db.strategy_for(p.entity_type, lvl) == strat, (p.entity_type, lvl)
            assert db.allowed_strategies(p.entity_type) == set(p.allowed_strategies)

    def test_forbidden_strategies_queryable(self, kb):
        db = KnowledgeBaseDB().build(kb)
        assert Strategy.KEEP in db.forbidden_strategies(EntityType.GOVERNMENT_ID)
        assert db.forbidden_strategies(EntityType.LOCATION) == set()

    def test_rebuild_is_idempotent(self, kb):
        db = KnowledgeBaseDB().build(kb).build(kb)
        assert len(db.entity_types()) == len(kb.entity_policies)

    def test_file_backed_db_persists(self, kb, tmp_path):
        path = tmp_path / "kb.sqlite"
        KnowledgeBaseDB(path).build(kb).close()
        assert KnowledgeBaseDB(path).strategy_for(EntityType.EMAIL_ADDRESS, RiskLevel.HIGH) == Strategy.MASK

    def test_context_rules_indexed_by_target_type(self, kb):
        db = KnowledgeBaseDB().build(kb)
        assert "CTX-02" in db.context_rules_applying_to(EntityType.OCCUPATION)
        assert db.context_rules_applying_to(EntityType.EMAIL_ADDRESS) == []


# =============================================================== policy changes propagate

class TestPolicyChangesPropagate:
    def test_changing_json_changes_the_engines_decision(self, kb_json):
        def stricter_email(d):
            _policy(d, "EMAIL_ADDRESS")["strategy_by_risk"]["high"] = "suppress"
        before = PolicyEngine(KnowledgeBase.model_validate(kb_json))
        after = PolicyEngine(_mutated(kb_json, stricter_email))
        assert before.strategy_for(EntityType.EMAIL_ADDRESS, RiskLevel.HIGH) == Strategy.MASK
        assert after.strategy_for(EntityType.EMAIL_ADDRESS, RiskLevel.HIGH) == Strategy.SUPPRESS

    def test_raising_sensitivity_changes_risk(self, kb_json, entity_factory):
        after = PolicyEngine(_mutated(kb_json, lambda d: _policy(d, "LOCATION").update(sensitivity="medium")))
        e = entity_factory("LOCATION", 0)
        base, final, _ = after.assess(e, [e], after.context_escalations([e]))
        assert base == RiskLevel.MEDIUM


# =============================================================== context rules & exceptions

class TestContextRules:
    @pytest.mark.parametrize("idx", range(6))
    def test_combinations_trigger_expected_escalation(self, engine, kb_expected, entity_factory, idx):
        case = kb_expected["context_cases"][idx]
        ents = [entity_factory(et, s) for et, s in case["entities"]]
        esc = engine.context_escalations(ents)
        for e in ents:
            exp = case["expect"].get(e.entity_type.value)
            if not exp:
                continue
            _, final, rules = engine.assess(e, ents, esc)
            assert final.rank >= RiskLevel(exp["min_risk"]).rank, (case["case"], e.entity_type, final)
            assert exp["rule"] in rules, (case["case"], rules)

    @pytest.mark.parametrize("idx", range(4))
    def test_harmless_combinations_do_not_escalate(self, engine, kb_expected, entity_factory, idx):
        case = kb_expected["no_escalation_cases"][idx]
        ents = [entity_factory(et, s) for et, s in case["entities"]]
        esc = engine.context_escalations(ents)
        targets = [e for e in ents if e.entity_type.value == case.get("check_type", e.entity_type.value)]
        for e in targets:
            base, final, rules = engine.assess(e, ents, esc)
            assert final == base, (case["case"], e.entity_type, rules)

    @pytest.mark.parametrize("idx", range(3))
    def test_exceptions(self, engine, kb_expected, entity_factory, idx):
        case = kb_expected["exception_cases"][idx]
        ents = [entity_factory(et, s) for et, s in case["entities"]]
        esc = engine.context_escalations(ents)
        target = next(e for e in ents if e.entity_type.value == case["target"])
        _, final, rules = engine.assess(target, ents, esc)
        assert final.value == case["expected_final_risk"], (case["case"], rules)
        assert case["expected_rule"] in rules

    def test_escalation_takes_the_maximum_of_overlapping_rules(self, engine, entity_factory):
        ents = [entity_factory(t, 0) for t in ("PERSON", "OCCUPATION", "ORGANIZATION", "LOCATION")]
        esc = engine.context_escalations(ents)
        occ = next(e for e in ents if e.entity_type == EntityType.OCCUPATION)
        assert esc[occ.entity_id].escalate_to == RiskLevel.HIGH          # CTX-02 beats CTX-04
        assert {"CTX-02", "CTX-04"} <= set(esc[occ.entity_id].rule_ids)
