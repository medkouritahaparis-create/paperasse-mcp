# Paperasse MCP

## What this project is
An open-source MCP server that lets AI assistants (Claude and any MCP client) answer questions about French administrative procedures **using official sources only**, with a citable link for every answer.

The server does not reason or give advice. It finds and returns official content:
- **service-public.fr practical guides (fiches)**: downloaded from the open-data XML published by the DILA on data.gouv.fr
- **Légifrance law articles**: via the PISTE API (phase 2)
- **Local help points** (France Services, préfectures, mairies): via the open Service-Public.fr directory API (phase 2)

Owner: Taha Medkouri. Personal side project, built on personal time and equipment. Public portfolio project for Forward Deployed Engineer / Solutions Engineer roles, so code quality, tests, evals and the decision log matter as much as features.

## Current status
- Session 1: hello-world MCP server with a fake `search_fiche` tool (`main.py`).
- Session 2 (2026-10-26): roadmap step 1 done. `paperasse/ingest.py` downloads the feed (schema 3.5) and parses all 3,004 fiches into `data/fiches.jsonl`, with tests in `tests/test_ingest.py`.
- Session 2 (cont.): roadmap step 2 done. `paperasse/store.py` builds `data/paperasse.db` (SQLite FTS5, BM25), and `main.py` serves real `search_fiche` and paged `get_fiche`. Tests: `tests/test_store.py`, `tests/test_server.py`.
- Session 2 (cont.): roadmap step 3 started. `.mcp.json` registers the server for Claude Code. A scripted run of 29 real questions found the right fiche in the top 3 for 22/29; see `docs/manual-test-2026-10-26.md`. Key gaps: the *Entreprendre* feed (micro-entreprise/URSSAF) isn't ingested, and long main guides rank below short Q&A fiches.
- Review fixes (2026-10-26), 6 steps planned: (1) repeated text, (2) low-confidence warning, (3) eval set + runner, (4) ranking against the eval, (5) *Entreprendre* feed, (6) open-source hygiene.
  - Step 1 done: repeated blocks print once and later copies become `[Paperasse : identique à …]` pointers. Complement/Conclusion titles and inline link URLs are kept. Duplicated text went from 23.2% to 6.9%. Checks: `python -m scripts.dup_stats`, `python -m scripts.check_fidelity`.
  - Step 2 done: every `search_fiche` result has `match` (IDF-weighted share of the query in its title + summary). Responses have `low_confidence` + `hint` when the top match is below 0.5 (`MIN_CONFIDENT_MATCH`). That flags 11/13 bad queries and 2/26 good ones.
  - Step 3 done: `evals/questions.jsonl` (57 questions, labelled from fiche titles) and `evals/run.py`. Baseline (code 4e93a4c): keywords top-1 50% / top-3 85%; sentences 36% / 64%; all 44% / 75%, MRR 0.59. Report in `evals/results/2026-10-26-4e93a4c.md`, numbers in the README.
  - Step 4 done: the top 50 BM25 hits are re-ranked with a length prior (`LENGTH_PRIOR` = 0.075 in `store.py`). All: top-1 44% → 62%, top-3 75% → 79%, MRR 0.59 → 0.71. Every option tried, kept or rejected, is in `docs/decisions.md`. The `low_confidence` threshold stays at 0.5 (re-check after step 5).
- Next step: review step 5, ingesting the *Entreprendre* feed (audience `professionnels`).

## Stack
- Python 3.11+, managed with `uv`
- Official MCP Python SDK (`mcp[cli]` v2), using `MCPServer` (`from mcp.server.mcpserver import MCPServer`). In v2, `FastMCP` was renamed to `MCPServer`. Don't use `mcp.server.fastmcp`.
- Search: start with SQLite FTS5 (BM25). Consider embeddings only if evals show keyword search is not good enough
- Tests: `pytest`

## Commands
- Install deps: `uv sync`
- Run server: `uv run main.py`
- Inspect / test tools by hand: `uv run mcp dev main.py`
- Use in Claude Code: `.mcp.json` at the repo root registers the `paperasse` server (needs `data/paperasse.db`)
- Tests: `uv run pytest`
- Download feed + build `data/fiches.jsonl`: `uv run python -m paperasse.ingest` (add `--no-download` to reparse `data/raw/` only)
- Build search index `data/paperasse.db` from `data/fiches.jsonl`: `uv run python -m paperasse.store` (the server needs it)
- Search eval: `uv run python -m evals.run` (writes `evals/results/<date>-<search code commit>.md`; `--no-save` to only print). Run it before and after any change that affects search.
- Text quality checks (after re-ingesting): `uv run python -m scripts.dup_stats` (repeated text %), `uv run python -m scripts.check_fidelity` (every source paragraph reproduced)

## Target structure
```
paperasse-mcp/
├── main.py              # MCP server entry point, tool definitions only
├── paperasse/
│   ├── ingest.py        # parse service-public.fr XML → clean fiches
│   ├── store.py         # SQLite storage + FTS5 search index
│   ├── legifrance.py    # PISTE / Légifrance client (phase 2)
│   └── annuaire.py      # Service-Public.fr directory API client (phase 2)
├── data/                # downloaded XML + generated DB (git-ignored)
├── evals/               # question → expected fiche ID test set + runner
├── tests/
└── docs/decisions.md    # architecture decision log
```

## Tools (planned)
| Tool | Returns |
|---|---|
| `search_fiche(query, audience="particuliers", limit=5)` | Top matching fiches: id, title, short summary, URL, updated_at, `match`; plus `low_confidence` (+ `hint`) when the best match is weak |
| `get_fiche(id)` | Full fiche text, last update date, official URL |
| `get_procedure_steps(id)` | Structured steps and required documents, when present in the fiche |
| `get_legal_article(code, article)` | Article text + Légifrance URL (phase 2) |
| `find_local_help(postcode, type)` | Nearest France Services / préfecture / mairie (phase 2) |

## Rules
- **Every tool result must include the official source URL** and the fiche's last update date, so the assistant can cite it.
- Never invent or paraphrase official content inside the server: return the source text. Interpretation is the client's job.
- Tool docstrings are read by the model: write them clearly, say when to use the tool and what it returns.
- Return clear, useful errors (e.g. "no fiche found for this query, try broader terms") rather than empty results or stack traces.
- Data licence: Licence Ouverte (Etalab). Credit "Service-Public.gouv.fr / DILA" in the README and in tool output metadata. Always use the latest XML feed version (v3.3 was removed on 4 May 2026; current: 3.5, set in `FEED_VERSION` in `paperasse/ingest.py`).
- Never commit downloaded data, generated databases, API keys or PISTE credentials. Use `.env` (git-ignored) for secrets.
- No real personal data anywhere in the repo, including tests and evals.
- Not affiliated with the French administration: no government branding, and say so in the README.
- Log important architecture choices in `docs/decisions.md` (context, options, decision, why).

## Roadmap
1. Parse the XML into clean fiches (id, title, audience, text, steps, URL, updated_at) + tests
2. SQLite FTS5 index + real `search_fiche` and `get_fiche`
3. Test in Claude Code / Claude Desktop with real questions (CAF, URSSAF, impôts, titre de séjour)
4. Small eval set: ~50 questions → expected fiche IDs, measure top-1 / top-3 accuracy
5. `get_procedure_steps`
6. Légifrance (PISTE) + `find_local_help`
7. Host remotely so others can add it as a connector; README with eval results
