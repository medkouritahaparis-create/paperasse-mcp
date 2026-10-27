"""Parse the service-public.fr XML feed (DILA, schema 3.5) into clean fiches.

There are two feeds with the same schema: *Particuliers* (service-public.gouv.fr)
and *Professionnels* (entreprendre.service-public.gouv.fr). Each is a zip of one
XML file per publication. Fiches (F*.xml) are the practical guides we serve.
About 100 fiches are in both feeds, with the same id and text but a page (URL)
on each site: they are merged into one fiche with both URLs. Their text is rendered to plain Markdown-like text
without rewording anything: we only drop markup and keep the structure
(headings, lists, tables, cases).

Run `uv run python -m paperasse.ingest` to download both feeds and write
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
# Audience -> feed. Order matters: for a fiche in both feeds, the first one's
# text and URL are the primary ones.
FEEDS = {
    "particuliers": f"https://lecomarquage.service-public.gouv.fr/vdd/{FEED_VERSION}/part/zip/vosdroits-latest.zip",
    "professionnels": f"https://lecomarquage.service-public.gouv.fr/vdd/{FEED_VERSION}/pro/zip/vosdroits-latest.zip",
}
AUDIENCES = tuple(FEEDS)
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
# Complement is a collapsible "En savoir plus si…" section on the website.
TITLED_BLOCKS = {"Chapitre", "SousChapitre", "Situation", "Cas", "Complement", "Conclusion"}
# Links to online services, offices or legal texts that appear inside the text.
LINK_BLOCKS = {
    "ServiceEnLigne", "ServiceEnLigneAnnexe", "NoticeLiee", "OuSAdresser",
    "PourEnSavoirPlus", "Reference",
}
# Callouts whose <Titre> ("À noter", "Attention"...) is a label, not a heading.
CALLOUTS = {"ANoter", "ASavoir", "Attention", "Rappel", "Exemple", "Avertissement"}

# Official page of a publication, by the audience it belongs to.
FICHE_URL_BASE = {
    "Particuliers": "https://www.service-public.gouv.fr/particuliers/vosdroits/",
    "Professionnels": "https://entreprendre.service-public.gouv.fr/vosdroits/",
}
# Inline links to these resource types have no page of their own (they 404).
NO_PAGE_LINK_TYPES = {"Sigle", "Acronyme", "Abréviation", "Définition de glossaire"}

# The source XML often repeats a whole block word for word, once per case
# (e.g. F827 repeats its "droit à l'erreur" section in all 6 cases). Blocks of
# these types, at least this long once rendered, are printed once; later copies
# become a pointer to the first one. Link blocks are not merged, so each case
# keeps its own "Title (URL)" line; only the text inside them can be.
DEDUP_TAGS = TITLED_BLOCKS | CALLOUTS | {"BlocCas", "Liste", "Tableau", "Paragraphe"}
DEDUP_MIN_CHARS = 200


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
    audiences: list[str]  # feeds the fiche is in: "particuliers", "professionnels"
    summary: str
    text: str
    url: str  # official page in the primary audience
    urls: dict[str, str]  # official page by audience (the same fiche has a page on each site)
    updated_at: str  # last update of the fiche (YYYY-MM-DD)
    important_update_at: str | None  # last *important* change, if the feed gives one
    theme: str | None
    breadcrumb: list[str] = field(default_factory=list)
    online_services: list[OnlineService] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _link_url(el: ET.Element) -> str | None:
    """URL of an inline link element, or None if it has no page to point to."""
    if el.tag == "LienExterne":
        return el.get("URL") or None
    if el.tag == "LienInterne":
        target = el.get("LienPublication") or ""
        base = FICHE_URL_BASE.get(el.get("audience") or "Particuliers")
        if base and target[:1] in ("F", "N", "R") and el.get("type") not in NO_PAGE_LINK_TYPES:
            return base + target
    return None


def _raw_text(el: ET.Element) -> str:
    parts = [el.text or ""]
    for child in el:
        if child.tag not in SKIPPED_TAGS:
            inner = _raw_text(child)
            url = _link_url(child)
            if url and inner.strip():
                # Keep surrounding spaces outside the brackets: "[le site](url) qui".
                lead = inner[: len(inner) - len(inner.lstrip())]
                trail = inner[len(inner.rstrip()) :]
                inner = f"{lead}[{_clean(inner)}]({url}){trail}"
            parts.append(inner)
        parts.append(child.tail or "")
    return "".join(parts)


_MD_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
_BARE_URL = re.compile(r" ?\(https?://[^)\s]+\)")


def strip_links(text: str) -> str:
    """Drop link URLs, keeping link text: for search indexing and text comparisons."""
    return _BARE_URL.sub("", _MD_LINK.sub(r"\1", text))


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
    summary = el.find("Resume")  # accessibility summary: "Ce tableau présente…"
    if summary is not None and _inline(summary):
        lines.append(_inline(summary))
    rows = el.findall("Rangée")
    for i, row in enumerate(rows):
        cells = [_inline(c).replace("|", "\\|") for c in row.findall("Cellule")]
        lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            lines.append("|" + " --- |" * len(cells))
    return lines


@dataclass
class _Render:
    """State shared across one fiche's rendering."""

    path: list[str] = field(default_factory=list)  # titles of the enclosing headings
    seen: dict[bytes, tuple[str, str]] = field(default_factory=dict)  # block XML -> (label, headings)


