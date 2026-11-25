"""End-to-end evaluation of the five-agent pipeline. Counts and rates only.

    python scripts/evaluate_pipeline.py                 # ai4privacy test + PIIMB
    python scripts/evaluate_pipeline.py --limit 50      # quicker
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from privacy_review.config import get_settings  # noqa: E402
from privacy_review.datasets import prepare_dataset  # noqa: E402
from privacy_review.datasets.ground_truth import as_document  # noqa: E402
from privacy_review.evaluation.knowledge_base_metrics import evaluate_kb  # noqa: E402
from privacy_review.evaluation.redaction_metrics import evaluate_runs  # noqa: E402
from privacy_review.evaluation.verification_metrics import evaluate_verification  # noqa: E402
from privacy_review.orchestration.runner import default_pipeline, run_pipeline  # noqa: E402

SYNTHETIC = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "synthetic_cross_document.json"


def main() -> None:
    s = get_settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--llm", action="store_true", help="allow Claude calls (budgeted per batch). Off by default.")
    args = ap.parse_args()
    if args.llm:
        p = default_pipeline()
    else:   # hundreds of documents: never spend API calls unless explicitly asked
        from privacy_review.knowledge_base import default_engine
        from privacy_review.llm import ClaudeReasoner
        from privacy_review.orchestration.graph import Pipeline
        quiet = s.model_copy(update={"llm_enabled": False})
        p = Pipeline(default_engine(), quiet, reasoner=ClaudeReasoner(quiet))
    agents = (p.a1, p.a2, p.a3, p.a4, p.a5)
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "llm_reasoning": "deterministic path only (run with --llm to include budgeted Claude calls)",
              "results": {}}

    for name, split in (("ai4privacy", "test"), ("piimb", "external_test")):
        ex = [e for e in prepare_dataset.load(s.data_dir / "processed" / f"{name}.jsonl") if e.split == split][: args.limit]
        t0 = time.time()
        states = {e.example_id: run_pipeline([as_document(e, "raw")], batch_id=e.example_id[:20], pipeline=p) for e in ex}
        r = evaluate_runs(ex, states)
        r["seconds"] = round(time.time() - t0, 1)
        r["kind"] = "dataset-based"
        report["results"][f"pipeline_{name}_{split}"] = r

    val = [e for e in prepare_dataset.load(s.data_dir / "processed" / "ai4privacy.jsonl") if e.split == "validation"][: args.limit]
    v = evaluate_verification([(e.example_id, e.text) for e in val], agents, s.random_seed)
    v["kind"] = "deterministic fault injection on ai4privacy validation texts"
    report["results"]["verification_fault_injection"] = v

    kb = evaluate_kb(p.policy, Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "kb_expected_decisions.json")
    kb["kind"] = "deterministic rule-based"
    report["results"]["knowledge_base"] = kb

    report["results"]["adversarial_synthetic"] = (
        {"status": "pending", "reason": f"{SYNTHETIC.name} not present yet (being built on feature/synthetic-cross-document)"}
        if not SYNTHETIC.exists() else {"status": "fixture present - run scripts/evaluate_adversarial.py"})

    out = s.reports_dir / "pipeline_evaluation.json"
    out.write_text(json.dumps(report, indent=2))
    for k, r in report["results"].items():
        print(f"\n== {k}")
        print(json.dumps({kk: vv for kk, vv in r.items() if kk not in ("leaked_by_type",)}, indent=1)[:1400])
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
