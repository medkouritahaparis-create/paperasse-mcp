"""Parse the service-public.fr XML feed (DILA, schema 3.5) into clean fiches.

The feed is a zip of one XML file per publication. Fiches (F*.xml) are the
practical guides we serve. Their text is rendered to plain Markdown-like text
without rewording anything: we only drop markup and keep the structure
(headings, lists, tables, cases).

Run `uv run python -m paperasse.ingest` to download the feed and write
data/fiches.jsonl.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET

FEED_VERSION = "3.5"
FEED_URL = f"https://lecomarquage.service-public.gouv.fr/vdd/{FEED_VERSION}/part/zip/vosdroits-latest.zip"
SOURCE_CREDIT = "Service-Public.gouv.fr / DILA, Licence Ouverte (Etalab)"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DC = "{http://purl.org/dc/elements/1.1/}"

# Elements that carry no user-facing text (questionnaire logic, metadata).
SKIPPED_TAGS = {
    "Questionnaire", "Condition", "SiSelectionne", "IntituleSiSelectionne",
    "Colonne", "TitreAlternatif", "Credits", "Legende", "TexteDeRemplacement",
    "Image", "ImageIllustration", "Video",
    # Link metadata: the URL is rendered with the link title instead.
    "Source", "PivotLocal", "RessourceWeb",
}
# Blocks whose own <Titre> is a heading for the content below it. Heading level
# follows nesting depth, since Situation/Cas can wrap Chapitre and vice versa.
TITLED_BLOCKS = {"Chapitre", "SousChapitre", "Situation", "Cas"}
# Links to online services or offices that appear inside the text.
LINK_BLOCKS = {"ServiceEnLigne", "ServiceEnLigneAnnexe", "NoticeLiee", "OuSAdresser"}
# Callouts whose <Titre> ("À noter", "Attention"...) is a label, not a heading.
CALLOUTS = {"ANoter", "ASavoir", "Attention", "Rappel", "Exemple", "Avertissement"}


@dataclass
class OnlineService:
    id: str
    title: str
    url: str


@dataclass
class Fiche:
    id: str
    title: str
    type: str
    audience: str
    summary: str
    text: str
    url: str
    updated_at: str  # last update of the fiche (YYYY-MM-DD)
    important_update_at: str | None  # last *important* change, if the feed gives one
    theme: str | None
    breadcrumb: list[str] = field(default_factory=list)
    online_services: list[OnlineService] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _raw_text(el: ET.Element) -> str:
    parts = [el.text or ""]
    for child in el:
        if child.tag not in SKIPPED_TAGS:
            parts.append(_raw_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _inline(el: ET.Element) -> str:
    """Flatten an inline element (Paragraphe, Titre...) to one line of text."""
    # Collapse whitespace only once at the end: inner spaces ("loger </Expression>ne") matter.
    return _clean(_raw_text(el))


def _title(el: ET.Element) -> str:
    """Title of a block, preferring <TitreRiche> (same text, better whitespace)."""
    rich = el.find("TitreRiche")
    if rich is not None:
        return _inline(rich)
    t = el.find("Titre")
    return _inline(t) if t is not None else ""


def _table(el: ET.Element) -> list[str]:
    lines = []
    caption = _title(el)
    if caption:
        lines.append(caption)
    rows = el.findall("Rangée")
    for i, row in enumerate(rows):
        cells = [_inline(c).replace("|", "\\|") for c in row.findall("Cellule")]
        lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            lines.append("|" + " --- |" * len(cells))
    return lines


def _blocks(el: ET.Element, depth: int = 0, level: int = 2) -> list[str]:
    """Render a block element to a list of text lines."""
    tag = el.tag
    if tag in SKIPPED_TAGS or tag in ("Titre", "TitreRiche"):
        return []
    if tag == "Paragraphe":
        text = _inline(el)
        return [text] if text else []
    if tag == "Liste":
        lines = []
        for n, item in enumerate(el.findall("Item"), start=1):
            bullet = f"{n}." if el.get("type") == "numero" else "-"
            sub = [l for c in item for l in _blocks(c, depth + 1, level)]
            if sub:
                lines.append(f"{'  ' * depth}{bullet} {sub[0]}")
                lines.extend(f"{'  ' * (depth + 1)}{l}" for l in sub[1:])
        return lines
    if tag == "Tableau":
        return _table(el)
    if tag in LINK_BLOCKS:
        title = _title(el)
        res = el.find("RessourceWeb")
        url = el.get("URL") or (res.get("URL", "") if res is not None else "")
        lines = [f"{title} ({url})" if url else title] if title else []
        # Offices and services can carry their own text (addresses, notices, cases).
        for child in el:
            lines.extend(_blocks(child, depth, level))
        return lines

    lines: list[str] = []
    if tag in TITLED_BLOCKS:
        title = _title(el)
        if title:
            lines.append(f"{'#' * min(level, 6)} {title}")
            level += 1
    elif tag in CALLOUTS:
        label = _title(el)
        body = [l for c in el for l in _blocks(c, depth, level)]
        if label and body:
            return [f"{label} : {body[0]}", *body[1:]]
        return body
    for child in el:
        lines.extend(_blocks(child, depth, level))
    return lines


def _render_text(root: ET.Element) -> str:
    lines: list[str] = []
    for tag in ("Introduction", "Texte", "ListeSituations", "Conclusion"):
        for el in root.findall(tag):
            lines.extend(_blocks(el))
    # Blank line between blocks, except inside list runs.
    out: list[str] = []
    for line in lines:
        if out and not (line.lstrip().startswith(("-", "|")) or re.match(r"\s*\d+\.", line)):
            out.append("")
        out.append(line)
    return "\n".join(out).strip()


def _updated_at(root: ET.Element) -> str:
    raw = root.findtext(f"{DC}date") or ""  # e.g. "modified 2026-09-28"
    m = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    if not m:
        raise ValueError(f"{root.get('ID')}: no update date in dc:date {raw!r}")
    return m.group(0)


def parse_fiche(path: Path) -> Fiche:
    root = ET.parse(path).getroot()
    if root.tag != "Publication":
        raise ValueError(f"{path.name}: not a Publication")
    fid = root.get("ID") or ""
    important = root.get("dateDerniereModificationImportante")
    sources = [s.strip() for s in (root.findtext(f"{DC}source") or "").split(",") if s.strip()]
    online = [
        OnlineService(id=s.get("ID", ""), title=_inline(s.find("Titre")), url=s.get("URL", ""))
        for s in root.findall("ServiceEnLigne")
        if s.find("Titre") is not None and s.get("URL")
    ]
    return Fiche(
        id=fid,
        title=_clean(root.findtext(f"{DC}title") or ""),
        type=root.get("type") or "",
        audience=_clean(root.findtext("Audience") or ""),
        summary=_clean(root.findtext(f"{DC}description") or ""),
        text=_render_text(root),
        url=root.get("spUrl") or f"https://www.service-public.gouv.fr/particuliers/vosdroits/{fid}",
        updated_at=_updated_at(root),
        important_update_at=important[:10] if important else None,
        theme=_clean(root.findtext("Theme/Titre") or "") or None,
        breadcrumb=[_clean(n.text or "") for n in root.findall("FilDAriane/Niveau")],
        online_services=online,
        sources=sources,
    )


def iter_fiches(raw_dir: Path) -> Iterator[Fiche]:
    """Yield every fiche (F*.xml) in the unzipped feed, sorted by ID."""
    for path in sorted(raw_dir.glob("F*.xml")):
        yield parse_fiche(path)


def download_feed(data_dir: Path = DATA_DIR) -> Path:
    """Download and unzip the latest feed. Returns the directory of XML files."""
    data_dir.mkdir(parents=True, exist_ok=True)
    zip_path = data_dir / "vosdroits-latest.zip"
    raw_dir = data_dir / "raw"
    with urllib.request.urlopen(FEED_URL, timeout=120) as resp, open(zip_path, "wb") as f:
        shutil.copyfileobj(resp, f)
    if raw_dir.exists():
        shutil.rmtree(raw_dir)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(raw_dir)
    return raw_dir


def main() -> None:
    raw_dir = DATA_DIR / "raw"
    if "--no-download" not in sys.argv:
        print(f"Downloading {FEED_URL}")
        download_feed()
    out = DATA_DIR / "fiches.jsonl"
    count = 0
    with open(out, "w", encoding="utf-8") as f:
        for fiche in iter_fiches(raw_dir):
            f.write(json.dumps(asdict(fiche), ensure_ascii=False) + "\n")
            count += 1
    print(f"Wrote {count} fiches to {out}")


if __name__ == "__main__":
    main()