def _xml_key(el: ET.Element) -> bytes:
    tail, el.tail = el.tail, None
    try:
        return ET.tostring(el)
    finally:
        el.tail = tail


def _label(el: ET.Element, lines: list[str]) -> str:
    """Short name for a block in a repeat pointer: its title, or the start of its text."""
    title = strip_links(_title(el))
    if title:
        return title
    first = strip_links(lines[0]).lstrip("#-|0123456789. ").strip()
    return first if len(first) <= 60 else first[:60].rsplit(" ", 1)[0] + "…"


def _blocks(el: ET.Element, ctx: _Render, depth: int = 0, level: int = 2) -> list[str]:
    """Render a block element to a list of text lines.

    A block that repeats an earlier one word for word (same XML) is replaced by
    a pointer to the first copy, if it is long enough to be worth it.
    """
    if el.tag not in DEDUP_TAGS:
        return _render_block(el, ctx, depth, level)
    key = _xml_key(el)
    if key in ctx.seen:
        label, where = ctx.seen[key]
        lines = _render_block(el, _Render(path=list(ctx.path)), depth, level)
        if sum(map(len, lines)) >= DEDUP_MIN_CHARS:
            sous = f" (sous « {where} »)" if where else ""
            return [f"[Paperasse : identique à « {label} » plus haut{sous}.]"]
        return _render_block(el, ctx, depth, level)
    where = " > ".join(ctx.path[-2:])  # nearest headings of the first copy
    lines = _render_block(el, ctx, depth, level)
    if lines:
        ctx.seen[key] = (_label(el, lines), where)
    return lines


def _render_block(el: ET.Element, ctx: _Render, depth: int, level: int) -> list[str]:
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
            sub = [l for c in item for l in _blocks(c, ctx, depth + 1, level)]
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
        # Offices, services and references can carry their own text (addresses, notices, cases).
        for child in el:
            lines.extend(_blocks(child, ctx, depth, level))
        return lines

    lines: list[str] = []
    title = ""
    if tag in TITLED_BLOCKS:
        title = _title(el)
        if title:
            lines.append(f"{'#' * min(level, 6)} {title}")
            level += 1
            ctx.path.append(strip_links(title))
    elif tag in CALLOUTS:
        label = _title(el)
        body = [l for c in el for l in _blocks(c, ctx, depth, level)]
        if label and body:
            return [f"{label} : {body[0]}", *body[1:]]
        return body
    # Text written directly in a block, e.g. <Reference><Complement>texte</Complement>.
    if (el.text or "").strip():
        lines.append(_clean(el.text))
    for child in el:
        lines.extend(_blocks(child, ctx, depth, level))
    if title:
        ctx.path.pop()
    return lines


