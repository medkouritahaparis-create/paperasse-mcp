"""Paperasse MCP server: tool definitions only. Logic lives in the paperasse package."""

from functools import cache
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from paperasse.ingest import SOURCE_CREDIT
from paperasse.store import MIN_CONFIDENT_MATCH, FicheStore

MAX_RESULTS = 10
LOW_CONFIDENCE_HINT = (
    "These results may not match. Rephrase the query in French with official administrative terms."
)
PAGE_CHARS = 40_000  # ~10k tokens; covers ~97% of fiches in one page

mcp = MCPServer(
    name="paperasse",
    instructions=(
        "Official information on French administrative procedures from service-public.fr. "
        "Search with search_fiche, then read the fiche with get_fiche before answering. "
        "Always cite the returned url and updated_at. "
        "Not affiliated with the French administration."
    ),
)


@cache
def _store() -> FicheStore:
    try:
        return FicheStore()
    except FileNotFoundError as e:
        raise ToolError(str(e)) from e


def _page(text: str, offset: int, max_chars: int) -> tuple[str, int | None]:
    """Slice text at a line boundary. Returns (chunk, next_offset or None)."""
    end = offset + max_chars
    if end >= len(text):
        return text[offset:], None
    cut = text.rfind("\n", offset, end)
    if cut <= offset:
        cut = end
    return text[offset:cut], cut


@mcp.tool()
def search_fiche(query: str, audience: str = "particuliers", limit: int = 5) -> dict[str, Any]:
    """Search official service-public.fr guides (fiches) about a French administrative procedure.

    Use this first for any question about French paperwork: CAF (APL, RSA, prime d'activité),
    URSSAF, impôts, titre de séjour, carte Vitale, logement social, carte grise, etc.
    The fiches are in French: always translate the user's question into a few French keywords
    using official administrative terms before calling, even if the user writes in another
    language (e.g. "I lost my residence permit" -> "perte titre de séjour";
    "student housing aid" -> "APL étudiant"). Don't pass a full sentence.

    Returns up to `limit` (max 10) fiches, best match first, each with id, title, summary,
    official url, updated_at and `match` (0-1: how much of the query the title and summary
    cover). Then call get_fiche(id) to read the full text before answering: the summary alone
    is not enough to answer.

    If `low_confidence` is true, the best result probably doesn't answer the question: retry
    once with different French official terms (synonyms, the name of the benefit or document).
    If it is still low, don't present these fiches as the answer; say no matching official
    guide was found.
    """
    if audience.strip().lower() != "particuliers":
        raise ToolError("Only audience='particuliers' is available for now.")
    if not query.strip():
        raise ToolError("Empty query. Describe the procedure in a few French keywords.")
    results = _store().search(query, limit=max(1, min(limit, MAX_RESULTS)))
    if not results:
        raise ToolError(
            f"No fiche found for {query!r}. Try broader or different French terms "
            "(e.g. 'allocation logement' instead of a full sentence)."
        )
    out: dict[str, Any] = {"results": results, "low_confidence": results[0]["match"] < MIN_CONFIDENT_MATCH}
    if out["low_confidence"]:
        out["hint"] = LOW_CONFIDENCE_HINT
    out["source"] = SOURCE_CREDIT
    return out


@mcp.tool()
def get_fiche(id: str, offset: int = 0) -> dict[str, Any]:
    """Read the full official text of a service-public.fr fiche, by id (e.g. "F12006").

    Use after search_fiche, before answering. The text is the official wording, in French,
    with Markdown headings and [links](url). It often covers several cases ("### En France",
    "### À l'étranger"): pick the one that matches the user's situation. When the official text
    repeats a block word for word in several cases, it is given once; later copies are replaced by
    a line "[Paperasse : identique à « … » plus haut (sous « … »)]" pointing to the first copy.

    Returns title, url, updated_at, text, online_services (official online procedures with
    links) and sources (legal texts). Long fiches come in pages: if `next_offset` is not null,
    call again with offset=next_offset to read more. For paged fiches, `outline` lists the
    main headings with their offset: call get_fiche(id, offset=...) to jump to a section.
    """
    fiche = _store().get(id)
    if fiche is None:
        raise ToolError(f"No fiche with id {id!r}. Ids look like 'F12006'; get them from search_fiche.")
    text = fiche.pop("text")
    if offset < 0 or (offset and offset >= len(text)):
        raise ToolError(f"offset must be between 0 and {len(text) - 1} for fiche {fiche['id']}.")
    chunk, next_offset = _page(text, offset, PAGE_CHARS)
    fiche.update(
        text=chunk,
        offset=offset,
        next_offset=next_offset,
        total_chars=len(text),
        source=SOURCE_CREDIT,
    )
    if next_offset is not None or offset:
        fiche["outline"] = _outline(text)
    return fiche


def _outline(text: str) -> list[dict[str, Any]]:
    """Top-level headings (## and ###) with the offset to pass to get_fiche to jump there."""
    outline, pos = [], 0
    for line in text.splitlines(keepends=True):
        if line.startswith(("## ", "### ")):
            outline.append({"heading": line.strip(), "offset": pos})
        pos += len(line)
    return outline


if __name__ == "__main__":
    mcp.run()
