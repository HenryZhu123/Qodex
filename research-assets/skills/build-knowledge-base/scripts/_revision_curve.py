"""How far does similarity fall when a revised edition changes X% of the text?

Takes the parsed 8th-edition text and replaces a fraction of its units with
unrelated textbook text, then reports the top-400 fingerprint Jaccard and the
chunk-level coverage. This gives the missing calibration point: a real revision
that touches only 5-10% of the book.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

SCRIPTS = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\skills\build-knowledge-base\scripts")
sys.path.insert(0, str(SCRIPTS))

from kb_registry import chunk_sha256, fingerprint_jaccard, term_fingerprint  # noqa: E402

BOOK = Path(r"D:\Code\hku\LLM\kb_review\books\computer_network_8th\parsed\bf0b7038334a1485.json")
FILLER = Path(r"D:\Code\hku\LLM\kb_review\books\computer_organization\chunks.jsonl")
SEED = 42


def main() -> None:
    units = [u["text"] for u in json.loads(BOOK.read_text(encoding="utf-8"))["units"] if u["text"].strip()]
    filler = [json.loads(line)["content"] for line in FILLER.read_text(encoding="utf-8").splitlines() if line.strip()]
    rng = random.Random(SEED)

    original_text = "".join(units)
    fp_original = term_fingerprint(original_text)
    hashes_original = {chunk_sha256(u) for u in units}

    print(f"units={len(units)} filler={len(filler)}")
    print(f"{'revised':>8} {'fingerprint':>12} {'chunk_coverage':>15}")
    for pct in (0, 1, 2, 5, 10, 20, 30):
        count = int(len(units) * pct / 100)
        replaced = set(rng.sample(range(len(units)), count)) if count else set()
        revised = [
            (rng.choice(filler) if index in replaced else unit)
            for index, unit in enumerate(units)
        ]
        text = "".join(revised)
        score = fingerprint_jaccard(fp_original, term_fingerprint(text))
        revised_hashes = {chunk_sha256(u) for u in revised}
        coverage = len(hashes_original & revised_hashes) / len(hashes_original)
        print(f"{pct:>7}% {score:>12.4f} {coverage:>15.4f}")


if __name__ == "__main__":
    main()
