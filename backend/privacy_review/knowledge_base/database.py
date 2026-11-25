"""SQLite storage for the knowledge base.

JSON is the authoring format (reviewable in a pull request); SQLite is what agents query
at runtime. `build()` is idempotent and the tests check the two stay in agreement.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from privacy_review.knowledge_base.schema import KnowledgeBase
from privacy_review.schemas.entities import EntityType
from privacy_review.schemas.policy import RiskLevel, Strategy

_DDL = """
CREATE TABLE kb_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE entity_policies (
    entity_type TEXT PRIMARY KEY, identifier_class TEXT NOT NULL, sensitivity TEXT NOT NULL,
    default_strategy TEXT NOT NULL, verification_required INTEGER NOT NULL,
    pseudonym_scope TEXT, risk_rules TEXT NOT NULL);
CREATE TABLE allowed_strategies (
    entity_type TEXT NOT NULL REFERENCES entity_policies(entity_type), strategy TEXT NOT NULL,
    PRIMARY KEY (entity_type, strategy));
CREATE TABLE strategy_by_risk (
    entity_type TEXT NOT NULL REFERENCES entity_policies(entity_type), risk_level TEXT NOT NULL,
    strategy TEXT NOT NULL, PRIMARY KEY (entity_type, risk_level));
CREATE TABLE context_rules (
    rule_id TEXT PRIMARY KEY, name TEXT NOT NULL, scope TEXT NOT NULL,
    min_distinct_types INTEGER NOT NULL, escalate_to TEXT NOT NULL, description TEXT NOT NULL);
CREATE TABLE context_rule_types (
    rule_id TEXT NOT NULL REFERENCES context_rules(rule_id),
    role TEXT NOT NULL CHECK (role IN ('trigger', 'requires', 'applies')),
    entity_type TEXT NOT NULL);
CREATE TABLE verification_rules (
    rule_id TEXT PRIMARY KEY, check_name TEXT NOT NULL, severity TEXT,
    severity_direct TEXT, severity_indirect TEXT, description TEXT NOT NULL);
CREATE TABLE policy_constraints (
    constraint_id TEXT NOT NULL, entity_type TEXT NOT NULL, forbidden_strategy TEXT NOT NULL,
    reason TEXT NOT NULL, PRIMARY KEY (constraint_id, entity_type, forbidden_strategy));
CREATE TABLE policy_exceptions (
    exception_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, condition TEXT NOT NULL,
    effect TEXT NOT NULL, value TEXT NOT NULL, unless_rules TEXT NOT NULL, description TEXT NOT NULL);
CREATE TABLE linkage_weights (
    entity_type TEXT PRIMARY KEY, specific REAL NOT NULL, generalized REAL NOT NULL);
