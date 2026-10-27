"""End-to-end eval helper: let a real model write the search query, as an MCP client would.

The search_fiche docstring asks the client model to turn the user's question
into a few French keywords with official terms. The plain eval sends questions
as they are written; `uv run --group eval python -m evals.run --rewrite` instead
gives Claude Haiku the search_fiche tool exactly as the server publishes it
(description and input schema from the MCP server, plus the server
instructions), sends the question, and measures the query the model passes to
the tool.

Rewrites are cached in evals/rewrites.jsonl, keyed by model, tool definition
and question, so reruns are free and reproducible, and a changed docstring is
re-asked. The API key comes from ANTHROPIC_API_KEY or the git-ignored .env;
without one, only cached rewrites can be used. The tests and CI never call the API.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import main

EVALS_DIR = Path(__file__).resolve().parent
CACHE = EVALS_DIR / "rewrites.jsonl"
ENV_FILE = EVALS_DIR.parent / ".env"
MODEL = "claude-haiku-5-5"
PRICE_PER_MTOK = {"input": 0.10, "output": 0.50}  # USD, Claude Haiku 5.5, prompts under 100K tokens


class RewriteUnavailable(Exception):
    """A rewrite is needed but there is no API key or SDK: the caller skips the rewrite eval."""


def tool_definition() -> dict[str, Any]:
    """search_fiche as the MCP server publishes it, in Messages API tool format."""
    tool = next(t for t in asyncio.run(main.mcp.list_tools()) if t.name == "search_fiche")
    return {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}


def cache_key(question: str, tool: dict[str, Any], instructions: str, model: str = MODEL) -> str:
    blob = json.dumps([model, tool, instructions, question], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def load_cache(path: Path = CACHE) -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return {row["key"]: row for row in map(json.loads, filter(str.strip, f))}


def _load_env_file(path: Path | None = None) -> None:
    """Read KEY=value lines from .env into the environment (existing variables win)."""
    path = path or ENV_FILE
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _client():
    _load_env_file()
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise RewriteUnavailable(
            "No ANTHROPIC_API_KEY (environment or .env): skipping the LLM rewrite eval. "
            "Put ANTHROPIC_API_KEY=... in .env (git-ignored) to run it."
        )
    try:
        import anthropic
    except ImportError as e:
        raise RewriteUnavailable("The anthropic SDK is not installed: run `uv sync --group eval`.") from e
    return anthropic.Anthropic()


def ask_model(client, question: str, tool: dict[str, Any], instructions: str) -> dict[str, Any]:
    """One question -> the arguments the model passes to search_fiche, with token usage."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        output_config={"effort": "low"},
        system=instructions,
        tools=[tool],
        tool_choice={"type": "auto"},
        messages=[{"role": "user", "content": question}],
    )
    call = next((b for b in response.content if b.type == "tool_use" and b.name == tool["name"]), None)
    return {
        "arguments": dict(call.input) if call else None,  # None: the model answered without searching
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }


def rewrite_all(questions: list[dict], client_factory=_client, cache_path: Path = CACHE) -> tuple[dict[str, dict], dict]:
    """Rewrite every question, using the cache first.

    Returns ({question id: cache row}, cost info). New rewrites are appended to
    the cache as they arrive, so an interrupted run loses nothing.
    """
    tool, instructions = tool_definition(), main.mcp.instructions or ""
    cache = load_cache(cache_path)
    out, client, new_in, new_out = {}, None, 0, 0
    for q in questions:
        key = cache_key(q["question"], tool, instructions)
        if key not in cache:
            client = client or client_factory()
            result = ask_model(client, q["question"], tool, instructions)
            cache[key] = {"key": key, "model": MODEL, "question": q["question"], **result}
            with open(cache_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(cache[key], ensure_ascii=False) + "\n")
            new_in += result["input_tokens"]
            new_out += result["output_tokens"]
        out[q["id"]] = cache[key]
    rows = list(out.values())
    total_in, total_out = sum(r["input_tokens"] for r in rows), sum(r["output_tokens"] for r in rows)
    cost = {
        "model": MODEL,
        "new_tokens": (new_in, new_out),
        "new_cost_usd": _usd(new_in, new_out),  # spent by this run
        "full_run_cost_usd": _usd(total_in, total_out),  # what the whole set costs without the cache
    }
    return out, cost


def _usd(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * PRICE_PER_MTOK["input"] + output_tokens * PRICE_PER_MTOK["output"]) / 1e6
