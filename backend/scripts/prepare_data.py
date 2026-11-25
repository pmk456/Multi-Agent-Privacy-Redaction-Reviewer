"""Download dataset samples, normalise, split. Writes to data/ (git-ignored).

    python scripts/prepare_data.py [--ai4privacy N] [--piimb-per-task N] [--seed S] [--refresh]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from privacy_review.config import get_settings  # noqa: E402
from privacy_review.datasets import load_datasets, prepare_dataset  # noqa: E402


def main() -> None:
    s = get_settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--ai4privacy", type=int, default=s.ai4privacy_sample_size)
    ap.add_argument("--piimb-per-task", type=int, default=s.piimb_sample_size // 3)
    ap.add_argument("--seed", type=int, default=s.random_seed)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    raw, proc = s.data_dir / "raw", s.data_dir / "processed"
    a_rows = load_datasets.load_ai4privacy(raw, args.ai4privacy, args.seed, args.refresh)
    p_rows = load_datasets.load_piimb(raw, args.piimb_per_task, args.seed, args.refresh)

    ai4p = prepare_dataset.split_examples(prepare_dataset.normalise_ai4privacy(a_rows), args.seed)
    piimb = prepare_dataset.normalise_piimb(p_rows)
    prepare_dataset.save(ai4p, proc / "ai4privacy.jsonl")
    prepare_dataset.save(piimb, proc / "piimb.jsonl")

    summary = {"ai4privacy": prepare_dataset.summarise(ai4p), "piimb": prepare_dataset.summarise(piimb),
               "seed": args.seed}
    (proc / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
