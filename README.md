# Paperasse MCP

An open-source [MCP](https://modelcontextprotocol.io) server that lets AI assistants answer questions about French administrative procedures **from official sources only**, with a citable link and last update date for every answer. It covers the guides for individuals (service-public.gouv.fr) and for professionals and the self-employed (entreprendre.service-public.gouv.fr).

> **Status:** early development. Ingestion of both official feeds, keyword search (SQLite FTS5) and a search eval work.

## Quick start

```bash
uv sync
uv run python -m paperasse.ingest   # download both official feeds and build data/fiches.jsonl
uv run python -m paperasse.store    # build the search index data/paperasse.db
uv run mcp dev main.py              # inspect the tools in the MCP Inspector
uv run pytest
```

## Tools

| Tool | What it does |
|---|---|
| `search_fiche(query, audience="all", limit=5)` | Best matching fiches: id, title, summary, official URL, last update date and a `match` score. `audience` is `"all"`, `"particuliers"` (individuals) or `"professionnels"` (businesses, self-employed); the URL is the page on that audience's site. Says `low_confidence: true` when the best result probably doesn't answer the question |
| `get_fiche(id, offset=0)` | Full official text of a fiche, with its URL on each site, update date, online services and legal sources; long fiches come in pages |

## Search quality

Measured with [evals/questions.jsonl](evals/questions.jsonl): 67 questions with expected fiches labelled by hand from the fiche titles, not from search results. Current results, 2026-10-27 (search code `337d5a8`, 3,673 fiches from both feeds, default `audience="all"`):

| Questions | n | Top-1 | Top-3 | MRR@10 |
|---|---|---|---|---|
| Everyday procedures, keywords as clients are told to send them ("APL étudiant") | 26 | 77% | 85% | 0.82 |
| Everyday procedures, full sentences sent as is ("Comment avoir un garant gratuit pour louer ?") | 22 | 41% | 68% | 0.55 |
| Freelancers / micro-entrepreneurs (8 keywords, 5 sentences) | 13 | 23% | 31% | 0.33 |
| **All answerable** | 61 | **52%** | **67%** | **0.62** |

On the 48 everyday questions, the first baseline (`4e93a4c`) scored 44% top-1, 75% top-3 and MRR 0.59. A mild boost for longer fiches, so main guides outrank short Q&A spin-offs, brought that to 62% / 79% / 0.71 ([report](evals/results/2026-10-26-7f5f470.md)). Adding the business feed costs one question (60% / 77% / 0.69), because word statistics are now shared with business fiches. Freelancer questions are the weak spot: users say "auto-entrepreneur" where the official titles say "micro-entrepreneur". Every option tried is in [docs/decisions.md](docs/decisions.md). Reports: [current](evals/results/2026-10-27-337d5a8.md), [baseline](evals/results/2026-10-26-4e93a4c.md).

`low_confidence` is set on all 6 questions that have no good answer (off-topic, English). It is also set on 7 of 32 questions whose rank-1 result is right (false alarms).

Reproduce:

```bash
uv run python -m evals.run
```

The official feed is updated daily, so numbers can move slightly with the data. Each report records the code commit and the data snapshot. The set is small, so treat one question as about 2 points.

## Data and licence

Content comes from **Service-Public.gouv.fr / DILA** (Direction de l'information légale et administrative), published as open data under the [Licence Ouverte / Etalab](https://www.etalab.gouv.fr/licence-ouverte-open-licence). Two feeds, both schema 3.5:

- [Fiches pratiques et ressources de Service-Public.gouv.fr Particuliers](https://www.data.gouv.fr/datasets/fiches-pratiques-et-ressources-de-service-public-gouv-fr-particuliers): guides for individuals, on service-public.gouv.fr.
- [Fiches pratiques et ressources Entreprendre - Service-Public.gouv.fr](https://www.data.gouv.fr/datasets/fiches-pratiques-et-ressources-entreprendre-service-public-gouv-fr): guides for businesses and the self-employed, on entreprendre.service-public.gouv.fr. Downloaded from `https://lecomarquage.service-public.gouv.fr/vdd/3.5/pro/zip/vosdroits-latest.zip`.

## Disclaimer

This project is **not affiliated with, endorsed by or operated by the French administration**. It returns official text but is not legal advice. Always check the linked official page.
