"""SQLite storage and FTS5 (BM25) search over the parsed fiches.

Run `uv run python -m paperasse.store` to build data/paperasse.db from
data/fiches.jsonl (made by `python -m paperasse.ingest`).
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import unicodedata
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable

from paperasse import synonyms
from paperasse.ingest import AUDIENCES, DATA_DIR, Fiche, strip_links

DB_PATH = DATA_DIR / "paperasse.db"
JSONL_PATH = DATA_DIR / "fiches.jsonl"

# BM25 column weights, in FTS column order: a match in the title matters most.
FTS_COLUMNS = ("title", "summary", "breadcrumb", "text")
BM25_WEIGHTS = (10.0, 4.0, 2.0, 1.0)

# BM25 normalises for document length, which lets short Q&A fiches outrank the
# main guide on a topic (e.g. "Naturalisation : quels justificatifs… ?" above
# "Naturalisation française par décret"). The top RERANK_POOL BM25 hits are
# re-ranked by bm25 * (1 + LENGTH_PRIOR * ln(1 + text length)), which gives
# longer, more complete fiches a mild boost. Tuned on the eval: see docs/decisions.md.
LENGTH_PRIOR = 0.075
RERANK_POOL = 50

# Very common French words that only add noise to an OR query.
STOPWORDS = frozenset("""
a à au aux avec ce ces cet cette comme dans de des du elle en est et être il ils
je la le les leur leurs ma mais me mes mon ne nos notre nous on ou où par pas
pour qu que quel quelle quelles quels qui sa sans se ses si son sont sur ta te
tes ton tu un une vos votre vous y comment quoi quand combien faut faire puis
peut dois doit est-ce
""".split())

# A result is "low confidence" when the query words it contains in its title or
# summary, weighted by rarity (IDF), cover less than this share of the query.
# Chosen on labelled and off-topic queries: see docs/decisions.md.
MIN_CONFIDENT_MATCH = 0.5

# How synonyms (paperasse/synonyms.py) are used: "variants" runs one extra
# query per synonym and keeps each fiche's best score; "or" adds them to the
# same query; "off" ignores them. Chosen on the eval: see docs/decisions.md.
EXPANSION_MODE = "variants"

_SCHEMA = f"""
CREATE TABLE fiches (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    type TEXT NOT NULL,
    audiences TEXT NOT NULL,        -- JSON list: "particuliers", "professionnels"
    summary TEXT NOT NULL,
    text TEXT NOT NULL,
    url TEXT NOT NULL,              -- official page in the primary audience
    urls TEXT NOT NULL,             -- JSON {{audience: official page}}
    updated_at TEXT NOT NULL,
    important_update_at TEXT,
    theme TEXT,
    breadcrumb TEXT NOT NULL,       -- JSON list
    online_services TEXT NOT NULL,  -- JSON list of {{id, title, url}}
    sources TEXT NOT NULL,          -- JSON list of URLs
    text_len INTEGER NOT NULL       -- characters in text, for the length prior
);
CREATE VIRTUAL TABLE fiches_fts USING fts5(
    {", ".join(FTS_COLUMNS)},
    content='',
    tokenize='unicode61 remove_diacritics 2'
);
"""


def build_index(fiches: Iterable[Fiche | dict[str, Any]], db_path: Path = DB_PATH) -> int:
    """(Re)build the database from fiches. Returns the number of fiches indexed.

    Writes to a temporary file and swaps it in, so a running server never sees
    a half-built database.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(_SCHEMA)
        count = 0
        for f in fiches:
            row = asdict(f) if is_dataclass(f) else f
            cur = conn.execute(
                "INSERT INTO fiches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row["id"], row["title"], row["type"], json.dumps(row["audiences"]), row["summary"],
                    row["text"], row["url"], json.dumps(row["urls"]), row["updated_at"], row["important_update_at"],
                    row["theme"], json.dumps(row["breadcrumb"], ensure_ascii=False),
                    json.dumps(row["online_services"], ensure_ascii=False),
                    json.dumps(row["sources"], ensure_ascii=False),
                    len(row["text"]),
                ),
            )
            conn.execute(
                "INSERT INTO fiches_fts(rowid, title, summary, breadcrumb, text) VALUES (?,?,?,?,?)",
                # URLs would only add noise tokens ("https", "gouv"...) to the index.
                (cur.lastrowid, row["title"], row["summary"], " > ".join(row["breadcrumb"]), strip_links(row["text"])),
            )
            count += 1
        conn.commit()
    finally:
        conn.close()
    tmp.replace(db_path)
    return count


