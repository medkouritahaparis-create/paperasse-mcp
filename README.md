# Paperasse MCP

An open-source [MCP](https://modelcontextprotocol.io) server that lets AI assistants answer questions about French administrative procedures **from official sources only**, with a citable link and last update date for every answer.

> **Status:** early development. Ingestion, keyword search (SQLite FTS5) and a search eval work. Ranking improvements are next.

## Quick start

```bash
uv sync
uv run python -m paperasse.ingest   # download the official feed and build data/fiches.jsonl
uv run python -m paperasse.store    # build the search index data/paperasse.db
uv run mcp dev main.py              # inspect the tools in the MCP Inspector
uv run pytest
```

## Tools

| Tool | What it does |
|---|---|
| `search_fiche(query, audience="particuliers", limit=5)` | Best matching service-public.fr fiches: id, title, summary, official URL, last update date and a `match` score. Says `low_confidence: true` when the best result probably doesn't answer the question |
| `get_fiche(id, offset=0)` | Full official text of a fiche, with URL, update date, online services and legal sources; long fiches come in pages |

## Search quality

Measured with [evals/questions.jsonl](evals/questions.jsonl): 57 questions with expected fiches labelled by hand from the fiche titles, not from search results. Current results, 2026-10-26 (search code `7f5f470`, 3,004 *Particuliers* fiches), with the first baseline (`4e93a4c`) in brackets:

| Questions | n | Top-1 | Top-3 | MRR@10 |
|---|---|---|---|---|
| Keywords, as clients are told to send them ("APL étudiant") | 26 | 77% (50%) | 85% (85%) | 0.82 (0.68) |
| Full sentences, sent as is ("Comment avoir un garant gratuit pour louer ?") | 22 | 45% (36%) | 73% (64%) | 0.59 (0.50) |
| All answerable | 48 | **62%** (44%) | **79%** (75%) | **0.71** (0.59) |

The gain comes from one change, a mild boost for longer fiches, so main guides outrank short Q&A spin-offs. Thirteen other ranking ideas were tried and rejected; see [docs/decisions.md](docs/decisions.md). Full reports: [current](evals/results/2026-10-26-7f5f470.md), [baseline](evals/results/2026-10-26-4e93a4c.md).

`low_confidence` is set on 8 of 9 questions that have no good answer (off-topic, English, freelancer topics not covered yet). It is also set on 7 of 30 questions whose rank-1 result is right (false alarms).

Reproduce:

```bash
uv run python -m evals.run
```

The official feed is updated daily, so numbers can move slightly with the data. Each report records the code commit and the data snapshot. The set is small, so treat one question as about 2 points.

## Data and licence

Content comes from **Service-Public.gouv.fr / DILA** (Direction de l'information légale et administrative), published as open data under the [Licence Ouverte / Etalab](https://www.etalab.gouv.fr/licence-ouverte-open-licence). Feed: [Fiches pratiques et ressources de Service-Public.gouv.fr Particuliers](https://www.data.gouv.fr/datasets/fiches-pratiques-et-ressources-de-service-public-gouv-fr-particuliers) (schema 3.5).

## Disclaimer

This project is **not affiliated with, endorsed by or operated by the French administration**. It returns official text but is not legal advice. Always check the linked official page.
