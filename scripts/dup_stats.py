"""Measure paragraphs (>80 chars) repeated inside the same fiche in data/fiches.jsonl.

Link URLs and "[Paperasse : identique à …]" pointer lines are left out, so
numbers stay comparable before and after links were added to the text.

Usage: uv run python -m scripts.dup_stats [path/to/fiches.jsonl]
"""

import collections
import json
import sys
from pathlib import Path

from paperasse.ingest import strip_links

MIN_LEN = 80


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/fiches.jsonl")
    total = dup = 0
    fiches_with_dups = 0
    worst = []
    for line in open(path, encoding="utf-8"):
        f = json.loads(line)
        text = strip_links(f["text"])
        total += len(text)
        paras = [p.strip() for p in text.split("\n\n")]
        counts = collections.Counter(p for p in paras if len(p) > MIN_LEN and not p.startswith("[Paperasse"))
        d = sum(len(p) * (n - 1) for p, n in counts.items() if n > 1)
        dup += d
        if d:
            fiches_with_dups += 1
            worst.append((d, f["id"]))
    print(f"total chars: {total:,}")
    print(f"duplicated chars (paragraphs >{MIN_LEN} chars repeated in the same fiche): {dup:,} = {dup / total:.1%}")
    print(f"fiches with duplicates: {fiches_with_dups}")
    print("worst:", sorted(worst, reverse=True)[:5])


if __name__ == "__main__":
    main()
