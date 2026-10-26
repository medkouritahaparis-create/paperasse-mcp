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
- Next step: roadmap step 2, the SQLite FTS5 index and real `search_fiche` / `get_fiche`.

## Stack
- Python 3.11+, managed with `uv`
- Official MCP Python SDK (`mcp[cli]` v2), using `MCPServer` (`from mcp.server.mcpserver import MCPServer`). In v2, `FastMCP` was renamed to `MCPServer`. Don't use `mcp.server.fastmcp`.
- Search: start with SQLite FTS5 (BM25). Consider embeddings only if evals show keyword search is not good enough
- Tests: `pytest`

## Commands
- Install deps: `uv sync`
- Run server: `uv run main.py`
- Inspect / test tools by hand: `uv run mcp dev main.py`
- Tests: `uv run pytest`
- Download feed + build `data/fiches.jsonl`: `uv run python -m paperasse.ingest` (add `--no-download` to reparse `data/raw/` only)

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
| `search_fiche(query, audience="particuliers")` | Top matching fiches: id, title, short summary, URL |
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
