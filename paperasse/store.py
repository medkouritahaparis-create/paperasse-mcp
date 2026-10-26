"""SQLite storage and FTS5 (BM25) search over the parsed fiches.

Run `uv run python -m paperasse.store` to build data/paperasse.db from
data/fiches.jsonl (made by `python -m paperasse.ingest`).
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable

from paperasse.ingest import DATA_DIR, Fiche

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
                (cur.lastrowid, row["title"], row["summary"], " > ".join(row["breadcrumb"]), row["text"]),
            )
            count += 1
        conn.commit()
    finally:
        conn.close()
    tmp.replace(db_path)
    return count


def to_fts_query(query: str) -> str | None:
    """Turn a natural-language question into a safe FTS5 query.

    Words are quoted (so user input can't inject FTS syntax) and OR-ed, so a
    fiche doesn't need every word to match; BM25 ranks the best ones first.
    Words of 4+ letters get a prefix match to catch French plurals and
    variants ("allocation" -> "allocations"). Returns None if nothing is left.
    """
    words = [w.lower() for w in re.findall(r"\w+", query)]
    terms = []
    for w in words:
        if len(w) < 2 or w in STOPWORDS:
            continue
        term = f'"{w}"' + ("*" if len(w) >= 4 else "")
        if term not in terms:
            terms.append(term)
    return " OR ".join(terms) or None


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

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Best matching fiches for a question, most relevant first."""
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
        return [dict(r) for r in rows]

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
