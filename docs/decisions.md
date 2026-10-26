# Architecture decision log

Each entry: context, options, decision, why.

## 2026-10-26 — MCP Python SDK v2 (`MCPServer`, not `FastMCP`)

- **Context:** `uv add "mcp[cli]"` installs mcp 2.3.0, where `FastMCP` is renamed `MCPServer` (`from mcp.server.mcpserver import MCPServer`).
- **Options:** pin `mcp<2` to keep the `FastMCP` API, or use v2.
- **Decision:** use v2 and `MCPServer`.
- **Why:** it's a new project with no legacy code to protect, and v2 is the maintained line. Same decorator style (`@mcp.tool()`).

## 2026-10-26 — Data source: DILA "particuliers" feed, schema 3.5

- **Context:** service-public.fr publishes its fiches as open data (Licence Ouverte) on data.gouv.fr. v3.3 was removed on 4 May 2026, and the current version is 3.5.
- **Decision:** ingest `https://lecomarquage.service-public.gouv.fr/vdd/3.5/part/zip/vosdroits-latest.zip` (about 24 MB, 5,572 XML files). The version is the `FEED_VERSION` constant in `paperasse/ingest.py`. Only `F*.xml` files (fiches, 3,004 on 2026-10-26) are parsed for now. `N*` files (themes/folders) and `R*` files (resources: forms, glossary, online services) can come later.
- **Why:** the official XML is the source of truth, is updated daily and has stable IDs and URLs. The vectorised Hugging Face mirror (AgentPublic/service-public) is derived data and would add a dependency we don't need yet.

## 2026-10-26 — Render fiche text as plain Markdown, verbatim

- **Context:** the server must return source text and never paraphrase it. The XML mixes content with presentation (`MiseEnEvidence`), questionnaire logic (`Questionnaire`, `Condition`) and case tabs (`BlocCas`/`Cas`, `ListeSituations`/`Situation`).
- **Options:** (a) return raw XML, (b) strip all tags to one blob, (c) render to light Markdown that keeps structure.
- **Decision:** (c). Chapters, cases and situations become headings, with the level following nesting depth. Lists become `-` / `1.`, tables become Markdown tables, and callouts become `À noter : …` using the label from the XML. Online services, notices and offices become `Titre (URL)` followed by their own text. Questionnaire logic is dropped. **All cases are kept:** the server doesn't know the user's situation, so the client picks the relevant case.
- **Why:** an LLM reads headings and lists well, and keeping every case means nothing is silently filtered out. No words are added except the XML's own labels.
- **Verified:** a script compared every `Paragraphe` in the source with the output across all 3,004 fiches. The only paragraphs not reproduced are image and video descriptions (transcripts and alt text), which are excluded on purpose. 82 "Recherche guidée" fiches are hubs with no body text: they keep their metadata and an empty `text`.

## 2026-10-26 — Two dates per fiche

- **Decision:** `updated_at` comes from `dc:date` ("modified YYYY-MM-DD"; present on every fiche, and the date to cite). `important_update_at` comes from `dateDerniereModificationImportante` (present on about 58% of fiches; marks substantive changes).
- **Why:** the rules require a last-update date on every result. `dc:date` is the only one that is always present.

## 2026-10-26 — Search: SQLite FTS5, BM25, OR query with prefixes

- **Context:** roadmap step 2 needs real search over 3,004 fiches. Users ask in natural French ("Comment demander l'APL quand on est étudiant ?").
- **Options:** (a) FTS5 with all words AND-ed, (b) FTS5 with words OR-ed, ranked by BM25, (c) embeddings.
- **Decision:** (b). `unicode61 remove_diacritics 2` tokenizer, so "etudiant" matches "étudiant". A small French stopword list is removed. Words of 4+ letters get a prefix match ("allocation" → "allocations"), since unicode61 doesn't stem. Every term is quoted, so user input can't inject FTS5 syntax. BM25 column weights: title 10, summary 4, breadcrumb 2, text 1. The FTS table is contentless (`content=''`), with full rows in a normal `fiches` table, which keeps the DB at about 50 MB.
- **Why:** it's simple, has no extra dependencies and is good enough on a first check. (c) stays on hold until evals show keyword search falling short, as planned in CLAUDE.md.
- **Tried and rejected for now:** "AND matches first, then OR". It fixed one query (paying tax in instalments) but lost the best fiche for "APL étudiant" and pushed long catch-all fiches (e.g. F16507 "Un proche est décédé", 225k characters) to the top. Ranking will be tuned against the step 4 eval set, not by eye. Known weak queries to add to the eval set: "j'ai reçu un avis d'imposition, comment payer en plusieurs fois", "carte vitale perdue", "déclarer mon chiffre d'affaires auto-entrepreneur URSSAF".

## 2026-10-26 — `get_fiche` returns long fiches in pages

- **Context:** fiche text has a median of 6.7k characters, but 104 fiches are over 40k and the largest (F32823) is 309k. That's too much for one tool result.
- **Decision:** pages of up to 40k characters (about 10k tokens), cut at a line break, with `offset` / `next_offset` / `total_chars`. Paged fiches also get an `outline` of `##`/`###` headings, each with its offset, so the model can jump to the relevant section. Deeper headings were left out because they made the outline itself 40k characters on F32823.
- **Why:** nothing is cut silently, the client controls how much it reads, and the text stays verbatim (pages joined back together equal the full text, which is tested).
