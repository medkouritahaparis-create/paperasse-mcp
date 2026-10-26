from pathlib import Path

import pytest

from paperasse.ingest import parse_fiche
from paperasse.store import FicheStore, build_index, to_fts_query
from tests.conftest import FICHES


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
