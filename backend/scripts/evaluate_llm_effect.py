"""What does Claude add? Same documents, pipeline with and without LLM calls (budgeted).

    python scripts/evaluate_llm_effect.py --n 30        # <= 3 Haiku calls per document
"""
from __future__ import annotations
import argparse, json, sys, time, warnings
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1])); warnings.filterwarnings("ignore")
from privacy_review.config import get_settings  # noqa: E402
from privacy_review.datasets import prepare_dataset  # noqa: E402
from privacy_review.datasets.ground_truth import as_document  # noqa: E402
from privacy_review.evaluation.redaction_metrics import evaluate_runs  # noqa: E402
from privacy_review.knowledge_base import default_engine  # noqa: E402
from privacy_review.llm import ClaudeReasoner  # noqa: E402
from privacy_review.orchestration.graph import Pipeline  # noqa: E402
from privacy_review.orchestration.runner import run_pipeline  # noqa: E402

ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=30); args = ap.parse_args()
s = get_settings()
ex = [e for e in prepare_dataset.load(s.data_dir / "processed" / "ai4privacy.jsonl") if e.split == "validation"][: args.n]
out = {}
for label, enabled in (("without_llm", False), ("with_llm", True)):
    cfg = s.model_copy(update={"llm_enabled": enabled})
    reasoner = ClaudeReasoner(cfg)
    p = Pipeline(default_engine(), cfg, reasoner=reasoner)
    t0 = time.time()
    states = {e.example_id: run_pipeline([as_document(e, "raw")], pipeline=p) for e in ex}
    r = evaluate_runs(ex, states)
    out[label] = {"seconds": round(time.time() - t0, 1), "completeness": r["redaction_completeness"]["completeness"],
                  "never_keep_completeness": r["redaction_completeness"]["never_keep_types"]["completeness"],
                  "release_rate": r["end_to_end"]["release_rate"],
                  "utility": r["data_utility"]["mean_utility_retained_including_blocked"],
                  "docs_where_llm_used": sum(st.llm_used for st in states.values()),
                  "usage": reasoner.ledger.summary(), "model": cfg.llm_model}
u = out["with_llm"]["usage"]
out["estimated_cost_usd"] = round(u["input_tokens"] * 0.10e-6 + u["output_tokens"] * 0.50e-6, 5)   # Haiku 5.5 list price
out["documents"] = len(ex); out["kind"] = "LLM-based (qualitative effect, small sample)"
path = s.reports_dir / "llm_effect.json"; path.write_text(json.dumps(out, indent=2)); print(json.dumps(out, indent=1)); print("->", path)
