import re
from pathlib import Path

import pytest

from paperasse.ingest import Fiche, iter_fiches, merge_feeds, parse_fiche, strip_links

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def fiche():
    return parse_fiche(FIXTURES / "F99999.xml")


def test_metadata(fiche):
    assert fiche.id == "F99999"
    assert fiche.title == "Demande de carte de test"
    assert fiche.audiences == ["particuliers"]
    assert fiche.summary == "Comment demander une carte de test."
    assert fiche.theme == "Papiers"
    assert fiche.breadcrumb == ["Accueil particuliers", "Papiers"]
    assert fiche.sources == ["https://www.legifrance.gouv.fr/a", "https://www.legifrance.gouv.fr/b"]


def test_source_url_and_dates(fiche):
    assert fiche.url == "https://www.service-public.gouv.fr/particuliers/vosdroits/F99999"
    assert fiche.urls == {"particuliers": fiche.url}
    assert fiche.updated_at == "2026-09-11"
    assert fiche.important_update_at == "2026-03-06"


def test_online_services(fiche):
    assert [(s.id, s.title, s.url) for s in fiche.online_services] == [
        ("R1", "Faire la demande en ligne", "https://example.gouv.fr/teleservice")
    ]


def test_text_keeps_inline_spacing(fiche):
    # Whitespace before a closing tag must survive: "loger </Expression>ne" -> "loger ne".
    assert "Les personnes à loger ne doivent pas dépasser le 1er plafond." in fiche.text
    assert "La carte de test est gratuite." in fiche.text


def test_text_structure(fiche):
    lines = fiche.text.splitlines()
    assert "## Qui peut la demander ?" in lines
    assert "À noter : La demande est personnelle." in lines
    assert "1. Remplir le formulaire" in lines
    assert "2. Envoyer le dossier" in lines
    # Cases are nested one level under their chapter, with clean titles.
    assert "### En France" in lines
    assert "### À l'étranger" in lines


def test_table(fiche):
    lines = fiche.text.splitlines()
    i = lines.index("| Foyer | Plafond |")
    assert lines[i + 1] == "| --- | --- |"
    assert lines[i + 2] == "| 1 personne | 10 000 € |"


def test_links_inside_text(fiche):
    assert "Faire la demande en ligne (https://example.gouv.fr/teleservice)" in fiche.text
    assert "Mairie (https://lannuaire.service-public.gouv.fr/navigation/mairie)" in fiche.text
    assert "Sur rendez-vous." in fiche.text
    assert "Ministère chargé des tests" not in fiche.text


def test_questionnaire_logic_is_dropped(fiche):
    assert "Où habitez-vous" not in fiche.text
    assert "T1" not in fiche.text


def test_iter_fiches_only_reads_fiches(tmp_path):
    (tmp_path / "F99999.xml").write_bytes((FIXTURES / "F99999.xml").read_bytes())
    (tmp_path / "R1.xml").write_text("<Publication/>")
    assert [f.id for f in iter_fiches(tmp_path)] == ["F99999"]


def test_pro_fiche_without_spurl_gets_entreprendre_url(tmp_path):
    xml = (FIXTURES / "F99999.xml").read_text(encoding="utf-8")
    path = tmp_path / "F99999.xml"
    path.write_text(re.sub(r' spUrl="[^"]*"', "", xml), encoding="utf-8")
    f = parse_fiche(path, "professionnels")
    assert f.audiences == ["professionnels"]
    assert f.url == "https://entreprendre.service-public.gouv.fr/vosdroits/F99999"


def _fiche(fid: str, audience: str, text: str) -> Fiche:
    url = f"https://{audience}.example/{fid}"
    return Fiche(id=fid, title=fid, type="", audiences=[audience], summary="", text=text, url=url,
                 urls={audience: url}, updated_at="2026-01-01", important_update_at=None, theme=None)


def test_merge_feeds_keeps_one_fiche_with_both_urls():
    merged = merge_feeds({
        "particuliers": iter([_fiche("F1", "particuliers", "part text"), _fiche("F2", "particuliers", "")]),
        "professionnels": iter([_fiche("F1", "professionnels", "pro text"), _fiche("F3", "professionnels", "")]),
    })
    assert [f.id for f in merged] == ["F1", "F2", "F3"]
    f1 = merged[0]
    assert f1.audiences == ["particuliers", "professionnels"]
    assert f1.urls == {"particuliers": "https://particuliers.example/F1",
                       "professionnels": "https://professionnels.example/F1"}
    assert (f1.url, f1.text) == ("https://particuliers.example/F1", "part text")  # first feed is primary
    assert merged[2].audiences == ["professionnels"]


def test_missing_date_is_an_error(tmp_path):
    bad = tmp_path / "F1.xml"
    bad.write_text('<Publication ID="F1"><Audience>Particuliers</Audience></Publication>')
    with pytest.raises(ValueError, match="no update date"):
        parse_fiche(bad)


# --- Repeated blocks, titles and links (fixture shaped like F827) ---

POINTER = "[Paperasse : identique à « En savoir plus si vous avez oublié de déclarer » plus haut (sous « Caisse A > Déménagement »).]"


@pytest.fixture(scope="module")
def repeated():
    return parse_fiche(FIXTURES / "F99998.xml").text


def test_repeated_block_is_printed_once_then_pointed_to(repeated):
    assert repeated.count("C'est le droit à l'erreur.") == 1
    assert repeated.count(POINTER) == 2
    # The first copy stays where the XML puts it, under its own title.
    lines = repeated.splitlines()
    assert lines.index("#### En savoir plus si vous avez oublié de déclarer") < lines.index("### Naissance")


def test_short_repeated_paragraph_is_kept_in_each_case(repeated):
    # Below DEDUP_MIN_CHARS a pointer would be as long as the text it replaces.
    assert repeated.count("Signalez votre nouvelle adresse dans votre espace en ligne") == 2


def test_link_blocks_keep_their_url_in_every_case(repeated):
    assert repeated.count("Déclarer un changement (https://example.gouv.fr/declarer)") == 2


def test_inline_links_keep_their_url(repeated):
    assert "[le site des erreurs fréquentes](https://example.gouv.fr/erreurs) qui explique" in repeated
    assert "[l'aide au logement](https://www.service-public.gouv.fr/particuliers/vosdroits/F1563)" in repeated
    assert "[la fiche pro](https://entreprendre.service-public.gouv.fr/vosdroits/F23961)" in repeated
    # Acronyms and glossary terms have no page of their own.
    assert "et la CSE, ou" in repeated


def test_table_summary_and_reference_are_rendered(repeated):
    assert "Ce tableau présente les délais de test." in repeated
    assert "Code de test : article 1 (https://www.legifrance.gouv.fr/test)" in repeated
    assert "Délais de déclaration" in repeated


def test_strip_links():
    assert strip_links("Voir [le site](https://a.gouv.fr/x) ou Mairie (https://b.fr/y).") == "Voir le site ou Mairie."