def _is_noise(word: str) -> bool:
    return len(word) < 2 or word in STOPWORDS


def query_terms(query: str) -> list[str]:
    """Meaningful words of a query, lowercased, deduplicated, stopwords removed.

    Hyphenated words stay one term ("micro-entrepreneur"), searched as a phrase:
    split in two, they would count twice and outweigh the rest of the query.
    Stopwords at their ends are dropped ("peuvent-ils" -> "peuvent", "a-t-on" -> nothing).
    """
    terms: list[str] = []
    for token in re.findall(r"\w+(?:-\w+)*", query.lower()):
        parts = token.split("-")
        while parts and _is_noise(parts[0]):
            parts.pop(0)
        while parts and _is_noise(parts[-1]):
            parts.pop()
        term = "-".join(parts)
        if term and term not in terms:
            terms.append(term)
    return terms


def _fts_term(term: str) -> str:
    # Words of 4+ letters get a prefix match to catch French plurals and
    # variants ("allocation" -> "allocations"). A hyphenated term is a phrase:
    # "micro-entrepreneur" matches "micro-entrepreneurs" but not "micro" alone.
    last = term.rsplit("-", 1)[-1]
    return '"' + term.replace("-", " ") + '"' + ("*" if len(last) >= 4 else "")


def _phrase(text: str) -> str:
    """Folded phrase as a hyphenated term: "Carte de séjour" -> "carte-de-sejour"."""
    return "-".join(re.findall(r"\w+", _fold(text)))


def expansions(query: str) -> list[tuple[str, list[str]]]:
    """Synonym rules (see paperasse/synonyms.py) whose phrase is in the query.

    Returns (phrase found, phrases to add), all folded and hyphenated.
    """
    if EXPANSION_MODE == "off":
        return []
    words = re.findall(r"\w+", _fold(query))
    return [
        (_phrase(key), [_phrase(s) for s in syns])
        for key, syns in synonyms.rules()
        if _contains(_phrase(key), words)
    ]


def _or_query(terms: list[str]) -> str | None:
    out: list[str] = []
    for t in terms:
        if _fold(t) not in out:
            out.append(_fold(t))
    return " OR ".join(_fts_term(t) for t in out) or None


def _covered(term: str, phrase: str) -> bool:
    """Whether a query term is part of a (folded, hyphenated) synonym phrase."""
    return set(_fold(term).split("-")) <= set(phrase.split("-"))


def to_fts_query(query: str) -> str | None:
    """Turn a natural-language question into a safe FTS5 query.

    Words are quoted (so user input can't inject FTS syntax) and OR-ed, so a
    fiche doesn't need every word to match; BM25 ranks the best ones first.
    In "or" expansion mode, synonyms are added to the same query. Returns None
    if nothing is left.
    """
    terms = query_terms(query)
    if EXPANSION_MODE == "or":
        terms += [t for _, added in expansions(query) for t in added]
    return _or_query(terms)


def fts_queries(query: str) -> list[str]:
    """The FTS5 queries to run for a question: the question itself first.

    In "variants" mode, each synonym gives one more query where the phrase is
    swapped for the synonym ("retraite auto-entrepreneur" -> "retraite
    micro-entrepreneur"). The user's own query always runs; a fiche keeps its
    best score across the queries, so a synonym can lift a fiche but never
    counts twice.
    """
    first = to_fts_query(query)
    if first is None:
        return []
    out = [first]
    if EXPANSION_MODE == "variants":
        terms = query_terms(query)
        for phrase, added in expansions(query):
            rest = [t for t in terms if not _covered(t, phrase)]
            for syn in added:
                q = _or_query(rest + [syn])
                if q and q not in out:
                    out.append(q)
    return out


