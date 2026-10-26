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

from paperasse.ingest import DATA_DIR, Fiche, strip_links

DB_PATH = DATA_DIR / "paperasse.db"
JSONL_PATH = DATA_DIR / "fiches.jsonl"

# BM25 column weights, in FTS column order: a match in the title matters most.
FTS_COLUMNS = ("title", "summary", "breadcrumb", "text")
BM25_WEIGHTS = (10.0, 4.0, 2.0, 1.0)

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

_SCHEMA = f"""
CREATE TABLE fiches (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    type TEXT NOT NULL,
    audience TEXT NOT NULL,
    summary TEXT NOT NULL,
    text TEXT NOT NULL,
    url TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    important_update_at TEXT,
    theme TEXT,
    breadcrumb TEXT NOT NULL,       -- JSON list
    online_services TEXT NOT NULL,  -- JSON list of {{id, title, url}}
    sources TEXT NOT NULL           -- JSON list of URLs
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
                "INSERT INTO fiches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row["id"], row["title"], row["type"], row["audience"], row["summary"],
                    row["text"], row["url"], row["updated_at"], row["important_update_at"],
                    row["theme"], json.dumps(row["breadcrumb"], ensure_ascii=False),
                    json.dumps(row["online_services"], ensure_ascii=False),
                    json.dumps(row["sources"], ensure_ascii=False),
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


def query_terms(query: str) -> list[str]:
    """Meaningful words of a query, lowercased, deduplicated, stopwords removed."""
    terms: list[str] = []
    for w in re.findall(r"\w+", query.lower()):
        if len(w) >= 2 and w not in STOPWORDS and w not in terms:
            terms.append(w)
    return terms


def _fts_term(term: str) -> str:
    # Words of 4+ letters get a prefix match to catch French plurals and
    # variants ("allocation" -> "allocations").
    return f'"{term}"' + ("*" if len(term) >= 4 else "")


def to_fts_query(query: str) -> str | None:
    """Turn a natural-language question into a safe FTS5 query.

    Words are quoted (so user input can't inject FTS syntax) and OR-ed, so a
    fiche doesn't need every word to match; BM25 ranks the best ones first.
    Returns None if nothing is left.
    """
    return " OR ".join(_fts_term(t) for t in query_terms(query)) or None


def _fold(text: str) -> str:
    """Lowercase and drop accents, like the FTS tokenizer does ("Étudiant" -> "etudiant")."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def _contains(term: str, words: set[str]) -> bool:
    return term in words or (len(term) >= 4 and any(w.startswith(term) for w in words))


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
        words = set(re.findall(r"\w+", _fold(f"{title} {summary}")))
        weights = {t: self.idf(t) for t in terms}
        found = sum(w for t, w in weights.items() if _contains(t, words))
        return found / sum(weights.values())

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Best matching fiches for a question, most relevant first.

        Each result has a `match` score in [0, 1]: see `match()`.
        """
        fts = to_fts_query(query)
        if fts is None:
            return []
        weights = ", ".join(str(w) for w in BM25_WEIGHTS)
        rows = self.conn.execute(
            f"""
            SELECT f.id, f.title, f.summary, f.url, f.updated_at, f.theme
            FROM fiches_fts
            JOIN fiches f ON f.rowid = fiches_fts.rowid
            WHERE fiches_fts MATCH ?
            ORDER BY bm25(fiches_fts, {weights})
            LIMIT ?
            """,
            (fts, limit),
        ).fetchall()
        results = [dict(r) for r in rows]
        for r in results:
            r["match"] = round(self.match(query, r["title"], r["summary"]), 2)
        return results

    def get(self, fiche_id: str) -> dict[str, Any] | None:
        """Full fiche by ID, or None if it doesn't exist."""
        row = self.conn.execute("SELECT * FROM fiches WHERE id = ?", (normalize_id(fiche_id),)).fetchone()
        if row is None:
            return None
        fiche = dict(row)
        for key in ("breadcrumb", "online_services", "sources"):
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
