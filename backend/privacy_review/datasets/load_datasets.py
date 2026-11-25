"""Download seeded samples from Hugging Face without pulling whole datasets.

Uses the dataset-viewer `/filter` endpoint, which returns pages of rows matching a SQL-ish
WHERE clause. We draw random page offsets with a fixed seed, so a given (seed, size) always
yields the same sample, and cache the result under data/raw/.

LICENSING - read before changing where these files go:
  * ai4privacy/pii-masking-200k: free licence for individuals and non-profits; prohibits
    redistributing derivative datasets. Never commit data/raw or data/processed.
  * piimb/pii-masking-benchmark: CC-BY-NC-4.0. Non-commercial use with attribution.
"""

from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

FILTER_URL = "https://datasets-server.huggingface.co/filter?"
PAGE = 20                                   # rows per request (API max is 100)

AI4PRIVACY = {"dataset": "ai4privacy/pii-masking-200k", "config": "default", "split": "train"}
PIIMB = {"dataset": "piimb/pii-masking-benchmark", "config": "full_text", "split": "test"}
# PIIMB's ai4privacy-en / ai4privacy-multi tasks come from the same generator family as our
# development data. Using them for "independent" evaluation would leak, so they are excluded.
PIIMB_TASKS = ("gretel", "nemotron-pii", "privy")


def _get(params: dict, tries: int = 5) -> dict:
    url = FILTER_URL + urllib.parse.urlencode(params)
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return json.load(r)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            wait = 2 ** attempt
            log.warning("dataset-viewer request failed (%s), retry %d/%d in %ds", e, attempt + 1, tries, wait)
            time.sleep(wait)
    raise RuntimeError(f"dataset-viewer unavailable after {tries} attempts")


def _sample_pages(base: dict, where: str, n: int, rng: random.Random) -> list[dict]:
    first = _get({**base, "where": where, "offset": 0, "length": 1})
    total = first["num_rows_total"]
    pages = max(1, -(-n // PAGE))
    starts = sorted(rng.sample(range(0, max(1, total - PAGE)), k=min(pages, max(1, total // PAGE))))
    rows: list[dict] = []
    for off in starts:
        page = _get({**base, "where": where, "offset": off, "length": PAGE})
        rows.extend({"_offset": off + i, **x["row"]} for i, x in enumerate(page["rows"]))
        if len(rows) >= n:
            break
    return rows[:n]


def load_ai4privacy(raw_dir: Path, n: int, seed: int, refresh: bool = False) -> list[dict]:
    path = raw_dir / f"ai4privacy_en_n{n}_seed{seed}.jsonl"
    if path.exists() and not refresh:
        return [json.loads(line) for line in path.read_text().splitlines()]
    rows = _sample_pages(AI4PRIVACY, "\"language\"='en'", n, random.Random(seed))
    _write(path, rows)
    return rows


def load_piimb(raw_dir: Path, n_per_task: int, seed: int, refresh: bool = False) -> list[dict]:
    path = raw_dir / f"piimb_en_{'-'.join(PIIMB_TASKS)}_n{n_per_task}_seed{seed}.jsonl"
    if path.exists() and not refresh:
        return [json.loads(line) for line in path.read_text().splitlines()]
    rng = random.Random(seed + 1)
    rows: list[dict] = []
    for task in PIIMB_TASKS:
        rows += _sample_pages(PIIMB, f"\"language\"='en' AND \"task_name\"='{task}'", n_per_task, rng)
    _write(path, rows)
    return rows


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    log.info("cached %d rows to %s", len(rows), path)
