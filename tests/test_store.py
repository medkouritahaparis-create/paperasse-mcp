from pathlib import Path

import pytest

from paperasse.ingest import parse_fiche
from paperasse import store as store_module
from paperasse import synonyms
from paperasse.store import (
    FicheStore, build_index, expansions, fts_queries, query_terms, to_fts_query,
)
from tests.conftest import FICHES, make_fiche


def test_fts_query_drops_stopwords_and_adds_prefixes():
    assert to_fts_query("Comment demander l'APL quand on est étudiant ?") == (
        '"demander"* OR "apl" OR "etudiant"*'
    )


def test_fts_query_dedupes_and_handles_empty():
    assert to_fts_query("CAF caf Caf") == '"caf"'
    assert to_fts_query("  ? de la  ") is None


@pytest.mark.parametrize("query", ['"', "NEAR(a b)", "a OR", "*", "title:x", "AND NOT -x ^y"])
def test_fts_query_is_safe_against_fts_syntax(store, query):
    # Any user input must run without an FTS5 syntax error.
    store.search(query)


def test_search_ranks_title_matches_first(store):
    hits = store.search("aide logement étudiant")
    assert hits[0]["id"] == "F1"
    assert {"id", "title", "summary", "url", "updated_at"} <= hits[0].keys()


def test_search_prefix_matches_plurals(store):
    assert [h["id"] for h in store.search("allocation")] == ["F3"]


def test_search_is_accent_insensitive(store):
    assert store.search("etudiant")[0]["id"] == "F1"


def test_search_limit_and_no_match(store):
    assert len(store.search("étudiant", limit=1)) == 1
    assert store.search("zzzinconnu") == []


def test_get_returns_full_fiche_with_decoded_lists(store):
    fiche = store.get(" f3 ")
    assert fiche["id"] == "F3"
    assert fiche["url"].endswith("/F3")
    assert fiche["online_services"] == [{"id": "R1", "title": "Simulateur", "url": "https://example.gouv.fr/sim"}]
    assert store.get("F404") is None


def test_build_accepts_parsed_fiches(tmp_path):
    fiche = parse_fiche(Path(__file__).parent / "fixtures" / "F99999.xml")
    db = tmp_path / "x.db"
    assert build_index([fiche], db) == 1
    assert FicheStore(db).search("carte test")[0]["id"] == "F99999"


def test_rebuild_replaces_database(tmp_path):
    db = tmp_path / "x.db"
    build_index(FICHES, db)
    build_index(FICHES[:1], db)
    assert FicheStore(db).count() == 1
    assert not db.with_suffix(".tmp").exists()


def test_missing_database_has_helpful_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="paperasse.store"):
        FicheStore(tmp_path / "missing.db")


def test_link_urls_are_not_indexed(tmp_path):
    db = tmp_path / "links.db"
    build_index([make_fiche("F9", "Fiche avec lien", text="Voir [le site](https://example.gouv.fr/page).")], db)
    store = FicheStore(db)
    assert store.search("site")[0]["id"] == "F9"
    assert store.search("example") == []
    # The stored text keeps the link for the client.
    assert "(https://example.gouv.fr/page)" in store.get("F9")["text"]


def test_query_terms():
    assert query_terms("Comment demander l'APL, l'APL ?") == ["demander", "apl"]


def test_match_is_share_of_query_in_title_and_summary(store):
    assert store.match("aide logement étudiant", "Aide au logement pour étudiant", "") == 1.0
    # Accents and plurals are handled like in search.
    assert store.match("allocation", "Allocations familiales", "") == 1.0
    assert store.match("etudiant", "Aide au logement pour étudiant", "") == 1.0
    assert store.match("recette crêpes", "Aide au logement pour étudiant", "") == 0.0
    assert store.match("de la", "Aide", "") == 0.0  # only stopwords


def test_match_weights_rare_words_more(store):
    # "étudiant" is in 2 fiches, "transport" in 1: matching the rarer word counts more.
    rare = store.match("étudiant transport", "Carte de transport", "")
    common = store.match("étudiant transport", "Aide pour étudiant", "")
    assert 0 < common < rare < 1


def test_search_results_carry_match(store):
    hits = store.search("aide logement étudiant")
    assert hits[0]["match"] == 1.0
    # Found only through body text ("se déplacer"): weak match.
    assert store.search("déplacer")[0]["match"] == 0.0


def test_length_prior_lifts_main_guide_above_short_qa(tmp_path):
    # Without the prior, BM25 length normalisation puts the short Q&A first.
    guide = make_fiche("F10", "Naturalisation par décret", "Conditions et démarche.",
                       "\n\n".join(f"## Étape {i}\n\n" + "Texte officiel de la démarche. " * 60 for i in range(10)))
    qa = make_fiche("F11", "Naturalisation : quels justificatifs ?", "Liste des justificatifs.", "Un court texte.")
    db = tmp_path / "prior.db"
    build_index([guide, qa], db)
    store = FicheStore(db)
    assert [h["id"] for h in store.search("naturalisation")] == ["F10", "F11"]