CREATE INDEX idx_crt_type ON context_rule_types(entity_type);
"""


class KnowledgeBaseDB:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    # ------------------------------------------------------------------ build
    def build(self, kb: KnowledgeBase) -> "KnowledgeBaseDB":
        cur = self.conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF")          # drop order must not matter on rebuild
        for (name,) in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            cur.execute(f"DROP TABLE IF EXISTS {name}")
        cur.executescript(_DDL)
        cur.execute("PRAGMA foreign_keys = ON")

        cur.executemany("INSERT INTO kb_meta VALUES (?, ?)", [
            ("version", kb.version),
            ("unsupported_entity_risk", kb.defaults.unsupported_entity_risk.value),
            ("unsupported_entity_strategy", kb.defaults.unsupported_entity_strategy.value),
            ("default_pseudonym_scope", kb.defaults.default_pseudonym_scope.value),
            ("max_remediation_rounds", str(kb.defaults.max_remediation_rounds)),
            ("min_utility_retained", str(kb.defaults.min_utility_retained)),
        ])
        for p in kb.entity_policies:
            et = p.entity_type.value
            cur.execute("INSERT INTO entity_policies VALUES (?,?,?,?,?,?,?)", (
                et, p.identifier_class.value, p.sensitivity.value, p.default_strategy.value,
                int(p.verification_required), p.pseudonym_scope.value if p.pseudonym_scope else None,
                json.dumps(p.risk_rules)))
            cur.executemany("INSERT INTO allowed_strategies VALUES (?,?)",
                            [(et, s.value) for s in dict.fromkeys(p.allowed_strategies)])
            cur.executemany("INSERT INTO strategy_by_risk VALUES (?,?,?)",
                            [(et, lvl.value, s.value) for lvl, s in p.strategy_by_risk.items()])
        for r in kb.context_rules:
            cur.execute("INSERT INTO context_rules VALUES (?,?,?,?,?,?)",
                        (r.rule_id, r.name, r.scope, r.min_distinct_types, r.escalate_to.value, r.description))
            rows = [(r.rule_id, "trigger", t.value) for t in r.trigger_types] \
                 + [(r.rule_id, "requires", t.value) for t in r.requires_all] \
                 + [(r.rule_id, "applies", t.value) for t in r.applies_to]
            cur.executemany("INSERT INTO context_rule_types VALUES (?,?,?)", rows)
        for v in kb.verification_rules:
            cur.execute("INSERT INTO verification_rules VALUES (?,?,?,?,?,?)",
                        (v.rule_id, v.check, v.severity, v.severity_direct, v.severity_indirect, v.description))
        for c in kb.policy_constraints:
            cur.executemany("INSERT OR IGNORE INTO policy_constraints VALUES (?,?,?,?)",
                            [(c.constraint_id, et.value, s.value, c.reason)
                             for et in c.entity_types for s in c.forbidden_strategies])
        for e in kb.exceptions:
            cur.execute("INSERT INTO policy_exceptions VALUES (?,?,?,?,?,?,?)",
                        (e.exception_id, e.entity_type.value, e.condition, e.effect, e.value.value,
                         json.dumps(e.unless_rules), e.description))
        cur.executemany("INSERT INTO linkage_weights VALUES (?,?,?)",
                        [(et.value, w.specific, w.generalized) for et, w in kb.linkage_rules.specificity_weights.items()])
        self.conn.commit()
        return self

    # ------------------------------------------------------------------ queries
    def meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM kb_meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def has_policy(self, et: EntityType) -> bool:
        return self.conn.execute("SELECT 1 FROM entity_policies WHERE entity_type = ?", (et.value,)).fetchone() is not None

    def policy_row(self, et: EntityType) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM entity_policies WHERE entity_type = ?", (et.value,)).fetchone()

    def strategy_for(self, et: EntityType, risk: RiskLevel) -> Strategy | None:
        row = self.conn.execute(
            "SELECT strategy FROM strategy_by_risk WHERE entity_type = ? AND risk_level = ?",
            (et.value, risk.value)).fetchone()
        return Strategy(row["strategy"]) if row else None

    def allowed_strategies(self, et: EntityType) -> set[Strategy]:
        rows = self.conn.execute("SELECT strategy FROM allowed_strategies WHERE entity_type = ?", (et.value,))
        return {Strategy(r["strategy"]) for r in rows}

    def forbidden_strategies(self, et: EntityType) -> set[Strategy]:
        rows = self.conn.execute("SELECT forbidden_strategy FROM policy_constraints WHERE entity_type = ?", (et.value,))
        return {Strategy(r["forbidden_strategy"]) for r in rows}

    def context_rules_applying_to(self, et: EntityType) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT rule_id FROM context_rule_types WHERE role = 'applies' AND entity_type = ? ORDER BY rule_id",
            (et.value,))
        return [r["rule_id"] for r in rows]

    def exceptions_for(self, et: EntityType) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM policy_exceptions WHERE entity_type = ?", (et.value,)))

    def entity_types(self) -> list[EntityType]:
        return [EntityType(r["entity_type"]) for r in self.conn.execute("SELECT entity_type FROM entity_policies")]

    def close(self) -> None:
        self.conn.close()