def _render_text(root: ET.Element) -> str:
    lines: list[str] = []
    ctx = _Render()
    for tag in ("Introduction", "Texte", "ListeSituations", "Conclusion"):
        for el in root.findall(tag):
            lines.extend(_blocks(el, ctx))
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


def parse_fiche(path: Path, audience: str = "particuliers") -> Fiche:
    """Parse one fiche from the feed of `audience` ("particuliers" or "professionnels")."""
    root = ET.parse(path).getroot()
    if root.tag != "Publication":
        raise ValueError(f"{path.name}: not a Publication")
    fid = root.get("ID") or ""
    # spUrl is the page on the site of this feed (a few pro fiches point to the particuliers site).
    url = root.get("spUrl") or FICHE_URL_BASE[audience.capitalize()] + fid
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
        audiences=[audience],
        summary=_clean(root.findtext(f"{DC}description") or ""),
        text=_render_text(root),
        url=url,
        urls={audience: url},
        updated_at=_updated_at(root),
        important_update_at=important[:10] if important else None,
        theme=_clean(root.findtext("Theme/Titre") or "") or None,
        breadcrumb=[_clean(n.text or "") for n in root.findall("FilDAriane/Niveau")],
        online_services=online,
        sources=sources,
    )


def iter_fiches(raw_dir: Path, audience: str = "particuliers") -> Iterator[Fiche]:
    """Yield every fiche (F*.xml) in one unzipped feed, sorted by ID."""
    for path in sorted(raw_dir.glob("F*.xml")):
        yield parse_fiche(path, audience)


def merge_feeds(feeds: dict[str, Iterator[Fiche]]) -> list[Fiche]:
    """One fiche per id across feeds, in feed order then id order.

    A fiche in several feeds has the same text in each (only its links point to
    the other site), so the first feed's version is kept and the others add
    their audience and page URL.
    """
    merged: dict[str, Fiche] = {}
    for audience, fiches in feeds.items():
        for f in fiches:
            if f.id in merged:
                merged[f.id].audiences.append(audience)
                merged[f.id].urls[audience] = f.url
            else:
                merged[f.id] = f
    return list(merged.values())


def raw_dir(audience: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / "raw" / audience


def download_feed(audience: str, data_dir: Path = DATA_DIR) -> Path:
    """Download and unzip the latest feed of an audience. Returns the directory of XML files."""
    data_dir.mkdir(parents=True, exist_ok=True)
    zip_path = data_dir / f"vosdroits-{audience}-latest.zip"
    raw_dir_ = raw_dir(audience, data_dir)
    with urllib.request.urlopen(FEEDS[audience], timeout=120) as resp, open(zip_path, "wb") as f:
        shutil.copyfileobj(resp, f)
    if raw_dir_.exists():
        shutil.rmtree(raw_dir_)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(raw_dir_)
    return raw_dir_


def main() -> None:
    if "--no-download" not in sys.argv:
        for audience, url in FEEDS.items():
            print(f"Downloading {url}")
            download_feed(audience)
    fiches = merge_feeds({a: iter_fiches(raw_dir(a), a) for a in AUDIENCES})
    out = DATA_DIR / "fiches.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for fiche in fiches:
            f.write(json.dumps(asdict(fiche), ensure_ascii=False) + "\n")
    counts = {a: sum(a in f.audiences for f in fiches) for a in AUDIENCES}
    print(f"Wrote {len(fiches)} fiches to {out} ({', '.join(f'{n} {a}' for a, n in counts.items())})")


if __name__ == "__main__":
    main()
