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

## 2026-10-26 — Repeated blocks, dropped titles and dropped links in fiche text

- **Context:** an outside review found that 23% of fiche text was paragraphs (>80 chars) repeated inside the same fiche (1,605 of 3,004 fiches). Example: F827 repeats its "droit à l'erreur" section 6 times, including under the MSA cases.
- **Diagnosis (data/raw/F827.xml):** the repetition is **in the source**. The XML holds 6 identical `<Complement>` blocks, one inside each `<Cas>` (3 under `Situation[Caf]`, 3 under `Situation[MSA]`). The parser was faithful to it. But the parser had two bugs of its own: (1) it dropped the title of `<Complement>` ("En savoir plus si vous avez oublié de déclarer votre situation"), so the block read as part of the case text; (2) it dropped the URL of every inline link (`LienExterne`, `LienInterne`), keeping only the link text. Across all fiches: 1,063 `Complement`, 171 `PourEnSavoirPlus`, 41 `Reference` and 30 `Conclusion` titles, plus 5,327 external and about 34k internal link URLs. The "nouvelle demande d'aide au logement" paragraph in F827 had no link in the XML, so nothing was lost there.
- **Options for the repetition:** (a) keep every copy (faithful but noisy: 23% of tokens, and the model sees the same text under unrelated cases); (b) move a shared block out of the cases, under a new heading (wrong when a block is shared by only some cases, and it needs a heading we would have to write); (c) print a repeated block where it first appears, and at each later position put a one-line pointer to it.
- **Decision:** (c). A block of type Chapitre/Cas/Situation/Complement/callout/BlocCas/Liste/Tableau/Paragraphe whose XML is identical to an earlier one, and whose rendered text is at least 200 characters, becomes `[Paperasse : identique à « <its title or first words> » plus haut (sous « <2 nearest headings of the first copy> »)]`. Link blocks (online services, offices, references) are never merged, so each case keeps its own "Title (URL)" line. The pointer is clearly marked as coming from Paperasse. It quotes only the official title or opening words and adds no official wording. Also: `Complement` and `Conclusion` titles are now headings; `PourEnSavoirPlus` and `Reference` render as "Title (URL)"; inline links render as `[text](url)` (internal links point to the official page, except acronyms and glossary terms, which have no page and 404); and a table's `<Resume>` ("Ce tableau présente…", never rendered before) is printed above it. Link URLs are stripped before indexing so they don't add noise tokens to search.
- **Why 200 characters:** a pointer averages about 147 characters. Measured on all fiches (links stripped, pointer lines excluded): no merging 22.3% duplicated; cutoff 400 → 11.5%; **200 → 6.7%**; 150 → 4.2% but pointers grow to 8.9% of all text; 120 → 2.7% with 11.2%. Below 200, pointers replace text of about their own length and make each case harder to read on its own. What remains duplicated is mostly short, case-specific sentences.
- **Result:** duplicated characters **23.2% → 6.9%** (`python -m scripts.dup_stats`); total text 32.1M → 27.7M characters, even with link URLs added back. `python -m scripts.check_fidelity`: every source `Paragraphe` of all 3,004 fiches is in the output (excluding elements skipped on purpose). Search on the 26 labelled manual-test questions is unchanged (13 at rank 1, 22 in the top 3).

## 2026-10-26 — `low_confidence` flag on weak search results

- **Context:** BM25 with an OR query always returns something. A question with no real match came back with confident-looking results, e.g. "I lost my residence permit what do I do" → SNCF mediator, EU internships, garde alternée.
- **Signals tried** (on the 26 labelled manual-test questions, plus 15 off-topic, English and no-content queries, using a one-off analysis script; the eval runner in review step 3 makes these numbers reproducible):
  - **Raw BM25 score of the top result:** doesn't separate them. Off-topic queries score 8–29, good ones 4–24. BM25 has no absolute scale.
  - **BM25 divided by the number of query terms:** also overlaps (off-topic 1.7–6.3, good 1.3–7.2).
  - **Share of query words found in the top result's title and summary:** separates better, but the edges are wrong ("avis d'imposition contester", a correct hit, 0.33; "quel temps fait-il" 0.50).
  - **Same share weighted by word rarity (BM25 IDF from the index), with accent folding and the same 4-letter prefix rule as search:** best. Missing rare words ("PSG", "iPhone", English words, which barely occur in French fiches) weigh more than missing common ones. Adding the breadcrumb to title + summary changed nothing.
