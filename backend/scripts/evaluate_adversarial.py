"""Agent 5 (and Agent 2) on the synthetic cross-document dataset. Deterministic, no API calls."""
from __future__ import annotations
import json, sys, warnings
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1])); warnings.filterwarnings("ignore")
from privacy_review.config import get_settings  # noqa: E402
from privacy_review.evaluation.adversarial_metrics import evaluate_synthetic  # noqa: E402
from privacy_review.knowledge_base import default_engine  # noqa: E402
from privacy_review.llm import ClaudeReasoner  # noqa: E402
from privacy_review.orchestration.graph import Pipeline  # noqa: E402

s = get_settings().model_copy(update={"llm_enabled": False})
p = Pipeline(default_engine(), s, reasoner=ClaudeReasoner(s))
data = json.loads((Path(__file__).resolve().parents[1] / "tests/fixtures/synthetic_cross_document.json").read_text())
r = evaluate_synthetic(data, (p.a1, p.a2, p.a3, p.a4, p.a5))
out = s.reports_dir / "adversarial_synthetic.json"; out.write_text(json.dumps(r, indent=2))
print(json.dumps({k: v for k, v in r.items() if k != "agent5"} | {"agent5": {k: v for k, v in r["agent5"].items()}}, indent=1)); print("->", out)
