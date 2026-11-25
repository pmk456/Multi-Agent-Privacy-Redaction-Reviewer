"""Evaluate Agent 1 against dataset ground truth. Reports counts and rates only.

    python scripts/evaluate_agent1.py --dataset ai4privacy --split dev
    python scripts/evaluate_agent1.py --dataset piimb               # independent evaluation
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from privacy_review.agents.privacy_intelligence import PrivacyIntelligenceAgent  # noqa: E402
from privacy_review.config import get_settings  # noqa: E402
from privacy_review.datasets import prepare_dataset  # noqa: E402
from privacy_review.datasets.ground_truth import as_document, corrupt_annotations  # noqa: E402
from privacy_review.evaluation.detection_metrics import evaluate_annotation_validation, evaluate_detection  # noqa: E402
from privacy_review.knowledge_base import default_engine  # noqa: E402


def main() -> None:
    s = get_settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=["ai4privacy", "piimb"], default="ai4privacy")
    ap.add_argument("--split", default=None)
    ap.add_argument("--corruption-rate", type=float, default=0.3)
    ap.add_argument("--no-annotation-eval", action="store_true")
    args = ap.parse_args()

    examples = prepare_dataset.load(s.data_dir / "processed" / f"{args.dataset}.jsonl")
    split = args.split or ("external_test" if args.dataset == "piimb" else "dev")
    examples = [e for e in examples if e.split == split]
    agent = PrivacyIntelligenceAgent(default_engine())

    t0 = time.time()
    preds = {}
    for ex in examples:                                      # raw mode: ground truth hidden
        preds[ex.example_id] = agent.run([as_document(ex, "raw")]).entities
    det = evaluate_detection(examples, preds)
    det["seconds"] = round(time.time() - t0, 1)
    if args.dataset == "piimb":
        det["by_task"] = {t: evaluate_detection([e for e in examples if e.task == t], preds)["privacy_coverage"]["recall"]
                          for t in sorted({e.task for e in examples})}

    report = {"dataset": args.dataset, "split": split, "mode": "raw_text", "detection": det}
    if not args.no_annotation_eval:
        rng = random.Random(s.random_seed)
        cases = []
        for ex in examples:
            doc, key = corrupt_annotations(ex, args.corruption_rate, rng)
            cases.append((ex, key, agent.run([doc])))
        report["annotation_validation"] = evaluate_annotation_validation(cases)
        report["annotation_validation"]["corruption_rate"] = args.corruption_rate

    out = s.reports_dir / f"agent1_{args.dataset}_{split}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    d = report["detection"]
    print(f"{args.dataset}/{split}: {d['examples']} examples, {d['gold_spans']} gold spans, {d['seconds']}s")
    for m in ("strict", "relaxed"):
        x = d["micro"][m]
        print(f"  {m:8} P={x['precision']:.3f} R={x['recall']:.3f} F1={x['f1']:.3f}  macro-F1={d['macro_f1'][m]:.3f}")
    pc = d["privacy_coverage"]
    print(f"  coverage R={pc['recall']:.3f} ({pc['covered']}/{pc['total']})  precision(any type)={pc['precision_any_type']:.3f}")
    print("  coverage by type:", {t: v["recall"] for t, v in pc["by_type"].items()})
    print("  worst labels:", {l: f"{v['covered']}/{v['total']}" for l, v in list(pc["by_original_label"].items())[:8]})
    if "by_task" in d:
        print("  coverage by PIIMB task:", d["by_task"])
    if "annotation_validation" in report:
        av = report["annotation_validation"]
        print("  annotation validation:", json.dumps(av["by_corruption"]))
        print("  span accuracy after validation:", av["span_level_accuracy_after_validation"],
              "| shifted spans repaired:", av["shifted_spans_repaired_to_cover_gold"])
    print(f"  -> {out}")


if __name__ == "__main__":
    main()
