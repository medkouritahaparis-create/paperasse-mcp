# Paperasse MCP

An open-source [MCP](https://modelcontextprotocol.io) server that lets AI assistants answer questions about French administrative procedures **from official sources only**, with a citable link and last update date for every answer.

> **Status:** early development. The XML ingestion works; search is still a placeholder.

## Quick start

```bash
uv sync
uv run python -m paperasse.ingest   # download the official feed and build data/fiches.jsonl
uv run mcp dev main.py              # inspect the tools in the MCP Inspector
uv run pytest
```

## Data and licence

Content comes from **Service-Public.gouv.fr / DILA** (Direction de l'information légale et administrative), published as open data under the [Licence Ouverte / Etalab](https://www.etalab.gouv.fr/licence-ouverte-open-licence). Feed: [Fiches pratiques et ressources de Service-Public.gouv.fr Particuliers](https://www.data.gouv.fr/datasets/fiches-pratiques-et-ressources-de-service-public-gouv-fr-particuliers) (schema 3.5).

## Disclaimer

This project is **not affiliated with, endorsed by or operated by the French administration**. It returns official text but is not legal advice. Always check the linked official page.