def test_search_and_get_do_not_leak_ranking_internals(store):
    hit = store.search("aide logement étudiant")[0]
    assert "bm25" not in hit and "text_len" not in hit
    assert "text_len" not in store.get("F1")


def test_hyphenated_words_are_one_phrase_term():
    assert query_terms("cotisations auto-entrepreneur") == ["cotisations", "auto-entrepreneur"]
    assert to_fts_query("micro-entrepreneur TVA") == '"micro entrepreneur"* OR "tva"'
    # Stopwords at the ends of a hyphenated word are dropped.
    assert query_terms("Combien de congés a-t-on ? Peuvent-ils") == ["congés", "peuvent"]


def test_match_finds_hyphenated_terms_as_phrases(store):
    assert store.match("micro-entrepreneur", "Devenir micro-entrepreneurs", "") == 1.0
    assert store.match("micro-entrepreneur", "Micro crédit pour entrepreneur", "") == 0.0


def test_search_filters_by_audience(store):
    ids = lambda q, a: [h["id"] for h in store.search(q, audience=a)]
    assert ids("micro-entrepreneur", "professionnels") == ["F5"]
    assert ids("micro-entrepreneur", "particuliers") == []
    assert ids("micro-entrepreneur", "all") == ["F5"]
    assert ids("congé naissance", "particuliers") == ids("congé naissance", "professionnels") == ["F6"]
    with pytest.raises(ValueError):
        store.search("congé", audience="entreprises")


def test_shared_fiche_url_follows_requested_audience(store):
    url = lambda a: store.search("congé naissance", audience=a)[0]["url"]
    assert url("particuliers") == "https://www.service-public.gouv.fr/particuliers/vosdroits/F6"
    assert url("professionnels") == "https://entreprendre.service-public.gouv.fr/vosdroits/F6"
    assert url("all") == url("particuliers")  # primary page
    hit = store.search("congé naissance")[0]
    assert hit["audiences"] == ["particuliers", "professionnels"] and "urls" not in hit
    assert store.get("F6")["urls"] == {"particuliers": url("particuliers"), "professionnels": url("professionnels")}


@pytest.fixture
def rules(monkeypatch):
    """A fixed synonym table, so these tests don't depend on the shipped one."""
    monkeypatch.setattr(synonyms, "ONE_WAY", {"auto-entrepreneur": ["micro-entrepreneur"]})
    monkeypatch.setattr(synonyms, "TWO_WAY", [["carte de séjour", "titre de séjour"]])
    monkeypatch.setattr(store_module, "EXPANSION_MODE", "variants")


def test_two_way_groups_expand_both_ways(rules):
    assert ("titre de séjour", ["carte de séjour"]) in synonyms.rules()
    assert ("carte de séjour", ["titre de séjour"]) in synonyms.rules()


def test_expansions_match_phrases_ignoring_case_accents_and_plural(rules):
    assert expansions("cotisations AUTO-ENTREPRENEURS") == [("auto-entrepreneur", ["micro-entrepreneur"])]
    assert expansions("renouveler ma Carte de Sejour") == [("carte-de-sejour", ["titre-de-sejour"])]
    assert expansions("carte grise") == []


def test_variants_keep_the_original_query_first_and_never_replace_it(rules):
    queries = fts_queries("retraite auto-entrepreneur")
    assert queries == ['"retraite"* OR "auto entrepreneur"*', '"retraite"* OR "micro entrepreneur"*']
    assert fts_queries("carte grise") == [to_fts_query("carte grise")]


def test_or_mode_adds_synonyms_to_the_same_query(rules, monkeypatch):
    monkeypatch.setattr(store_module, "EXPANSION_MODE", "or")
    assert fts_queries("retraite auto-entrepreneur") == [
        '"retraite"* OR "auto entrepreneur"* OR "micro entrepreneur"*'
    ]


def test_off_mode_ignores_synonyms(rules, monkeypatch):
    monkeypatch.setattr(store_module, "EXPANSION_MODE", "off")
    assert expansions("auto-entrepreneur") == []


def test_search_finds_official_term_through_synonym(rules, store):
    # F5 is "Devenir micro-entrepreneur"; the user says "auto-entrepreneur".
    hit = store.search("auto-entrepreneur")[0]
    assert hit["id"] == "F5"
    assert hit["match"] == 1.0  # the synonym in the title counts as covering the query word


def test_synonym_never_counts_twice(rules):
    # No FTS query holds both a phrase and its synonym: in one OR query, BM25 would
    # add both up, as if the user had said the word twice (on the real corpus this
    # sank "Régime de retraite du micro-entrepreneur" to rank 25 for
    # "retraite auto-entrepreneur"; see docs/decisions.md).
    for q in fts_queries("cotisations retraite auto-entrepreneur"):
        assert not ("auto entrepreneur" in q and "micro entrepreneur" in q)
    assert len(fts_queries("cotisations retraite auto-entrepreneur")) == 2
