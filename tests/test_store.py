from pathlib import Path

import pytest

from paperasse.ingest import parse_fiche
from paperasse.store import FicheStore, build_index, query_terms, to_fts_query
from tests.conftest import FICHES, make_fiche


def test_fts_query_drops_stopwords_and_adds_prefixes():
    assert to_fts_query("Comment demander l'APL quand on est étudiant ?") == (
        '"demander"* OR "apl" OR "étudiant"*'
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
