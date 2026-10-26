import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import main
from paperasse.ingest import SOURCE_CREDIT


@pytest.fixture(autouse=True)
def use_test_store(monkeypatch, store):
    monkeypatch.setattr(main, "_store", lambda: store)


def test_tools_are_registered():
    tools = asyncio.run(main.mcp.list_tools())
    assert {t.name for t in tools} == {"search_fiche", "get_fiche"}
    assert all(t.description for t in tools)


def test_search_fiche_returns_cited_results():
    out = main.search_fiche("aide logement étudiant")
    assert out["source"] == SOURCE_CREDIT
    first = out["results"][0]
    assert first["id"] == "F1"
    assert first["url"].startswith("https://www.service-public.gouv.fr/")
    assert first["updated_at"] == "2026-09-11"


def test_search_fiche_good_match_is_confident():
    out = main.search_fiche("aide logement étudiant")
    assert out["low_confidence"] is False
    assert "hint" not in out
    assert out["results"][0]["match"] == 1.0


def test_search_fiche_weak_match_is_flagged_but_still_returned():
    out = main.search_fiche("déplacer")  # only in F2's body text
    assert out["low_confidence"] is True
    assert out["hint"] == main.LOW_CONFIDENCE_HINT
    assert out["results"][0]["id"] == "F2"
    assert out["source"] == SOURCE_CREDIT and out["results"][0]["url"]


def test_search_fiche_docstring_tells_client_to_use_french():
    doc = main.search_fiche.__doc__
    assert "translate" in doc and "low_confidence" in doc


def test_search_fiche_limit_is_capped():
    assert len(main.search_fiche("étudiant", limit=1)["results"]) == 1
    assert len(main.search_fiche("fiche", limit=999)["results"]) <= main.MAX_RESULTS


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"query": "zzzinconnu"}, "No fiche found"),
        ({"query": "   "}, "Empty query"),
        ({"query": "logement", "audience": "professionnels"}, "particuliers"),
    ],
)
def test_search_fiche_errors_are_explained(kwargs, message):
    with pytest.raises(ToolError, match=message):
        main.search_fiche(**kwargs)


def test_get_fiche_short_fiche_in_one_page():
    out = main.get_fiche("f3")
    assert out["id"] == "F3"
    assert out["text"] == "Les allocations sont versées chaque mois."
    assert out["next_offset"] is None
    assert "outline" not in out
    assert out["source"] == SOURCE_CREDIT and out["updated_at"] and out["url"]


def test_get_fiche_pages_long_fiche_without_losing_text(store):
    full = store.get("F4")["text"]
    pages, offset = [], 0
    while offset is not None:
        out = main.get_fiche("F4", offset=offset)
        assert len(out["text"]) <= main.PAGE_CHARS
        pages.append(out["text"])
        offset = out["next_offset"]
    assert "".join(pages) == full
    assert len(pages) > 1


def test_get_fiche_outline_offsets_jump_to_headings():
    out = main.get_fiche("F4")
    assert len(out["outline"]) == 12
    target = out["outline"][5]
    assert main.get_fiche("F4", offset=target["offset"])["text"].startswith(target["heading"])


def test_get_fiche_errors_are_explained():
    with pytest.raises(ToolError, match="No fiche with id"):
        main.get_fiche("F404")
    with pytest.raises(ToolError, match="offset must be"):
        main.get_fiche("F3", offset=10_000)