def _fold(text: str) -> str:
    """Lowercase and drop accents, like the FTS tokenizer does ("Étudiant" -> "etudiant")."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def _contains(term: str, words: list[str]) -> bool:
    """Whether a (folded) query term is in a list of (folded) words, as _fts_term would match it."""
    parts = term.split("-")
    n, last = len(parts), parts[-1]
    for i in range(len(words) - n + 1):
        if words[i:i + n - 1] == parts[:-1] and (
            words[i + n - 1] == last or (len(last) >= 4 and words[i + n - 1].startswith(last))
        ):
            return True
    return False


def normalize_id(fiche_id: str) -> str:
    """'f10 ' -> 'F10'."""
    return fiche_id.strip().upper()


class FicheStore:
    """Read-only access to the fiche database."""

    def __init__(self, db_path: Path = DB_PATH):
        if not db_path.exists():
            raise FileNotFoundError(
                f"No fiche database at {db_path}. Build it with: "
                "uv run python -m paperasse.ingest && uv run python -m paperasse.store"
            )
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._idf_cache: dict[str, float] = {}

    def idf(self, term: str) -> float:
        """How rare a query word is across fiches (BM25's IDF; higher = rarer)."""
        if term not in self._idf_cache:
            n = self.count()
            df = self.conn.execute(
                "SELECT count(*) FROM fiches_fts WHERE fiches_fts MATCH ?", (_fts_term(term),)
            ).fetchone()[0]
            self._idf_cache[term] = math.log((n - df + 0.5) / (df + 0.5) + 1)
        return self._idf_cache[term]

    def match(self, query: str, title: str, summary: str) -> float:
        """Share of the query (weighted by word rarity) found in a result's title or summary.

        1.0 means every query word is there; near 0 means the result was only
        found through common words or its body text, so it may not be relevant.
        """
        terms = [_fold(t) for t in query_terms(query)]
        if not terms:
            return 0.0
        words = re.findall(r"\w+", _fold(f"{title} {summary}"))
        rules = expansions(query)
        weights = {t: self.idf(t) for t in terms}

        def found(term: str) -> bool:
            # A query word also counts as found through a synonym of a phrase it belongs to
            # ("auto-entrepreneur" in the query, "micro-entrepreneur" in the title).
            parts = set(term.split("-"))
            alternatives = [term] + [a for key, added in rules if parts <= set(key.split("-")) for a in added]
            return any(_contains(a, words) for a in alternatives)

        return sum(w for t, w in weights.items() if found(t)) / sum(weights.values())

    def search(self, query: str, limit: int = 5, audience: str = "all") -> list[dict[str, Any]]:
        """Best matching fiches for a question, most relevant first.

        `audience` is "particuliers", "professionnels" or "all". With one
        audience, only its fiches are searched and `url` is the fiche's page on
        that audience's site. Each result has a `match` score in [0, 1]: see `match()`.
        """
        if audience != "all" and audience not in AUDIENCES:
            raise ValueError(f"Unknown audience {audience!r}")
        weights = ", ".join(str(w) for w in BM25_WEIGHTS)
        best: dict[str, tuple[float, dict[str, Any]]] = {}
        for fts in fts_queries(query):
            for row in self.conn.execute(
                f"""
                SELECT f.id, f.title, f.summary, f.url, f.urls, f.audiences, f.updated_at, f.theme,
                       bm25(fiches_fts, {weights}) AS bm25, f.text_len
                FROM fiches_fts
                JOIN fiches f ON f.rowid = fiches_fts.rowid
                WHERE fiches_fts MATCH ? AND (? = 'all' OR f.audiences LIKE '%"' || ? || '"%')
                ORDER BY bm25
                LIMIT ?
                """,
                (fts, audience, audience, max(limit, RERANK_POOL)),
            ):
                # bm25() is negative, lower is better; the prior makes longer fiches more negative.
                key = row["bm25"] * (1 + LENGTH_PRIOR * math.log1p(row["text_len"]))
                if row["id"] not in best or key < best[row["id"]][0]:
                    best[row["id"]] = (key, dict(row))
        results = [r for _, r in sorted(best.values(), key=lambda kr: kr[0])[:limit]]
        for r in results:
            del r["bm25"], r["text_len"]
            urls = json.loads(r.pop("urls"))
            r["url"] = urls.get(audience, r["url"])
            r["audiences"] = json.loads(r["audiences"])
            r["match"] = round(self.match(query, r["title"], r["summary"]), 2)
        return results

    def get(self, fiche_id: str) -> dict[str, Any] | None:
        """Full fiche by ID, or None if it doesn't exist."""
        row = self.conn.execute("SELECT * FROM fiches WHERE id = ?", (normalize_id(fiche_id),)).fetchone()
        if row is None:
            return None
        fiche = dict(row)
        del fiche["text_len"]
        for key in ("audiences", "urls", "breadcrumb", "online_services", "sources"):
            fiche[key] = json.loads(fiche[key])
        return fiche

    def count(self) -> int:
        return self.conn.execute("SELECT count(*) FROM fiches").fetchone()[0]


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def main() -> None:
    if not JSONL_PATH.exists():
        raise SystemExit(f"{JSONL_PATH} not found. Run: uv run python -m paperasse.ingest")
    count = build_index(_read_jsonl(JSONL_PATH))
    print(f"Indexed {count} fiches into {DB_PATH}")


if __name__ == "__main__":
    main()