- **Decision:** every result gets `match` (IDF-weighted share of the query in its title + summary, 0–1). The response gets `low_confidence: true` and a `hint` when the top result's `match` is below **0.5** (`MIN_CONFIDENT_MATCH` in `paperasse/store.py`). Results are still returned, so the client can judge. The `search_fiche` docstring now tells the client to translate the user's question into French official keywords before calling, to retry once with other terms on `low_confidence`, and otherwise to say no official guide was found.
- **Threshold choice:**

  | Threshold | Good queries flagged (false alarms) | Bad queries flagged |
  |---|---|---|
  | 0.4 | 2/26 | 10/13 |
  | **0.5** | **2/26** | **11/13** |
  | 0.55 | 5/26 | 12/13 |

  (2 more bad queries, "bonjour" and gibberish, return no results and already get the "no fiche found" error.) 0.55 catches one more bad query at the cost of 3 more false alarms; too many warnings teach the client to ignore them. With 0.5, the false alarms are "déclarer un changement de situation à la CAF" and "avis d'imposition contester" (both correct, with titles that use other words). The misses are "quel temps fait-il" (its words also appear in fiche titles) and "cotisations sociales auto-entrepreneur" (no freelancer fiches yet; review step 5).
- **Limits:** chosen on 41 queries, so the threshold is a first estimate. Re-check it on the eval set (review step 3), which includes no-match questions. Search ranking is unchanged (13/26 at rank 1, 22/26 in the top 3), and a search takes about 2 ms.

## 2026-10-26 — Search eval: question set, labels and metrics

- **Context:** ranking changes (review step 4) and the `low_confidence` threshold need a fixed, reproducible measurement, not eyeballing.
- **Question set (`evals/questions.jsonl`, 57 questions):**
  - The 26 labelled manual-test questions (keyword style).
  - The 3 freelancer manual-test questions, with `expected: []` until the *Entreprendre* feed is ingested (review step 5).
  - 22 new questions phrased the way people ask (full sentences), across logement, transport, impôts, titre de séjour, santé, CAF, travail, papiers, famille and justice.
  - 6 with no good answer: 4 off-topic in French, and 2 in English (the server only searches French text; clients are told to translate first).
  - No personal data.
- **Labelling rule:** the expected fiche is chosen by browsing the 3,004 fiche titles, never from search output, so the eval doesn't grade the engine against itself. Several ids are allowed when more than one fiche truly answers. "Recherche guidée" hubs (empty text) are never counted as correct. Two candidate questions were dropped because no fiche answers them by title ("numéro fiscal", "renouvellement de titre de séjour" in general).
- **Metrics (`evals/run.py`, which calls the real `search_fiche`):** top-1, top-3 and MRR@10, overall and split by style. "Keywords" is what the tool docstring asks clients to send; "sentence" is a question sent unchanged, which is the pessimistic case. For `low_confidence`: the share of no-match questions flagged; and on answerable questions, a flag is a *false alarm* when rank 1 is right and a *useful warning* when it is wrong. A first draft counted every flag on an answerable question as a false alarm, which wrongly penalised correct warnings. The runner fails if an expected id has left the database (the feed changes daily), and each report records the search-code commit and the data snapshot.
- **Baseline (search code 4e93a4c):**

  | Questions | n | Top-1 | Top-3 | MRR@10 |
  |---|---|---|---|---|
  | Keywords | 26 | 50% | 85% | 0.68 |
  | Sentence | 22 | 36% | 64% | 0.50 |
  | All | 48 | 44% | 75% | 0.59 |

  `low_confidence`: 8/9 no-match questions flagged; 10/27 wrong rank-1 results flagged; 5/21 right rank-1 results flagged (false alarms, 3 of them sentences).
- **What the baseline shows, for step 4:**
  - Long main guides are outranked by short Q&A fiches (F2213 naturalisation at rank 9, F19778 RSA at rank 9, F2882 prime d'activité at rank 6).
  - Sentence queries carry many words that aren't in titles. That also makes `low_confidence` fire on correct answers, so the 0.5 threshold, chosen on keyword queries, should be re-checked against this set.
  - Some misses are vocabulary gaps ("garant gratuit" vs "Garantie Visale", "enceinte" vs "naissance"), which keyword search can't bridge without synonyms or embeddings. They're out of scope for step 4.
