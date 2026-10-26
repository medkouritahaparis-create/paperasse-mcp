"""Paperasse MCP server: tool definitions only. Logic lives in the paperasse package."""

from mcp.server.mcpserver import MCPServer

from paperasse.ingest import SOURCE_CREDIT

mcp = MCPServer(
    name="paperasse",
    instructions=(
        "Official information on French administrative procedures from service-public.fr. "
        "Always cite the returned source URL and last update date. "
        "Not affiliated with the French administration."
    ),
)


@mcp.tool()
def search_fiche(query: str, audience: str = "particuliers") -> list[dict]:
    """Search official service-public.fr guides (fiches) about a French administrative procedure.

    Use this first for any question about French paperwork (CAF, URSSAF, taxes, residence
    permits, health insurance...). Write the query in French for best results.
    Returns the top matching fiches with id, title, short summary, official URL and last
    update date. Then call get_fiche(id) to read the full text before answering.

    PLACEHOLDER: returns a fixed fake result until the search index is built.
    """
    return [
        {
            "id": "F0",
            "title": "Fiche de démonstration",
            "summary": f"Résultat factice pour « {query} » ({audience}). La recherche réelle arrive bientôt.",
            "url": "https://www.service-public.gouv.fr/particuliers/vosdroits",
            "updated_at": None,
            "source": SOURCE_CREDIT,
        }
    ]


if __name__ == "__main__":
    mcp.run()
