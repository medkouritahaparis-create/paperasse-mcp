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

## 2026-10-26 — Ranking: length prior (review step 4)

- **Context:** the baseline eval (search code 4e93a4c) gave all 44% top-1 / 75% top-3 / MRR 0.59. Long main guides lost to short Q&A fiches with similar titles (F2213 naturalisation and F19778 RSA at rank 9, F2882 prime d'activité at rank 6).
- **Method:** each option was tried alone against the same baseline, on the 48 answerable eval questions, by swapping `FicheStore.search` in a scratch harness that uses the eval's own `run_one`/`score` (it reproduced the baseline exactly before any change). A change is kept only if it beats the baseline by more than noise: one question is about 2 points. No embeddings.
- **Results** (top-1 / top-3 out of 48, MRR@10; baseline 21 / 36 / 0.593):

  | Option | Top-1 | Top-3 | MRR | Verdict |
  |---|---|---|---|---|
  | A. `text` weight 0.5 (from 1) | 22 | 37 | 0.611 | noise, rejected |
  | A. `text` weight 0.25 | 22 | 36 | 0.604 | noise, rejected |
  | A. `text` weight 0.1 | 20 | 32 | 0.571 | worse |
  | A. `text` weight 0 (title/summary/breadcrumb only) | 17 | 28 | 0.478 | worse |
  | B. `title` weight 20 or 40 (from 10) | 22 | 36 | 0.599 | noise, rejected |
  | B. `summary` weight 1 (from 4) | 19 | 34 | 0.558 | worse |
  | B. `summary` weight 8 | 23 | 36 | 0.614 | noise, rejected |
  | C. boost "Fiche d'information" type ×1.2 | 22 | 30 | 0.572 | worse (helps sentences, hurts keywords) |
  | C. same, ×1.5 | 22 | 27 | 0.541 | worse |
  | D. exclude "Recherche guidée" hubs | 21 | 35 | 0.583 | worse |
  | F. rank on title + summary first, then full text | 16 | 28 | 0.481 | worse |
  | G. re-rank top 50 by `match`, BM25 as tie-break | 21 | 34 | 0.588 | worse |
  | H. BM25 / best BM25 + 0.5 × `match` | 25 | 38 | 0.666 | better, but beaten by E |
  | **E. length prior: bm25 × (1 + a·ln(1 + text length)), a = 0.075** | **30** | **38** | **0.712** | **kept** |

- **Length prior sensitivity** (re-rank the top 50 BM25 hits): a = 0.01 → 24/36/0.633; 0.02 → 28/38/0.681; 0.03 → 28/39/0.687; **0.05, 0.075, 0.1 → 30/38/0.71** (a plateau); 0.15 → 29/38/0.699. A pool of 20, 50 or 100 gives the same numbers. a = 0.075 is the middle of the plateau, so the result doesn't rest on one exact value.
- **Tried on top of E, all rejected as noise:** `text` weight 0.5 (29/40/0.708: −1 top-1, +2 top-3); `summary` weight 8 (29/38/0.703); + 0.5 × `match` (30/39/0.718, but one fewer no-match question flagged).
- **Decision:** keep E alone. `bm25()` stays the first-stage ranker. Its top 50 (`RERANK_POOL`) are re-ranked by `bm25 × (1 + 0.075 · ln(1 + text_len))`, with `text_len` stored at build time. Why it works: FTS5's BM25 length normalisation (b = 0.75, fixed in FTS5) penalises long documents, while on service-public.fr the long fiche is usually the main guide and the short ones are narrow Q&A spin-offs. The prior is mild: a 40k-character guide gets about ×1.8 against ×1.5 for a 1k-character Q&A. Empty "Recherche guidée" hubs get no boost.
- **Result** (all / keywords / sentences): top-1 44% → **62%** / 50% → **77%** / 36% → **45%**; top-3 75% → **79%** / 85% → 85% / 64% → **73%**; MRR 0.59 → **0.71**. F2213 naturalisation, F19778 RSA and F2882 prime d'activité are now at rank 1.
- **`low_confidence` threshold re-checked on the new ranking:**

  | Threshold | No-match flagged | Useful warnings | False alarms |
  |---|---|---|---|
  | 0.40 | 7/9 | 9/18 | 6/30 |
  | **0.50** | **8/9** | **10/18** | **7/30** |
  | 0.55 | 9/9 | 11/18 | 7/30 |
  | 0.60 | 9/9 | 11/18 | 9/30 |

  0.55 looks slightly better, but the whole gain is one question ("cotisations sociales auto-entrepreneur", match 0.54), which review step 5 makes answerable. Changing the threshold for one data point would be overfitting, so it **stays at 0.5**, to be re-checked after step 5.

## 2026-10-27 — Entreprendre feed, `audience` and merged fiches (review step 5)

- **Context:** freelancer questions (micro-entreprise, URSSAF, CFE) had no answer: that content is in the DILA *Professionnels* feed (`.../vdd/3.5/pro/zip/vosdroits-latest.zip`, same schema 3.5), published on entreprendre.service-public.gouv.fr. On 2026-10-27 it has 775 fiches. 106 of them are also in the *Particuliers* feed, with the same id.
- **Shared fiches:** for all 106, title, summary, update date and text are identical once link targets are removed (checked with `strip_links`). The only differences are `spUrl` (the page on each site), the breadcrumb and inner links pointing to the feed's own site.
  - **Options:** (a) one row per (feed, id), so `get_fiche(id)` becomes ambiguous and "all" returns duplicates; (b) one row per id, with the official page for each audience.
  - **Decision:** (b). `merge_feeds` keeps the first feed's version (*Particuliers*), adds the second audience, and stores `urls = {audience: page}`. The text is the same official text either way. 3,004 + 775 − 106 = 3,673 fiches. The raw files now live in `data/raw/particuliers/` and `data/raw/professionnels/`. `scripts/check_fidelity` passes on all 3,779 files of both feeds.
- **`audience` parameter:** `search_fiche` accepts "particuliers", "professionnels" or "all", case-insensitive, and anything else is a clear error. With one audience, only fiches of that feed are searched, and `url` is the fiche's page on that audience's site (a shared fiche returns entreprendre.service-public.gouv.fr for "professionnels"). With "all", `url` is the primary page. Each result also lists `audiences`, and `get_fiche` returns `urls`.
- **Default: "all".**
  - Measured on the 61 answerable eval questions, before the hyphen fix below (the 48 *Particuliers* questions give identical by-category results either way):

    | Default | Top-1 | Top-3 | MRR | Freelance (13) top-1 / top-3 |
    |---|---|---|---|---|
    | "particuliers" | 29 | 37 | 0.55 | 0 / 0 |
    | **"all"** | **31** | **41** | **0.60** | 2 / 4 |

  - A freelancer often asks as a person ("can I be auto-entrepreneur while studying?"). The client can't be relied on to pick "professionnels", and with the old default those questions found nothing relevant. Searching both costs nothing on the *Particuliers* questions here, and the client can still narrow the search.
- **One index for both feeds:** BM25's word statistics (IDF, average length) are now computed over both feeds. On an index of the *Particuliers* fiches alone, the 48 original questions score exactly as on 2026-10-26 (30/38/0.71). On the shared index they score 29/37/0.69: q31 ("préavis", common in business fiches) drops from rank 1 to 3. That is one question, i.e. noise. Two separate indexes would need score merging for "all", so one index it is.
- **Hyphenated query words:** "micro-entrepreneur" used to be split into "micro" and "entrepreneur". Both are in the title of ~40 pro fiches, so they counted twice and buried the rest of the query ("micro-entrepreneur franchise TVA" put F21746 *Franchise en base de TVA* at rank 52). "auto*" also matched "autorisation", "automobile" and so on. Hyphenated words are now one FTS5 phrase term (`"micro entrepreneur"*`), and `match()` checks them as a phrase. Stopwords at the ends are dropped ("peuvent-ils" → "peuvent", "a-t-on" → nothing). Effect: freelance 2 → 3 top-1, q58 and q61 enter the top 10, no change on the other 48 questions. All: 31/41/0.60 → **32/41/0.62**.
- **Eval:** q27–q29 got expected ids (labelled from the fiche titles, like the rest). 10 freelancer questions were added (5 keywords, 5 sentences), making 67 questions, 61 answerable. Report: `evals/results/2026-10-27-337d5a8.md`.
- **`low_confidence` threshold re-checked** (no-match flagged / useful warnings / false alarms): 0.40 → 6/6, 16/29, 7/32; 0.45 → 6/6, 17/29, 7/32; **0.50 → 6/6, 18/29, 7/32**; 0.55 → 6/6, 18/29, 8/32; 0.60 → 6/6, 20/29, 9/32. The 0.55 case from step 4 is gone (q29 is answerable now). **Stays at 0.5.**
- **Known gaps, not fixed here (freelance top-1 is 3/13):**
  - Vocabulary: users say "auto-entrepreneur" and "micro-entreprise", while titles say "micro-entrepreneur". The `search_fiche` docstring now gives that translation as an example, which helps real clients but not the eval, which sends questions as is.
  - Full sentences: 0/5 freelance sentences are in the top 3, the same weakness as the *Particuliers* sentences.
  - Candidates for a later ranking step, measured the same way: a small synonym list for official renames, or light stemming.

## 2026-10-27 — Licences: MIT for the code, Licence Ouverte for the content (review step 6)

- **Context:** the repo is public and meant to be reused. It contains code; the content it serves belongs to the DILA.
- **Decision:** the code is MIT (`LICENSE`, © 2026 Taha Medkouri, also declared in `pyproject.toml`). The official content keeps its own licence, the Licence Ouverte / Etalab, and is credited as "Service-Public.gouv.fr / DILA" in the README and in every tool response (`source`). The data is never committed: users download it from the official feeds at install time, so the repo never redistributes a stale copy.
- **Why:** MIT is short, permissive and standard for small tools, and compatible with the Licence Ouverte, which only requires attribution. Keeping the two licences apart in the README avoids suggesting the MIT licence covers government content.

## 2026-10-27 — Eval split: tune on dev, report on test

- **Context:** `LENGTH_PRIOR` (step 4), the `low_confidence` threshold (steps 2, 4, 5) and the hyphen phrase terms (step 5) were all chosen on the same 67 questions that measured them. Scores on those questions are optimistic.
- **Change:** 18 new questions (12 freelance, 14 full sentences), labelled from the fiche titles found by grep on the titles, never from search results. That makes 85 questions, 79 answerable. Each question now has a `split`. The questions are sorted by (category, style, number) and every third one goes to `test`: no randomness, and categories and styles stay balanced. The result is **dev** 57 questions (53 answerable) and **test** 28 (26 answerable, 2 no-match). Test includes keywords, sentences, freelance and off-topic questions, and a unit test checks this. Reports are named `<date>-<code commit>-q<question set hash>.md`, so a new question set never overwrites an old report.
- **Rule:** search settings (weights, priors, synonyms, thresholds) are tuned and compared on **dev only**. **Test** is run only to report a final number, never to choose between options. If test numbers ever drive a change, that test set is spent and must be replaced by new questions.
- **Caveat:** 18 of the 26 test questions were part of the set that steps 4 and 5 were tuned on, so the test split is only clean from now on. The 18 new questions show the size of the effect. On search code `337d5a8`, the 61 previously seen questions score 52% top-1 / 67% top-3 / MRR 0.62. The 18 new ones score 44% / 50% / 0.50: harder (mostly sentences and freelance) and never tuned on.
- **Baseline on the new set** (search code `337d5a8`, report `evals/results/2026-10-27-337d5a8-q765f33.md`): dev 55% top-1 / 66% top-3 / MRR 0.62; **test 42% / 58% / 0.53**. Freelance: dev 41% / 41%, test 25% / 38%.

## 2026-10-27 — Query expansion with a synonym table

- **Context:** users say "auto-entrepreneur", "chômage" or "Pôle emploi", while official titles say "micro-entrepreneur", "allocation chômage (ARE)" or "France Travail". Freelance top-1 was 25% on test.
- **Dev set first:** by chance, only 2 dev questions used the targeted words. I added 8 dev questions in everyday vocabulary (labelled from titles; dev by construction, so test is untouched). I also replaced one new dev question that almost duplicated a test question ("Comment s'inscrire à France Travail…" vs "Je viens de perdre mon emploi, comment m'inscrire à France Travail ?"): leaving it would have leaked test into tuning. That makes 93 questions, dev 65 (61 answerable), test 28 (unchanged). Report on the old code with this set: `evals/results/2026-10-27-337d5a8-q0c79b3.md`.
- **Two ways to expand** (the user's words are always kept, never replaced):
  - **"or":** add the synonym to the same OR query. BM25 then adds the scores of both words, so a fiche that names "micro-entrepreneur (auto-entrepreneur)" in its text counts the concept twice and buries the rest of the query. On the real index, "retraite auto-entrepreneur" put *Régime de retraite du micro-entrepreneur* (F23369) at BM25 rank 25.
  - **"variants":** run the user's query, plus one query per synonym with the phrase swapped ("retraite micro-entrepreneur"). Each fiche keeps its best score. A synonym can lift a fiche but never counts twice, and `match()` counts a synonym in the title as covering the user's word.
- **Results on dev** (61 answerable; top-1 / top-3 / MRR; baseline with no expansion: 32 / 41 / 0.605). Each rule was tested alone:

  | Rule | "or" | "variants" | Verdict |
  |---|---|---|---|
  | auto-entrepreneur → micro-entrepreneur | 32 / 41 / 0.605 | **32 / 42 / 0.612** (q68 7→3, q88 >10→4) | **kept** |
  | chômage → allocation chômage, ARE | 32 / 41 / 0.607 | **32 / 41 / 0.607** (q91 3→2) | **kept** |
  | enceinte → grossesse | 32 / 41 / 0.606 | **33 / 42 / 0.621** (q44 >10→1) | **kept** (q44 was a known gap: dev is optimistic here) |
  | micro-entreprise → micro-entrepreneur | 31 / 41 / 0.600 | 32 / 41 / 0.603 (q61 9→>10) | rejected |
  | carte de séjour ↔ titre de séjour | 31 / 41 / 0.594 | 32 / 41 / 0.602 (q12 1→3, q15 2→1) | rejected |
  | mutuelle → complémentaire santé | 32 / 41 / 0.605 | 32 / 41 / 0.602 (q93 2→3) | rejected |
  | APL ↔ aide au logement, Pôle emploi → France Travail, sécu / sécurité sociale → Assurance maladie, freelance → micro-entrepreneur / travailleur indépendant, auto-entreprise → micro-entreprise, caution → dépôt de garantie, arrêt maladie → indemnités journalières | no change | no change | rejected: no evidence on dev |
  | all 15 together | 30 / 41 / 0.594 | 33 / 43 / 0.624 | — |

- **Decision:** "variants" mode (`EXPANSION_MODE` in `store.py`) with the 3 rules that helped (`paperasse/synonyms.py`). Rules with no measured effect are left out rather than kept on faith. A rule is added back when a dev question shows the need.
- **Result:**
  - Dev: 32 / 41 / 0.605 → **33 / 43 / 0.631**; freelance top-3 9 → 10.
  - Test, reported once and not used to choose: 11 → **12** top-1 (42% → **46%**), 15 → **16** top-3 (58% → **62%**), MRR 0.53 → **0.57**; freelance 2/8 → **3/8** top-1.
  - `low_confidence` is unchanged: all no-match questions flagged; false alarms 7 → 6 on dev.
  - Report: `evals/results/2026-10-27-8b2687b-q0c79b3.md`.
- **Seen while debugging, not fixed here:** full sentences lose to everyday verbs that are not stopwords ("suis", "peux", "veux"). "Je suis étudiant, est-ce que je peux être auto-entrepreneur ?" ranks *Je pars de chez mes parents* first. Step 4 below measures whether the client's rewrite into keywords already solves this.

## 2026-10-27 — End-to-end eval with an LLM client (`--rewrite`), and when to add embeddings

- **Context:** the `search_fiche` docstring tells the client model to turn the question into French keywords with official terms, but the eval sends questions as written. Sentence numbers therefore measure the worst case, not what a real MCP client sends.
- **Implemented:** `uv run --group eval python -m evals.run --rewrite` (`evals/rewrite.py`).
  - Claude Haiku 5.5 (`claude-haiku-5-5`, effort `low`) gets the server instructions and the `search_fiche` tool exactly as the MCP server publishes it (description and input schema read from `mcp.list_tools()`), then the question. The arguments it passes to the tool (query, and audience if it picks one) are what gets searched and scored.
  - Rewrites are cached in `evals/rewrites.jsonl`, keyed by model, tool definition and question: reruns are free and reproducible, and a docstring change is re-asked. The report lists every rewritten query and the cost.
  - Estimated cost at $0.10 / $0.50 per million tokens: about 1,000–1,500 input tokens (the tool definition is ~2,400 characters, ~700 tokens, plus the API's tool-use overhead and the question) and 100–300 output tokens per question, so roughly **$0.02–0.03** for the 93 questions.
  - The key comes from `ANTHROPIC_API_KEY` or the git-ignored `.env`. Without it, the mode prints "Skipped" and exits 0. The SDK lives in a separate `eval` dependency group, so CI and normal installs never need it. Tests use a fake client.
- **Not measured yet:** there was no API key on 2026-10-27, so `evals/rewrites.jsonl` is empty and no rewrite numbers exist. I did not write the rewrites myself as a substitute: I had seen the labels and the results, so my queries would have been biased.
- **Raw numbers that motivate it** (search code `8b2687b`, test split, report `evals/results/2026-10-27-8b2687b-q0c79b3.md`): keywords 64% top-1 / 73% top-3; full sentences **33% / 53%**. On dev: keywords 66% / 78%, sentences 41% / 62%. The gap is the vocabulary and phrasing problem keyword search can't bridge on its own: everyday verbs that aren't stopwords ("suis", "peux"), and words with no overlap with the official title ("garant" vs Visale, "propriétaire ne rend pas la caution" vs dépôt de garantie). English questions are labelled "no match" today, because BM25 can't find French fiches from English words.
- **Recommendation (not implemented): hybrid BM25 + multilingual embeddings, fused with Reciprocal Rank Fusion.**
  - **Condition:** run `--rewrite` first. If rewritten sentences reach the keyword level (≈ 65% top-1 on test), the client already bridges the gap and embeddings aren't worth their cost. If rewritten sentences stay below ~50% top-1, add them.
  - **Design:** embed each fiche's title + summary (+ breadcrumb) once at build time with a small multilingual model that runs locally (for example `intfloat/multilingual-e5-small` or `BAAI/bge-m3`), so there is no API dependency in the server. Store the vectors in SQLite (sqlite-vec) or a NumPy file next to the index. At query time, take the top 50 from BM25 (current pipeline) and the top 50 by cosine similarity, and fuse them with RRF (`score = Σ 1 / (60 + rank)`), which needs no score calibration between the two. Keep `match` / `low_confidence` on the lexical side.
  - **Why hybrid rather than replacing BM25:** BM25 is already strong on keywords (66–77% top-1) and on exact official names and acronyms (APL, ARE, CFE), where embeddings are weaker. RRF keeps those hits and adds the semantic ones.
  - **Measure:** dev first. Also give the two English questions expected fiche ids, since embeddings make them answerable.

## 2026-10-27 — Plan: hosting Paperasse as a remote MCP server (not deployed)

Plan only. Nothing is deployed and no account is created without the owner's approval.

- **Goal:** anyone can add Paperasse as a custom connector in Claude (or any MCP client) by pasting a URL, with no clone, no `uv` and no data build.
- **Transport:** MCP **Streamable HTTP**. The SDK already supports it: `mcp.run(transport="streamable-http")`, or `mcp.streamable_http_app()` mounted in an ASGI server (uvicorn) for a `/mcp` endpoint. stdio stays the default for local use, chosen by a `--http` flag or a `PAPERASSE_TRANSPORT` variable. The tools don't change.
- **State:** the server is read-only. One SQLite file (`paperasse.db`, 65 MB today) holds everything, with no user data and no sessions. So any instance can serve any request, scale to zero, and be replaced at any time.
- **Data refresh, daily:** build the data at **image build time**, not in the running server.
  - A scheduled GitHub Actions workflow (e.g. 04:00 Paris) runs ingest, store, the tests, `scripts.check_fidelity` and the eval (`evals.run --no-save`).
  - It refuses to publish if the fiche count drops by more than 5% or top-3 on the test split drops by more than 2 questions, which catches a broken feed or a schema change.
  - Otherwise it builds a container image with the database inside and deploys it.
  - Each day is an immutable image, so rollback is redeploying yesterday's. The feeds are about 33 MB and the build takes about a minute.
- **Host options:**

  | Option | Fit | Estimated cost |
  |---|---|---|
  | **Google Cloud Run** (container, scale to zero) | Stateless HTTP, pay per request, HTTPS and custom domain included, deploy from GitHub Actions with Workload Identity (no stored keys) | **≈ €0/month** at portfolio traffic (the free tier covers 2M requests and 360k GB-s/month); cold start ~1–2 s, fine for a tool call |
  | Fly.io (1 shared-cpu machine, 256–512 MB) | Simple `fly deploy`, always on, no cold start | ≈ $2–4/month |
  | Hugging Face Spaces (Docker) | Free, but it sleeps after inactivity and a public Space isn't meant as an API endpoint | €0, less reliable |

  **Recommendation:** Cloud Run, with 512 MB memory (the 65 MB database is read through the OS page cache), `min-instances=0`, `max-instances=3` and concurrency 20.
- **Safety and privacy:**
  - No authentication is needed: the content is public open data and the tools are read-only.
  - Per-IP rate limiting (e.g. 60 requests/min) at the proxy, and `max-instances` bounds the cost.
  - **Query text is never logged**, because people may type personal situations into a question. Only counts, latency and errors are logged.
  - Tool output keeps the source credit and the "not affiliated" notice. The service name and domain avoid any government branding (e.g. `paperasse-mcp.<owner domain>`, never a `gouv`-looking name).
- **Steps, each to be approved by the owner:**
  1. Add the HTTP transport, a `Dockerfile` and a `/healthz` route, and test locally with the MCP Inspector over HTTP.
  2. Owner creates the Google Cloud project, the billing alert (€5) and the GitHub Workload Identity binding.
  3. Add the nightly build-and-deploy workflow with the quality gates above.
  4. Optionally, a custom domain.
  5. README: a "Use it without installing" section with the connector URL.
