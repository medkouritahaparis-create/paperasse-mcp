# Paperasse MCP

An open-source [MCP](https://modelcontextprotocol.io) server that lets AI assistants answer questions about French administrative procedures **from official sources only**, with a citable link and last update date for every answer. It covers the guides for individuals (service-public.gouv.fr) and for professionals and the self-employed (entreprendre.service-public.gouv.fr).

> **Status:** early development. Ingestion of both official feeds, keyword search (SQLite FTS5) and a search eval work.

## Why

French administrative procedures are hard to navigate, and general-purpose AI assistants answer questions about them from memory: rules change every year (amounts, thresholds, deadlines), and a confident but outdated answer about the CAF, taxes or a residence permit can cost someone money or a deadline. The official guides already exist, are kept up to date by the DILA and are open data.

Paperasse gives an assistant those guides instead of its memory. It searches the official fiches, returns their text word for word with the official link and last update date, and says when it found nothing relevant. The assistant explains and cites; the server never writes or rewords the content.

## Try it

You need [uv](https://docs.astral.sh/uv/) and about a minute to download the official feeds and build the index:

```bash
git clone https://github.com/medkouritahaparis-create/paperasse-mcp.git
cd paperasse-mcp
uv sync
uv run python -m paperasse.ingest   # download both official feeds (about 35 MB) into data/
uv run python -m paperasse.store    # build the search index data/paperasse.db
```

**Claude Code:** open Claude Code in the repo folder: [.mcp.json](.mcp.json) registers the server. From anywhere else:

```bash
claude mcp add paperasse -- uv --directory /absolute/path/to/paperasse-mcp run main.py
```

**Claude Desktop:** add this to `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`), keeping your other servers, then restart Claude Desktop:

```json
{
  "mcpServers": {
    "paperasse": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/paperasse-mcp", "run", "main.py"]
    }
  }
}
```

If Claude Desktop can't find `uv`, use its full path (the output of `which uv`) as `command`.

Then ask, for example: *"Je suis étudiant, est-ce que j'ai droit aux APL ?"* or *"How do I declare my micro-entrepreneur revenue?"*. The answer should cite a service-public.gouv.fr or entreprendre.service-public.gouv.fr link.

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

## Development

```bash
uv run pytest                        # tests (no network, no data needed)
uv run mcp dev main.py               # inspect the tools in the MCP Inspector
uv run python -m evals.run           # search eval, writes evals/results/
```

Design choices, with the options considered and the numbers behind them, are in [docs/decisions.md](docs/decisions.md).

## Licence and data

The **code** is under the [MIT licence](LICENSE), © 2026 Taha Medkouri.

The **content** it serves is not covered by that licence: it comes from **Service-Public.gouv.fr / DILA** (Direction de l'information légale et administrative) and stays under the [Licence Ouverte / Etalab](https://www.etalab.gouv.fr/licence-ouverte-open-licence). Every tool response credits the source. The data is downloaded at install time and is not stored in this repository. Two feeds, both schema 3.5:

- [Fiches pratiques et ressources de Service-Public.gouv.fr Particuliers](https://www.data.gouv.fr/datasets/fiches-pratiques-et-ressources-de-service-public-gouv-fr-particuliers): guides for individuals, on service-public.gouv.fr.
- [Fiches pratiques et ressources Entreprendre - Service-Public.gouv.fr](https://www.data.gouv.fr/datasets/fiches-pratiques-et-ressources-entreprendre-service-public-gouv-fr): guides for businesses and the self-employed, on entreprendre.service-public.gouv.fr.

## Disclaimer

This project is **not affiliated with, endorsed by or operated by the French administration**. It returns official text but is not legal advice. Always check the linked official page.
