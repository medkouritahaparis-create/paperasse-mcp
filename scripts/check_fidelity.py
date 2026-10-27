"""Check that every source <Paragraphe> of every fiche appears in the rendered text.

Paragraphs inside elements the renderer skips on purpose (images and videos,
credits, alternative titles, questionnaire logic: see SKIPPED_TAGS) are not
checked. Link URLs are ignored in the comparison. A paragraph inside a repeated
block counts as reproduced if its first copy is in the text.

Usage: uv run python -m scripts.check_fidelity [data/raw]  (checks both feeds by default)
"""

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

from paperasse.ingest import SKIPPED_TAGS, _inline, parse_fiche, strip_links

EXCLUDED_ANCESTORS = SKIPPED_TAGS
BODY_TAGS = ("Introduction", "Texte", "ListeSituations", "Conclusion")


def missing_paragraphs(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    text = strip_links(parse_fiche(path).text)
    parents = {c: p for p in root.iter() for c in p}
    missing = []
    for tag in BODY_TAGS:
        for top in root.findall(tag):
            for p in top.iter("Paragraphe"):
                e, skip = p, False
                while e in parents:
                    e = parents[e]
                    skip |= e.tag in EXCLUDED_ANCESTORS
                para = strip_links(_inline(p))
                if not skip and para and para not in text:
                    missing.append(para)
    return missing


def main() -> None:
    raw = Path(sys.argv[1] if len(sys.argv) > 1 else "data/raw")
    files = sorted(raw.rglob("F*.xml"))
    bad = {}
    for f in files:
        m = missing_paragraphs(f)
        if m:
            bad[str(f.relative_to(raw))] = m
    print(f"{len(files)} fiches checked, {len(bad)} with missing paragraphs, "
          f"{sum(map(len, bad.values()))} paragraphs missing")
    for name, m in list(bad.items())[:10]:
        print(f"  {name}: {m[0][:120]!r}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
