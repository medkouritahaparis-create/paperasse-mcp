from pathlib import Path

import pytest

from paperasse.ingest import iter_fiches, parse_fiche

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def fiche():
    return parse_fiche(FIXTURES / "F99999.xml")


def test_metadata(fiche):
    assert fiche.id == "F99999"
    assert fiche.title == "Demande de carte de test"
    assert fiche.audience == "Particuliers"
    assert fiche.summary == "Comment demander une carte de test."
    assert fiche.theme == "Papiers"
    assert fiche.breadcrumb == ["Accueil particuliers", "Papiers"]
    assert fiche.sources == ["https://www.legifrance.gouv.fr/a", "https://www.legifrance.gouv.fr/b"]


def test_source_url_and_dates(fiche):
    assert fiche.url == "https://www.service-public.gouv.fr/particuliers/vosdroits/F99999"
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


def test_missing_date_is_an_error(tmp_path):
    bad = tmp_path / "F1.xml"
    bad.write_text('<Publication ID="F1"><Audience>Particuliers</Audience></Publication>')
    with pytest.raises(ValueError, match="no update date"):
        parse_fiche(bad)
